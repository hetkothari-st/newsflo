"""Stage 2: pure-ish. PDF text extraction plus the LLM-as-READER call.

The model is handed the rationale's own text and may only report what it
can quote. _evidence_in_text is the anti-hallucination gate (spec §4):
an entry whose evidence is not a whitespace-normalized substring of the
document text is discarded -- the model can propose, the document decides.
Empty lists are the correct answer for most rationales.
"""
import json
import re

from openai import RateLimitError
from pypdf import PdfReader

from app import config
from app.analysis.claude_client import FALLBACK_MODEL, MODEL, SYSTEM_PROMPT
from app.reasoning.compliance import validate_no_advice_language

TEXT_CAP_CHARS = 12_000  # business/counterparty prose lives in the opening sections

SUPPLY_FRAMING = (
    "This is a credit-rating agency's rationale document for the company "
    "named below. Write a one-sentence, jargon-free description of what "
    "the company actually does, based only on what this document states. "
    "Report ONLY relationships this document states. Copy the supporting "
    "sentence verbatim into `evidence`. If the document names none, return "
    "empty lists. Do not invent a supplier or customer the document does "
    "not name, and do not include any percentage, price, or buy/sell/hold "
    "language in the business summary."
)


def pdf_text(pdf_path) -> str | None:
    try:
        reader = PdfReader(str(pdf_path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return None
    text = text.strip()
    return text[:TEXT_CAP_CHARS] if text else None


def _normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _evidence_in_text(evidence: str, text: str) -> bool:
    if not evidence or not text:
        return False
    return _normalize_ws(evidence) in _normalize_ws(text)


def build_supply_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_supply_profile",
            "description": "Report the company's business summary and any suppliers/customers this document names, each with a verbatim supporting quote.",
            "parameters": {
                "type": "object",
                "properties": {
                    "business_summary": {"type": ["string", "null"]},
                    "suppliers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "evidence": {"type": "string"},
                            },
                            "required": ["name", "evidence"],
                        },
                    },
                    "customers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "evidence": {"type": "string"},
                            },
                            "required": ["name", "evidence"],
                        },
                    },
                },
                "required": ["business_summary", "suppliers", "customers"],
            },
        },
    }


def _call_supply_tool(client, company_name: str, text: str) -> dict:
    """Returns the parsed tool-call arguments dict, or {} on any failure --
    a malformed/truncated JSON response, an exhausted RateLimitError
    fallback, a missing tool-call, or any other client error all degrade
    to {} rather than raising, same discipline as
    business_profile._call_business_profile_tool. The entire attempt (both
    model attempts, response parsing, and json.loads) is wrapped in one
    outer try/except so nothing here can ever propagate."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{SUPPLY_FRAMING}\n\nCompany: {company_name}\n\nDocument text:\n{text}"},
    ]
    tool = build_supply_tool()

    def _call(model: str):
        return client.chat.completions.create(
            model=model, max_tokens=2048, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_supply_profile"}},
            messages=messages,
        )

    try:
        try:
            response = _call(MODEL)
        except RateLimitError:
            response = _call(FALLBACK_MODEL)
        message = response.choices[0].message
        tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_supply_profile"), None)
        if tool_call is None:
            return {}
        return json.loads(tool_call.function.arguments)
    except Exception:
        return {}


def extract_profile(client, company_name: str, text: str) -> dict | None:
    try:
        raw = _call_supply_tool(client, company_name, text)
    except Exception:
        return None
    if not raw:
        return None

    summary = raw.get("business_summary") or None
    if summary and not validate_no_advice_language(summary).is_valid:
        summary = None

    def gate(entries):
        kept = []
        for entry in entries or []:
            name = (entry.get("name") or "").strip()
            evidence = (entry.get("evidence") or "").strip()
            if name and _evidence_in_text(evidence, text):
                kept.append((name, evidence))
        return kept[: config.SUPPLY_LINK_MAX_PER_RELATION]

    return {
        "business_summary": summary,
        "suppliers": gate(raw.get("suppliers")),
        "customers": gate(raw.get("customers")),
    }
