import json
from types import SimpleNamespace

import httpx
from anthropic import Anthropic
from anthropic import APIError as AnthropicAPIError
from openai import OpenAI, RateLimitError

from app.analysis.usage_log import (
    record_usage, usage_from_anthropic, usage_from_gemini, usage_from_openai,
)
from app.config import (
    LLM_TIER_CHEAP, LLM_TIER_MODELS, PROMPT_CACHE_CONTROL, resolve_tier, settings,
)

# Anthropic is the primary provider when a real (funded) key is configured --
# best quality, native forced tool-use. Groq is the fallback so a real,
# funded key is never wasted on calls that a free provider could have
# served, and so the app keeps working if Anthropic's own rate limit is hit.
ANTHROPIC_MODEL = "claude-sonnet-4-5"

# Gemini is the analysis pipeline's primary provider (replaces the dead
# Anthropic slot -- see docs/superpowers/specs/2026-07-27-gemini-primary-
# reasoning-provider-design.md). "gemini-flash-latest" is an alias Google
# keeps pointed at their current recommended flash model, not a dated
# version string -- same reasoning as FALLBACK_MODEL's own history below
# (a hardcoded model name needs a manual swap when a provider deprecates
# it; an alias doesn't).
GEMINI_MODEL = "gemini-flash-latest"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiAPIError(Exception):
    """Raised on any non-2xx response from the Gemini API, and on any
    httpx.HTTPError raised before a response even exists (connection
    refused, DNS failure, connect/read timeout) -- covers rate limits/quota
    exhaustion (429), auth failures, server errors, and network/connection
    failures alike, same "any provider-level failure should degrade to the
    fallback provider" discipline AnthropicAPIError already provides for
    Anthropic.
    """


MODEL = "llama-3.3-70b-versatile"
# Groq enforces daily token quotas PER MODEL, not per key -- multiple keys on
# the same org share one quota bucket for a given model (confirmed: 3 keys
# from the same org all hit the same "org_..." rate-limit error for MODEL at
# the same time). FALLBACK_MODEL is a different model family (its own
# SEPARATE quota bucket), used only when MODEL is rate-limited -- best
# quality when available, still available when the primary model's daily
# budget is exhausted.
#
# Was llama-3.1-8b-instant (8B) -- confirmed live (both in production logs
# and this app's own reanalysis runs) to fail record_sectors/
# record_sector_companies' schema constantly: wrong field types, missing
# required properties, invented enum values. openai/gpt-oss-20b is still a
# distinct model/quota bucket from MODEL, but OpenAI's gpt-oss family is
# specifically built for reliable native tool/function calling, a much
# better fit for this app's strict, deeply-nested tool schemas than a
# generic small Llama model.
FALLBACK_MODEL = "openai/gpt-oss-20b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# How each provider this client layer can talk to handles a repeated,
# cacheable prompt prefix (cost-optimization phase 2). "explicit" = the
# request carries a per-block cache_control marker (Anthropic).
# "implicit" = the provider caches a repeated prefix on its own with
# nothing to mark, so the only thing the caller controls is putting stable
# content first (Gemini). "none" = the provider has no prompt-cache API,
# and caching degrades to a no-op rather than an error (Groq's
# OpenAI-compatible endpoint). Prompt caching never changes what the model
# is sent or what it returns -- only what the call is billed -- so a
# provider landing in "none" costs more but behaves identically.
PROMPT_CACHE_SUPPORT = {"anthropic": "explicit", "gemini": "implicit", "groq": "none"}


def tier_kwargs(call_name: str) -> dict:
    """The two kwargs every LLM call site in this app passes, spelled once:
    which logical call this is (for token accounting) and which model tier
    should serve it (app.config.resolve_tier, which refuses to downgrade a
    protected call). Usage: ``client.chat.completions.create(...,
    **tier_kwargs("extract_facts"))``."""
    return {"tier": resolve_tier(call_name), "call_name": call_name}

