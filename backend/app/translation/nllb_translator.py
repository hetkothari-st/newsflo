import re
import threading

import ctranslate2
import transformers

# Self-hosted NLLB-200 via CTranslate2 -- no API key, no rate limit, no per-
# call cost, translation stays entirely on this machine. Chosen over the
# smaller 600M-distilled checkpoint after real testing: the 600M model
# produced a repetition-loop failure and, once, a sign-flip ("gained 3.5%"
# translated as "3.5% decline") on realistic financial-jargon-dense text.
# The 1.3B-distilled checkpoint fixed both. Convert the model once via:
#   .venv/Scripts/python -m ctranslate2.converters.transformers \
#     --model facebook/nllb-200-distilled-1.3B \
#     --output_dir models/nllb-200-distilled-1.3B-int8 --quantization int8
MODEL_DIR = "models/nllb-200-distilled-1.3B-int8"
TOKENIZER_NAME = "facebook/nllb-200-distilled-1.3B"

# NLLB uses FLORES-200 codes, not our ISO-ish TARGET_LANGS codes.
NLLB_LANG_CODES = {
    "hi": "hin_Deva",
    "mr": "mar_Deva",
    "gu": "guj_Gujr",
    "ml": "mal_Mlym",
    "te": "tel_Telu",
    "ta": "tam_Taml",
    "kn": "kan_Knda",
    "pa": "pan_Guru",
    "bn": "ben_Beng",
}

# Generation parameters tuned against real failures observed in testing:
# beam_size=1 (greedy) produced a catastrophic repetition loop on one
# Telugu output (the same syllable repeated hundreds of times) and a
# garbled/hallucinated-character title in Gujarati. beam_size=5 +
# repetition_penalty + no_repeat_ngram_size eliminated both across repeated
# trials. This is slower per call than greedy decoding but NLLB has no
# rate limit to conserve, so there's no reason to trade reliability for it.
BEAM_SIZE = 5
REPETITION_PENALTY = 1.3
NO_REPEAT_NGRAM_SIZE = 3

_translator: ctranslate2.Translator | None = None
_tokenizer = None
_init_lock = threading.Lock()

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def _get_translator():
    """Lazy singleton, loaded on first use (not at import time) so importing
    this module costs nothing when TRANSLATION_PROVIDER isn't "nllb".
    Double-checked locking: multiple worker threads may call this
    concurrently (see job.py), and the model must only load once."""
    global _translator, _tokenizer
    if _translator is None:
        with _init_lock:
            if _translator is None:
                _translator = ctranslate2.Translator(MODEL_DIR, device="cpu", inter_threads=4, intra_threads=1)
                _tokenizer = transformers.AutoTokenizer.from_pretrained(TOKENIZER_NAME, src_lang="eng_Latn")
    return _translator, _tokenizer


def _split_sentences(text: str) -> list[str]:
    """Same sentence-boundary heuristic as
    frontend/src/components/ReasoningPanel.tsx's splitRationaleIntoPoints --
    period/!/? followed by a capital letter. Not real NLP, but consistent
    with how the rest of the app already treats sentence boundaries.

    Splitting matters here for a reason specific to NLLB: asked to translate
    several sentences in one string, it can silently drop a trailing
    sentence -- confirmed in testing, it dropped the second of two
    sentences in 6 of 9 languages on real financial-rationale text.
    Translating one complete sentence per model call sidesteps the failure
    mode entirely (confirmed fixed across all 9 languages after this
    change) rather than trying to prompt or parameter-tune around it.
    """
    if not text or not text.strip():
        return []
    return [p.strip() for p in _SENTENCE_SPLIT_RE.split(text.strip()) if p.strip()]


def _translate_sentences(sentences: list[str], lang_code: str) -> list[str]:
    if not sentences:
        return []
    translator, tokenizer = _get_translator()
    tokenizer.src_lang = "eng_Latn"
    tokenized = [tokenizer.convert_ids_to_tokens(tokenizer.encode(s)) for s in sentences]
    target_prefix = [[lang_code]] * len(sentences)
    results = translator.translate_batch(
        tokenized,
        target_prefix=target_prefix,
        beam_size=BEAM_SIZE,
        repetition_penalty=REPETITION_PENALTY,
        no_repeat_ngram_size=NO_REPEAT_NGRAM_SIZE,
    )
    decoded = []
    for r in results:
        tokens = r.hypotheses[0][1:]  # drop the leading target-language prefix token
        ids = tokenizer.convert_tokens_to_ids(tokens)
        decoded.append(tokenizer.decode(ids, skip_special_tokens=True))
    return decoded


def translate_alert(*, lang: str, title: str, content: str, companies: list[dict]) -> dict:
    """Same call signature/return shape as groq_translator.translate_alert
    (`{"title", "content", "companies": [{"rationale", "key_points"}, ...]}`),
    so job.py can dispatch to either provider without changing its own
    persistence/validation logic. `companies` is
    `[{"rationale": str, "key_points": list[str]}, ...]`.

    Every field's sentences are flattened into ONE list and translated in a
    single batched CT2 call -- batching (not per-field or per-company calls)
    is what makes this fast; a full alert with several companies still
    completes in a few seconds.
    """
    lang_code = NLLB_LANG_CODES[lang]

    title_sentences = _split_sentences(title)
    content_sentences = _split_sentences(content)
    rationale_sentences_per_company = [_split_sentences(c["rationale"]) for c in companies]
    key_points_per_company = [c["key_points"] for c in companies]  # short fragments already, no split needed

    # Interleaved per company (rationale sentences then that company's own
    # key_points) so this matches the take() reassembly order below --
    # batching all rationales first and all key_points after would zip
    # translated text onto the wrong field/company.
    batch: list[str] = [*title_sentences, *content_sentences]
    for rationale_sentences, key_points in zip(rationale_sentences_per_company, key_points_per_company):
        batch += rationale_sentences
        batch += key_points

    translated = _translate_sentences(batch, lang_code)

    cursor = 0

    def take(n: int) -> list[str]:
        nonlocal cursor
        chunk = translated[cursor:cursor + n]
        cursor += n
        return chunk

    translated_title = " ".join(take(len(title_sentences)))
    translated_content = " ".join(take(len(content_sentences)))

    translated_companies = []
    for rationale_sentences, key_points in zip(rationale_sentences_per_company, key_points_per_company):
        translated_rationale = " ".join(take(len(rationale_sentences)))
        translated_key_points = take(len(key_points))
        translated_companies.append({"rationale": translated_rationale, "key_points": translated_key_points})

    return {"title": translated_title, "content": translated_content, "companies": translated_companies}


def translate_categories(categories: list[str], lang: str) -> list[str]:
    """Category labels are short single fragments, not multi-sentence text
    -- no splitting needed, translate the batch directly."""
    lang_code = NLLB_LANG_CODES[lang]
    return _translate_sentences(categories, lang_code)
