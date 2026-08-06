"""Self-hosted AI4Bharat IndicTrans2 (en->indic, distilled 200M).

Same role as nllb_translator.py -- a local, no-API-key, no-rate-limit
translation backend -- and the same public surface (translate_alert /
translate_categories with identical signatures and return shapes), so
job.py dispatches to either without knowing the difference.

Chosen for evaluation against NLLB for one structural reason: NLLB-200
spends its capacity across 200 languages, while IndicTrans2 spends all of
its on Indic ones. That matters here because NLLB's SMALL checkpoint was
already rejected for this workload -- the 600M-distilled model produced a
repetition loop and, on financial text, a sign flip ("gained 3.5%"
rendered as a decline), which is why nllb_translator.py pins the 1.3B
checkpoint. IndicTrans2's 200M distilled checkpoint is a different
tradeoff, not simply "a smaller model", so it is worth measuring rather
than assuming.

MEMORY: this is the reason the model choice matters operationally. The
1.3B NLLB checkpoint could not be co-tenanted with FastAPI + scheduler +
DB pool on the Railway deploy target -- the process was silently
OOM-killed a few translation cycles after boot (2026-07-24). At ~200M
parameters this model is roughly a sixth of that resident footprint.

TRANSFORMERS VERSION: IndicTrans2 ships a *slow* (pure-Python) tokenizer
via trust_remote_code. transformers 5.x removed slow tokenizers entirely,
so this module requires transformers 4.x -- see requirements.txt, which
pins it. CTranslate2 is NOT an option for this model the way it is for
NLLB: CT2's transformers converter has no loader registered for
IndicTransConfig (verified against ctranslate2 4.8.1), so the weights
cannot be converted without writing a custom converter.
"""
import os
import re
import threading

# Downloaded and cached at image build time so the running container never
# depends on HuggingFace at runtime (same policy as the NLLB model dir).
# ai4bharat/indictrans2-en-indic-dist-200M is the canonical repo but is
# HF-GATED; this mirror is the only ungated copy that carries the COMPLETE
# package -- other mirrors ship config + weights but omit
# tokenization_indictrans.py and the dict.SRC/dict.TGT sentencepiece
# models, so AutoTokenizer cannot be constructed from them at all.
MODEL_NAME = os.environ.get(
    "INDICTRANS2_MODEL", "naklitechie/indictrans2-en-indic-dist-200M"
)

# IndicTrans2 uses FLORES-200 codes, same as NLLB.
INDICTRANS2_LANG_CODES = {
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

# Held equal to nllb_translator.py's BEAM_SIZE on purpose: that value was
# tuned there against a real repetition-loop failure, and matching it keeps
# any observed difference between the two a property of the MODEL rather
# than of the decoding parameters.
BEAM_SIZE = 5
MAX_LENGTH = 256

_model = None
_tokenizer = None
_processor = None
_init_lock = threading.Lock()

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def _get_model():
    """Lazy singleton, loaded on first use rather than at import time so
    importing this module costs nothing when TRANSLATION_PROVIDER is
    something else. Double-checked locking because job.py runs translation
    lanes on concurrent worker threads and the model must load exactly
    once."""
    global _model, _tokenizer, _processor
    if _model is None:
        with _init_lock:
            if _model is None:
                from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

                from app.translation._indic_processor import IndicProcessor

                tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
                model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME, trust_remote_code=True)
                model.eval()
                _tokenizer = tokenizer
                _processor = IndicProcessor(inference=True)
                _model = model  # assigned last: nothing may observe a half-built trio
    return _model, _tokenizer, _processor


def _split_sentences(text: str) -> list[str]:
    """Same boundary heuristic as nllb_translator._split_sentences and the
    frontend's splitRationaleIntoPoints -- period/!/? followed by a capital.

    Kept for IndicTrans2 as well, for two reasons. IndicTrans2 is trained
    on sentence-level pairs, so a multi-sentence input is out of
    distribution; and NLLB was observed silently DROPPING a trailing
    sentence in 6 of 9 languages on real financial text. Splitting removes
    the failure mode by construction rather than hoping this model does not
    share it, and keeps the two providers comparable.
    """
    if not text or not text.strip():
        return []
    return [p.strip() for p in _SENTENCE_SPLIT_RE.split(text.strip()) if p.strip()]