SYSTEM_PROMPT = (
    "You are an elite equity research analyst at a global hedge fund, with "
    "20+ years covering Indian and global markets across every major sector "
    "-- oil & gas, banking, autos, IT services, pharma, FMCG, metals, "
    "telecom, and infrastructure. You have deep, current knowledge of real "
    "companies, their actual business models, supply chains, customer "
    "relationships, competitive positioning, and what genuinely moves their "
    "earnings. You reason the way an experienced desk analyst does: "
    "skeptical by default, unwilling to state a causal link you can't "
    "actually defend, and comfortable saying \"nothing tradeable here\" when "
    "that's the honest read.\n\n"
    "Before naming ANY affected sector or company, you first understand the "
    "event itself: what actually happened; whether it is fundamentally "
    "bullish, bearish, or neutral; whether it is a TEMPORARY issue or a "
    "STRUCTURAL change; whether it is COMPANY-SPECIFIC or INDUSTRY-WIDE; "
    "and what the true market interpretation is (demand destruction, demand "
    "acceleration, timing delay, margin pressure, cost inflation, "
    "competitive pressure, execution risk, regulatory risk, sentiment only, "
    "or a one-time event). A company-specific, temporary event -- one "
    "firm's earnings miss, stock drop, CEO commentary, or execution stumble "
    "-- rarely transmits beyond that company and its directly-named "
    "counterparties; for such events the honest output is usually the "
    "company itself and little or nothing else.\n\n"
    "Your causal chains are precise, one link at a time (\"X raises AI "
    "capex -> GPU demand rises -> memory demand rises -> power and cooling "
    "demand rises\"), never a theme-level jump (\"X moved -> everything in "
    "the theme moves\"). You never rely on superficial keyword or theme "
    "similarity, and you never include a company merely because it is in "
    "the same industry or the same buzzword universe as the story.\n\n"
    "Final reality check on every sector and company you name: would an "
    "institutional investor realistically trade THAT security TODAY because "
    "of THIS news, and would a professional analyst put it in a same-day "
    "research note about this event? If the relationship is only thematic, "
    "speculative, or sector-similarity, you discard it. You determine what "
    "is affected strictly from what THIS article says -- never from outside "
    "assumptions, general market sentiment, or what would be a plausible-"
    "sounding guess. If the article doesn't support a specific, defensible "
    "call, you don't manufacture one."
)


class _RotatingCompletions:
    def __init__(self, rotator: "RotatingClient"):
        self._rotator = rotator

    def create(self, **kwargs):
        return self._rotator._call(**kwargs)


class _RotatingChat:
    def __init__(self, rotator: "RotatingClient"):
        self.completions = _RotatingCompletions(rotator)


class RotatingClient:
    """Duck-types the subset of the OpenAI client surface analyze_article
    uses (client.chat.completions.create(...)), backed by multiple API keys.

    On a RateLimitError from the currently active key, tries the next key in
    the rotation before giving up -- a rate-limited key stays "current" for
    subsequent calls once another key is found to work, rather than resetting
    to the first key every time (so a working key isn't abandoned prematurely
    on the next call). Any error OTHER than a rate limit is not a rotation
    trigger -- it propagates immediately, so a genuine bug isn't masked by
    silently trying more keys.
    """

    def __init__(self, api_keys: list[str], base_url: str):
        if not api_keys:
            raise ValueError("RotatingClient requires at least one API key")
        self._clients = [OpenAI(api_key=key, base_url=base_url) for key in api_keys]
        self._active = 0
        self.chat = _RotatingChat(self)

    def _call(self, **kwargs):
        last_error: RateLimitError | None = None
        for offset in range(len(self._clients)):
            index = (self._active + offset) % len(self._clients)
            try:
                result = self._clients[index].chat.completions.create(**kwargs)
                self._active = index
                return result
            except RateLimitError as exc:
                last_error = exc
                continue
        raise last_error


_JSON_SCHEMA_TO_GEMINI_TYPE = {
    "object": "OBJECT", "string": "STRING", "boolean": "BOOLEAN",
    "number": "NUMBER", "integer": "INTEGER", "array": "ARRAY",
}


