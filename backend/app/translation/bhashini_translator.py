"""Bhashini / ULCA (MeitY, Government of India) hosted translation.

Same public surface as nllb_translator / indictrans2_translator
(translate_alert / translate_categories with identical signatures and
return shapes), so job.py dispatches to it without change.

The opposite tradeoff to the self-hosted providers: no model in process, so
none of the memory pressure that got NLLB-1.3B OOM-killed on this deploy
target, and no transformers version pin. In exchange it is a network
dependency on a free government service -- treat availability as unknown
rather than assumed, which is exactly what job.py's TranslationFailure
attempt counter and RETRY_COOLDOWN already handle for any provider.

Credentials come from the environment, never from source:
    BHASHINI_USER_ID   -- ULCA userID
    BHASHINI_API_KEY   -- ULCA API key
Both are issued from the ULCA dashboard at bhashini.gov.in.

PROTOCOL: two steps, which is why this is not a plain POST.
  1. getModelsPipeline -- authenticate and ask which service can do
     en->{lang}. The reply carries a per-language inference endpoint AND
     its own auth header/value, distinct from the ULCA credentials.
  2. that endpoint -- the actual translation call.
Step 1 is pure service discovery and its result is cached per language for
the process's life; re-running it per batch would add a full round trip of
directory lookup to every translation.
"""
import logging
import os
import threading

import httpx

logger = logging.getLogger(__name__)

AUTH_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
# MeitY's public translation pipeline. Overridable because ULCA publishes
# more than one and an org may be issued its own.
PIPELINE_ID = os.environ.get("BHASHINI_PIPELINE_ID", "64392f96daac500b55c543cd")

# Bhashini speaks ISO-639-1, which coincides with TARGET_LANGS for all nine
# languages -- mapped explicitly anyway so a future TARGET_LANGS addition
# fails loudly here instead of silently sending an unsupported code.
BHASHINI_LANG_CODES = {
    "hi": "hi", "mr": "mr", "gu": "gu", "ml": "ml", "te": "te",
    "ta": "ta", "kn": "kn", "pa": "pa", "bn": "bn",
}

DISCOVERY_TIMEOUT = 60.0
TRANSLATE_TIMEOUT = 180.0

_pipelines: dict[str, dict] = {}
_pipeline_lock = threading.Lock()


def _credentials() -> tuple[str, str]:
    user_id = os.environ.get("BHASHINI_USER_ID", "").strip()
    api_key = os.environ.get("BHASHINI_API_KEY", "").strip()
    if not user_id or not api_key:
        raise RuntimeError(
            "TRANSLATION_PROVIDER is 'bhashini' but BHASHINI_USER_ID / "
            "BHASHINI_API_KEY are not set (get them from the ULCA dashboard "
            "at bhashini.gov.in)"
        )
    return user_id, api_key