def _translate_sentences(sentences: list[str], lang_code: str) -> list[str]:
    """One batched forward pass. Empty input short-circuits -- the tokenizer
    raises on an empty batch, and an alert with no translatable text is
    ordinary (every field can legitimately be empty)."""
    if not sentences:
        return []
    import torch

    model, tokenizer, processor = _get_model()
    prepared = processor.preprocess_batch(sentences, src_lang="eng_Latn", tgt_lang=lang_code)
    inputs = tokenizer(prepared, truncation=True, padding="longest", return_tensors="pt")
    with torch.no_grad():
        generated = model.generate(
            **inputs,
            num_beams=BEAM_SIZE,
            max_length=MAX_LENGTH,
            num_return_sequences=1,
        )
    decoded = tokenizer.batch_decode(generated, skip_special_tokens=True)
    return processor.postprocess_batch(decoded, lang=lang_code)


def translate_alert(
    *, lang: str, title: str, content: str, companies: list[dict],
    summary_short: str = "", summary_long: str = "",
) -> dict:
    """Signature and return shape are identical to
    groq_translator.translate_alert and nllb_translator.translate_alert
    (`{"title", "content", "summary_short", "summary_long", "companies":
    [{"rationale", "key_points", "why"}, ...]}`) so job.py's persistence
    and validation logic is provider-agnostic.

    Every field's sentences are flattened into ONE batch and translated in a
    single forward pass -- batching, not per-field calls, is what makes a
    local model fast enough to be practical.
    """
    lang_code = INDICTRANS2_LANG_CODES[lang]

    title_sentences = _split_sentences(title)
    content_sentences = _split_sentences(content)
    summary_short_sentences = _split_sentences(summary_short) if summary_short else []
    summary_long_sentences = _split_sentences(summary_long) if summary_long else []
    rationale_per_company = [_split_sentences(c["rationale"]) for c in companies]
    key_points_per_company = [c["key_points"] for c in companies]  # already short fragments
    why_per_company = [
        _split_sentences(c.get("why") or "") if c.get("why") else [] for c in companies
    ]

    # Interleaved per company (that company's rationale, then its
    # key_points, then its why) so this ordering matches the take()
    # reassembly below. Grouping all rationales first and all key_points
    # after would silently zip translated text onto the wrong field.
    batch: list[str] = [
        *title_sentences, *content_sentences,
        *summary_short_sentences, *summary_long_sentences,
    ]
    for rationale, key_points, why in zip(
        rationale_per_company, key_points_per_company, why_per_company
    ):
        batch += rationale
        batch += key_points
        batch += why

    translated = _translate_sentences(batch, lang_code)

    cursor = 0

    def take(n: int) -> list[str]:
        nonlocal cursor
        chunk = translated[cursor:cursor + n]
        cursor += n
        return chunk

    out_title = " ".join(take(len(title_sentences)))
    out_content = " ".join(take(len(content_sentences)))
    out_summary_short = " ".join(take(len(summary_short_sentences)))
    out_summary_long = " ".join(take(len(summary_long_sentences)))

    out_companies = []
    for rationale, key_points, why in zip(
        rationale_per_company, key_points_per_company, why_per_company
    ):
        out_companies.append({
            "rationale": " ".join(take(len(rationale))),
            "key_points": take(len(key_points)),
            "why": " ".join(take(len(why))),
        })

    return {
        "title": out_title,
        "content": out_content,
        "summary_short": out_summary_short,
        "summary_long": out_summary_long,
        "companies": out_companies,
    }


def translate_categories(categories: list[str], lang: str) -> list[str]:
    """Category labels are short single fragments -- no sentence splitting.

    Underscore-joined category strings ("oil_energy") are turned into an
    English phrase first: IndicTrans2 is a pure translation model with no
    instruction following, so unlike the LLM path there is no prompt in
    which to explain the convention. Same substitution nllb_translator
    performs for the same reason.
    """
    lang_code = INDICTRANS2_LANG_CODES[lang]
    phrases = [c.replace("_", " ").title() for c in categories]
    return _translate_sentences(phrases, lang_code)