def _uppercase_schema_types(schema: dict) -> dict:
    """Gemini's function-declaration parameter schema requires uppercase
    type strings ("OBJECT", "STRING", ...) -- every tool builder in this
    codebase emits lowercase JSON Schema ("object", "string", ...), the
    format every OTHER provider here (OpenAI-shape Groq, Anthropic)
    accepts as-is. Confirmed live: Gemini rejects/misbehaves on lowercase.
    Recursively walks `properties` (object schemas) and `items` (array
    schemas) -- two places a nested schema can appear in this codebase's
    tool definitions -- uppercasing every `type` key found, leaving
    `description`/`enum`/`required` untouched.

    A third shape also occurs (e.g. cascade.py's nullable `ticker` field):
    JSON Schema's list-valued `"type": ["string", "null"]`, meaning
    "string or null". Gemini's schema format has no equivalent list -- it
    takes a single uppercase `"type"` string plus a separate boolean
    `"nullable"` flag. Every list-valued `type` actually present in this
    codebase's tool schemas is exactly this 2-element `[<real type>, "null"]`
    shape, so that's the only list shape handled here: the non-"null" entry
    is uppercased and used as `type`, and `nullable` is set whenever "null"
    was present in the list.
    """
    result = dict(schema)
    if isinstance(result.get("type"), list):
        type_list = result["type"]
        real_types = [t for t in type_list if t != "null"]
        if len(real_types) != 1:
            raise ValueError(f"Unsupported list-valued JSON Schema type: {type_list!r}")
        result["type"] = _JSON_SCHEMA_TO_GEMINI_TYPE.get(real_types[0], real_types[0])
        if "null" in type_list:
            result["nullable"] = True
    elif "type" in result:
        result["type"] = _JSON_SCHEMA_TO_GEMINI_TYPE.get(result["type"], result["type"])
    if "properties" in result:
        result["properties"] = {k: _uppercase_schema_types(v) for k, v in result["properties"].items()}
    if "items" in result:
        result["items"] = _uppercase_schema_types(result["items"])
    return result


class _GeminiCompletions:
    """Translates an OpenAI-shape chat.completions.create(...) call into a
    Gemini generateContent REST call and translates the response back --
    same duck-typing contract as _AnthropicCompletions, one provider over.
    """

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

    def create(self, *, max_tokens, tools, messages, tier=None, call_name=None, **_ignored):
        # Model tiering (cost-optimization phase 4): only a CHEAP tier
        # changes anything. A reasoning-tier call (the default for every
        # call site, and the only thing a protected call can ever be) is
        # sent on this adapter's own configured model, exactly as it was
        # before tiering existed.
        model = LLM_TIER_MODELS["gemini"][LLM_TIER_CHEAP] if tier == LLM_TIER_CHEAP else self._model
        system_content = None
        contents = []
        for m in messages:
            if m["role"] == "system":
                system_content = m["content"]
            else:
                contents.append({"role": "user", "parts": [{"text": m["content"]}]})

        function_spec = tools[0]["function"]
        function_declaration = {
            "name": function_spec["name"],
            "description": function_spec["description"],
            "parameters": _uppercase_schema_types(function_spec["parameters"]),
        }

        # Prompt caching (cost-optimization phase 2) needs no marker here.
        # Gemini caches a repeated request prefix implicitly and bills the
        # hit automatically -- there is no cache_control field to set, and
        # its EXPLICIT cache (cachedContents) is the wrong tool for this
        # traffic: it has a minimum-token floor this system prompt is well
        # under, and it charges storage per cache entry. What implicit
        # caching does require is that the repeated content actually leads
        # the request, which the shape below gives it: the stable system
        # prompt rides `systemInstruction` and the stable tool schema rides
        # `tools`, both separate from `contents`, whose own text is built
        # stable-part-first by every call site (see app.analysis.cascade).
        body = {
            "contents": contents,
            "tools": [{"function_declarations": [function_declaration]}],
            "tool_config": {"function_calling_config": {"mode": "ANY"}},
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system_content is not None:
            body["systemInstruction"] = {"parts": [{"text": system_content}]}

        url = f"{GEMINI_BASE_URL}/models/{model}:generateContent?key={self._api_key}"
        try:
            response = httpx.post(url, json=body, timeout=60.0)
        except httpx.HTTPError as exc:
            # Raised by httpx BEFORE any response exists (DNS failure, refused
            # connection, read/connect timeout, ...) -- no status code to
            # inspect, so this can't go through the status-code branch below.
            # Re-raised as GeminiAPIError so FallbackClient's except tuple
            # still catches it and degrades to Groq instead of the raw httpx
            # exception propagating out of the whole pipeline. Deliberately
            # built from type(exc).__name__, not `exc`/`str(exc)`'s own
            # request -- `url` above embeds the API key as a query param
            # (Gemini's documented auth method), and we never want a key to
            # end up in a log line via an exception's string form.
            raise GeminiAPIError(f"Gemini API request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise GeminiAPIError(f"Gemini API returned {response.status_code}: {response.text}")

        data = response.json()
        record_usage(usage_from_gemini(data, call_name=call_name, model=model, tier=tier))
        candidates = data.get("candidates") or []
        # A safety block or MAX_TOKENS truncation omits "content" entirely
        # (finishReason: "SAFETY"/"MAX_TOKENS" with no content key) -- .get(...)
        # falls through to the same empty-tool_calls path as an ordinary
        # response with no function call, instead of a raw KeyError crash.
        content = candidates[0].get("content", {}) if candidates else {}
        parts = content.get("parts", [])
        function_call = next((p["functionCall"] for p in parts if "functionCall" in p), None)

        if function_call is None:
            fake_tool_calls = []
        else:
            fake_tool_calls = [SimpleNamespace(
                function=SimpleNamespace(name=function_call["name"], arguments=json.dumps(function_call["args"])),
            )]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=fake_tool_calls))])