def _pipeline(lang: str) -> dict:
    """Resolve (and cache) the inference endpoint for one target language.

    Locked because job.py runs lanes concurrently and several threads can
    reach an uncached language at once -- without the lock they would each
    issue their own discovery call. A duplicate call is harmless but wasteful
    against a shared free-tier service.
    """
    cached = _pipelines.get(lang)
    if cached is not None:
        return cached
    with _pipeline_lock:
        cached = _pipelines.get(lang)
        if cached is not None:
            return cached

        user_id, api_key = _credentials()
        target = BHASHINI_LANG_CODES[lang]
        response = httpx.post(
            AUTH_URL,
            headers={"userID": user_id, "ulcaApiKey": api_key},
            json={
                "pipelineTasks": [{
                    "taskType": "translation",
                    "config": {"language": {"sourceLanguage": "en", "targetLanguage": target}},
                }],
                "pipelineRequestConfig": {"pipelineId": PIPELINE_ID},
            },
            timeout=DISCOVERY_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
        try:
            task = body["pipelineResponseConfig"][0]
            endpoint = body["pipelineInferenceAPIEndPoint"]
            config = {
                "service_id": task["config"][0]["serviceId"],
                "url": endpoint["callbackUrl"],
                "auth_header": endpoint["inferenceApiKey"]["name"],
                "auth_value": endpoint["inferenceApiKey"]["value"],
            }
        except (KeyError, IndexError) as exc:
            # A 200 with an unexpected body means ULCA changed its response
            # shape or has no service for this pair -- surface it as a
            # translation failure rather than a KeyError deep in job.py.
            raise ValueError(f"unexpected getModelsPipeline response for lang={lang}: {exc}") from exc

        _pipelines[lang] = config
        return config


def _translate_texts(texts: list[str], lang: str) -> list[str]:
    """One request carrying the whole batch. Bhashini accepts a list, so a
    batch costs one round trip regardless of size -- but processing is
    sequential server-side, so wall-clock still scales with batch length.

    Returns outputs positionally aligned with `texts`. A length mismatch is
    raised rather than tolerated: job.py zips translated company text back
    onto AlertCompany rows BY INDEX, so a short array would silently attach
    text to the wrong company.
    """
    if not texts:
        return []
    config = _pipeline(lang)
    target = BHASHINI_LANG_CODES[lang]
    response = httpx.post(
        config["url"],
        headers={config["auth_header"]: config["auth_value"], "Content-Type": "application/json"},
        json={
            "pipelineTasks": [{
                "taskType": "translation",
                "config": {
                    "language": {"sourceLanguage": "en", "targetLanguage": target},
                    "serviceId": config["service_id"],
                },
            }],
            "inputData": {"input": [{"source": t} for t in texts]},
        },
        timeout=TRANSLATE_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    try:
        outputs = body["pipelineResponse"][0]["output"]
    except (KeyError, IndexError) as exc:
        raise ValueError(f"unexpected translation response for lang={lang}: {exc}") from exc
    if len(outputs) != len(texts):
        raise ValueError(
            f"bhashini returned {len(outputs)} outputs for {len(texts)} inputs (lang={lang})"
        )
    return [o.get("target", "") for o in outputs]


def translate_alert(
    *, lang: str, title: str, content: str, companies: list[dict],
    summary_short: str = "", summary_long: str = "",
) -> dict:
    """Identical signature/return shape to the other providers.

    Unlike the local models this does NOT split into sentences: Bhashini is
    a hosted pipeline that handles multi-sentence input itself, and
    splitting would multiply the number of items in an already
    sequentially-processed request for no quality gain.

    Empty fields are passed through as empty rather than sent -- an empty
    source is legitimate (alerts predating summary_short/why have them), and
    sending empty strings wastes quota and risks the service echoing
    something non-empty back.
    """
    fields: list[str] = []
    slots: list[tuple[str, int]] = []  # (which field, index into `fields`), for reassembly

    def add(name: str, value: str) -> None:
        if value and value.strip():
            slots.append((name, len(fields)))
            fields.append(value)
        else:
            slots.append((name, -1))

    add("title", title)
    add("content", content)
    add("summary_short", summary_short)
    add("summary_long", summary_long)
    for company in companies:
        add("rationale", company["rationale"])
        for point in company["key_points"]:
            add("key_point", point)
        add("why", company.get("why") or "")

    translated = _translate_texts(fields, lang)

    def value_at(index: int) -> str:
        return translated[index] if index >= 0 else ""

    cursor = 0

    def next_slot() -> str:
        nonlocal cursor
        _, index = slots[cursor]
        cursor += 1
        return value_at(index)

    out_title = next_slot()
    out_content = next_slot()
    out_summary_short = next_slot()
    out_summary_long = next_slot()

    out_companies = []
    for company in companies:
        rationale = next_slot()
        key_points = [next_slot() for _ in company["key_points"]]
        why = next_slot()
        out_companies.append({"rationale": rationale, "key_points": key_points, "why": why})

    return {
        "title": out_title,
        "content": out_content,
        "summary_short": out_summary_short,
        "summary_long": out_summary_long,
        "companies": out_companies,
    }


def translate_categories(categories: list[str], lang: str) -> list[str]:
    """Same underscore-to-phrase substitution the other non-LLM provider
    performs: Bhashini is a translation pipeline with no prompt in which to
    explain that 'oil_energy' means 'Oil & Energy'."""
    phrases = [c.replace("_", " ").title() for c in categories]
    return _translate_texts(phrases, lang)
