"""Dedicated LLM capacity for supply-link extraction.

The analysis pipeline and extraction share one Groq organization quota
(100k tokens/day) -- measured 2026-08-07, extraction got the scraps
(~30 docs/day against a 1,600-doc backlog). The user provisioned dedicated
Gemini keys for extraction; this module rotates across them so no single
key's per-day quota is hammered, and falls back to the shared Groq/Gemini
chain only when every dedicated key has failed.

Rotation is round-robin ON FAILURE with a sticky cursor: the client that
just worked keeps serving (Gemini bills/caches per key, and a working key
should not be abandoned mid-stream); any error advances to the next key.
Only when a full cycle of dedicated keys fails does the shared fallback
chain get one attempt -- and if that fails too, the error propagates to
extract_profile, which degrades to llm_failed exactly as before (the
drain's cooldown/breaker logic is unchanged and still the backstop).
"""
from app.analysis.claude_client import GeminiAdapter, build_client
from app.config import settings


class RotatingExtractionClient:
    """Duck-types the one surface extract._call_supply_tool uses:
    ``client.chat.completions.create(...)``."""

    def __init__(self, dedicated_clients: list, shared_fallback):
        self._dedicated = dedicated_clients
        self._shared = shared_fallback
        self._cursor = 0
        self.chat = self  # .chat.completions.create resolves through self
        self.completions = self

    def create(self, **kwargs):
        last_error: Exception | None = None
        for offset in range(len(self._dedicated)):
            index = (self._cursor + offset) % len(self._dedicated)
            try:
                response = self._dedicated[index].chat.completions.create(**kwargs)
                self._cursor = index  # sticky: keep using what works
                return response
            except Exception as exc:  # quota/network/provider -- rotate
                last_error = exc
        if self._shared is not None:
            return self._shared.chat.completions.create(**kwargs)
        raise last_error if last_error else RuntimeError("no extraction clients configured")


def build_extraction_client():
    """The client every extraction call site should use. With no dedicated
    keys configured this is exactly the shared chain -- behaviour identical
    to before this module existed."""
    shared = build_client(settings.groq_api_keys, settings.gemini_api_key or None)
    dedicated = [GeminiAdapter(key) for key in settings.supply_gemini_api_keys]
    if not dedicated:
        return shared
    return RotatingExtractionClient(dedicated, shared)