class _GeminiChat:
    def __init__(self, api_key: str, model: str):
        self.completions = _GeminiCompletions(api_key, model)


class GeminiAdapter:
    """Duck-types the OpenAI client surface analyze_article uses, backed by
    a raw Gemini generateContent REST call, so the rest of the pipeline
    never needs to know which provider actually served a given call."""

    def __init__(self, api_key: str, model: str = GEMINI_MODEL):
        self.chat = _GeminiChat(api_key, model)


class _AnthropicCompletions:
    """Translates an OpenAI-shape chat.completions.create(...) call into a
    native Anthropic messages.create(...) call and translates the response
    back into the OpenAI response shape -- so analyze_article's parsing code
    (response.choices[0].message.tool_calls[...]) works unchanged for either
    provider. The `model` kwarg passed in is ignored; this always calls this
    adapter's own configured model (ANTHROPIC_MODEL by default), since
    callers pass Groq model names meant for the Groq path.
    """

    def __init__(self, anthropic_client: Anthropic, model: str = ANTHROPIC_MODEL):
        self._client = anthropic_client
        self._model = model

    def create(self, *, max_tokens, tools, messages, tier=None, call_name=None, **_ignored):
        # See _GeminiCompletions.create -- only a CHEAP tier overrides the
        # adapter's configured model.
        model = LLM_TIER_MODELS["anthropic"][LLM_TIER_CHEAP] if tier == LLM_TIER_CHEAP else self._model
        system_content = None
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system_content = m["content"]
            else:
                chat_messages.append({"role": m["role"], "content": m["content"]})

        function_spec = tools[0]["function"]
        anthropic_tool = {
            "name": function_spec["name"],
            "description": function_spec["description"],
            "input_schema": function_spec["parameters"],
        }

        # Prompt caching (cost-optimization phase 2). Anthropic assembles a
        # request's cacheable prefix in a fixed order -- tools, then system,
        # then messages -- so a breakpoint on the tool schema caches the
        # tools block and a breakpoint on the system block caches
        # tools+system. Both are byte-identical across this pipeline's
        # calls (SYSTEM_PROMPT is one constant; each stage reuses one tool
        # builder), while only the trailing user message varies, so the
        # cached prefix is as long as it can be. This affects billing only:
        # a cache hit and a cache miss send the model the same tokens and
        # produce the same output.
        system_param = system_content
        if settings.prompt_cache_enabled:
            anthropic_tool["cache_control"] = dict(PROMPT_CACHE_CONTROL)
            if system_content is not None:
                system_param = [{
                    "type": "text",
                    "text": system_content,
                    "cache_control": dict(PROMPT_CACHE_CONTROL),
                }]

        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_param,
            tools=[anthropic_tool],
            tool_choice={"type": "tool", "name": anthropic_tool["name"]},
            messages=chat_messages,
        )
        record_usage(usage_from_anthropic(response, call_name=call_name, model=model, tier=tier))
        tool_use = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use is None:
            fake_tool_calls = []
        else:
            fake_tool_calls = [SimpleNamespace(
                function=SimpleNamespace(name=tool_use.name, arguments=json.dumps(tool_use.input)),
            )]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=fake_tool_calls))])


class _AnthropicChat:
    def __init__(self, anthropic_client: Anthropic, model: str = ANTHROPIC_MODEL):
        self.completions = _AnthropicCompletions(anthropic_client, model)


