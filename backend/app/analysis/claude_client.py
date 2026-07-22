import json
from types import SimpleNamespace

from anthropic import Anthropic
from anthropic import APIError as AnthropicAPIError
from openai import OpenAI, RateLimitError

# Anthropic is the primary provider when a real (funded) key is configured --
# best quality, native forced tool-use. Groq is the fallback so a real,
# funded key is never wasted on calls that a free provider could have
# served, and so the app keeps working if Anthropic's own rate limit is hit.
ANTHROPIC_MODEL = "claude-sonnet-4-5"

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

SYSTEM_PROMPT = (
    "You are a senior equity research analyst with 20+ years covering Indian "
    "and global markets across every major sector -- oil & gas, banking, "
    "autos, IT services, pharma, FMCG, metals, telecom, and infrastructure. "
    "You have deep, current knowledge of real companies, their actual "
    "business models, competitive positioning, and what genuinely moves "
    "their earnings. You reason the way an experienced desk analyst does: "
    "skeptical by default, unwilling to state a causal link you can't "
    "actually defend, and comfortable saying \"nothing tradeable here\" when "
    "that's the honest read. You determine which companies are affected "
    "strictly from what THIS article says -- never from outside assumptions, "
    "general market sentiment, or what would be a plausible-sounding guess. "
    "If the article doesn't support a specific, defensible call, you don't "
    "manufacture one."
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

    def create(self, *, max_tokens, tools, messages, **_ignored):
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

        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_content,
            tools=[anthropic_tool],
            tool_choice={"type": "tool", "name": anthropic_tool["name"]},
            messages=chat_messages,
        )
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


class _FallbackCompletions:
    def __init__(self, fallback_client: "FallbackClient"):
        self._fallback_client = fallback_client

    def create(self, **kwargs):
        return self._fallback_client._call(**kwargs)


class _FallbackChat:
    def __init__(self, fallback_client: "FallbackClient"):
        self.completions = _FallbackCompletions(fallback_client)


class FallbackClient:
    """Tries the primary client (Anthropic) first; on ANY Anthropic API-level
    failure (rate limit, insufficient credit balance, auth, server error,
    connection failure -- anthropic.APIError covers all of these) or an
    OpenAI-style RateLimitError, falls through to the secondary client (Groq,
    itself possibly a RotatingClient/model-fallback already). A credit/billing
    failure is a real, expected production scenario for a paid API -- not
    catching it here would crash the whole pipeline instead of degrading to
    the fallback provider. Errors from the secondary client itself still
    propagate normally.
    """

    def __init__(self, primary, secondary):
        self._primary = primary
        self._secondary = secondary
        self.chat = _FallbackChat(self)

    def _call(self, **kwargs):
        try:
            return self._primary.chat.completions.create(**kwargs)
        except (RateLimitError, AnthropicAPIError):
            return self._secondary.chat.completions.create(**kwargs)


def build_client(
    groq_api_key: str | list[str], anthropic_api_key: str | None = None,
) -> OpenAI | RotatingClient | FallbackClient:
    if isinstance(groq_api_key, list):
        groq_client = RotatingClient(groq_api_key, base_url=GROQ_BASE_URL)
    else:
        groq_client = OpenAI(api_key=groq_api_key, base_url=GROQ_BASE_URL)

    if anthropic_api_key:
        return FallbackClient(AnthropicAdapter(anthropic_api_key), groq_client)
    return groq_client