class AnthropicAdapter:
    """Duck-types the OpenAI client surface analyze_article uses, backed by
    the native Anthropic SDK, so the rest of the pipeline never needs to know
    which provider actually served a given call. Accepts an optional
    `model` override -- used by the translation path to call a cheaper/
    faster model than the analysis pipeline's ANTHROPIC_MODEL."""

    def __init__(self, api_key: str, model: str = ANTHROPIC_MODEL):
        self.chat = _AnthropicChat(Anthropic(api_key=api_key), model)


class _GroqCompletions:
    """Adds the two kwargs the provider-native adapters above understand
    (`tier`, `call_name`) to the Groq path, which is a real OpenAI client
    and would reject them outright.

    `tier` only ever downgrades: LLM_TIER_CHEAP swaps in the cheap Groq
    model, and anything else leaves the caller's own `model` kwarg alone.
    That asymmetry is deliberate -- the cascade already picks its Groq model
    per stage for reasons that predate tiering (MODEL and FALLBACK_MODEL sit
    in separate daily quota buckets, and the direct-company stage
    deliberately falls from one to the other), and a reasoning-tier default
    that "promoted" those calls would quietly rewrite that routing.
    """

    def __init__(self, inner):
        self._inner = inner

    def create(self, *, tier=None, call_name=None, **kwargs):
        if tier == LLM_TIER_CHEAP:
            kwargs["model"] = LLM_TIER_MODELS["groq"][LLM_TIER_CHEAP]
        response = self._inner.chat.completions.create(**kwargs)
        record_usage(usage_from_openai(
            response, call_name=call_name, model=kwargs.get("model"), tier=tier,
        ))
        return response


class _GroqChat:
    def __init__(self, inner):
        self.completions = _GroqCompletions(inner)


class GroqAdapter:
    """Thin wrapper over a Groq-backed OpenAI/RotatingClient so the Groq
    path speaks the same create(tier=..., call_name=...) contract as the
    Gemini and Anthropic adapters. `inner` stays reachable so callers (and
    tests) can still see which client is underneath."""

    def __init__(self, inner):
        self.inner = inner
        self.chat = _GroqChat(inner)


class _FallbackCompletions:
    def __init__(self, fallback_client: "FallbackClient"):
        self._fallback_client = fallback_client

    def create(self, **kwargs):
        return self._fallback_client._call(**kwargs)


class _FallbackChat:
    def __init__(self, fallback_client: "FallbackClient"):
        self.completions = _FallbackCompletions(fallback_client)


class FallbackClient:
    """Tries the primary client first; on ANY primary-provider API-level
    failure (rate limit/quota, auth, server error, connection failure --
    GeminiAPIError and AnthropicAPIError each cover all of these for their
    own provider) or an OpenAI-style RateLimitError, falls through to the
    secondary client (Groq, itself possibly a RotatingClient/model-fallback
    already). The analysis pipeline's build_client() wires GeminiAdapter as
    primary (Anthropic's key is dead); AnthropicAdapter is still used as a
    primary elsewhere (translation's own provider selection) -- this class
    stays provider-agnostic on purpose so either caller gets the same
    degrade-to-Groq safety net. A quota/billing failure is a real, expected
    production scenario for any paid or rate-limited API -- not catching it
    here would crash the whole pipeline instead of degrading to the
    fallback provider. Errors from the secondary client itself still
    propagate normally.
    """

    def __init__(self, primary, secondary):
        self._primary = primary
        self._secondary = secondary
        self.chat = _FallbackChat(self)

    def _call(self, **kwargs):
        try:
            return self._primary.chat.completions.create(**kwargs)
        except (RateLimitError, AnthropicAPIError, GeminiAPIError):
            return self._secondary.chat.completions.create(**kwargs)


def build_client(
    groq_api_key: str | list[str], gemini_api_key: str | None = None,
) -> GroqAdapter | FallbackClient:
    """The Groq client is always wrapped in a GroqAdapter, whether it ends
    up as the primary or as FallbackClient's secondary: every client this
    returns must accept the same create(tier=..., call_name=...) contract,
    or a degrade-to-Groq would blow up on kwargs a raw OpenAI client has
    never heard of. GroqAdapter.inner is the client it wraps."""
    if isinstance(groq_api_key, list):
        groq_client = GroqAdapter(RotatingClient(groq_api_key, base_url=GROQ_BASE_URL))
    else:
        groq_client = GroqAdapter(OpenAI(api_key=groq_api_key, base_url=GROQ_BASE_URL))

    if gemini_api_key:
        return FallbackClient(GeminiAdapter(gemini_api_key), groq_client)
    return groq_client
