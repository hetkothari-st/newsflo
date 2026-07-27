# Gemini as Primary Reasoning Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dead Anthropic slot in the analysis pipeline's `build_client()` fallback chain with a new `GeminiAdapter`, using a real, live-verified working Gemini API key — Groq stays as the unchanged fallback.

**Architecture:** `GeminiAdapter` duck-types the exact same `.chat.completions.create()` interface `AnthropicAdapter` already established (OpenAI-shape request in, OpenAI-shape response out), so every existing call site in `cascade.py`/`refinement.py`/`relevance.py` needs zero changes. It translates requests to Gemini's native `generateContent` REST shape via `httpx` (already a dependency) and translates responses back, including a required schema-case uppercasing step and a required args-to-JSON-string re-serialization step (both confirmed necessary via live testing this session).

**Tech Stack:** Python, `httpx` (already a dependency — no new package), pytest.

## Global Constraints

- Design doc: `docs/superpowers/specs/2026-07-27-gemini-primary-reasoning-provider-design.md` — read before starting.
- Zero changes to any call site in `cascade.py`, `refinement.py`, or `relevance.py` — they call `client.chat.completions.create(model=..., max_tokens=..., tools=[...], tool_choice=..., messages=[...])` today and must keep working completely unchanged.
- Zero changes to `backend/app/translation/groq_translator.py`'s `build_translation_client`/`build_translation_clients` — independent `TRANSLATION_PROVIDER`-driven provider selection, out of scope.
- `AnthropicAdapter` class and `settings.anthropic_api_key` are NOT removed — both still used by translation.
- Gemini request shape (live-verified this session): POST to `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}`, JSON body `{contents, systemInstruction, tools: [{function_declarations: [...]}], tool_config: {function_calling_config: {mode: "ANY"}}, generationConfig: {maxOutputTokens: ...}}`.
- Gemini response shape (live-verified): `candidates[0].content.parts[0].functionCall.{name, args}` — `args` is already a parsed dict, NOT a JSON string.
- Gemini function-declaration schemas require UPPERCASE JSON-schema type strings (`"OBJECT"`, `"STRING"`, `"BOOLEAN"`, `"NUMBER"`, `"INTEGER"`, `"ARRAY"`) — every existing tool builder in this codebase emits lowercase (`"object"`, `"string"`, etc.) — confirmed live that Gemini requires the uppercase form.
- `GEMINI_MODEL = "gemini-flash-latest"` (an alias, confirmed live to resolve and work).
- Full backend test suite must pass with zero regressions before this plan is done, AND a live (non-automated) smoke test against the real Gemini API must succeed before the final task is considered complete.

---

## File Map

```
backend/app/analysis/claude_client.py   MODIFY — add GeminiAdapter, GeminiAPIError, GEMINI_MODEL; change build_client()
backend/app/config.py                   MODIFY — add gemini_api_key field
backend/tests/test_claude_client.py     MODIFY — new tests mirroring existing AnthropicAdapter/FallbackClient/build_client conventions
backend/app/scheduler.py                MODIFY — build_client() call site: anthropic_api_key -> gemini_api_key
backend/backfill_business_profiles.py   MODIFY — same
backend/backfill_sectors.py              MODIFY — same
backend/backfill_subsectors.py          MODIFY — same
backend/reanalyze_cascade.py            MODIFY — same
backend/reanalyze_recent.py             MODIFY — same
```

---

## Task 1: `gemini_api_key` on `Settings`

**Files:**
- Modify: `backend/app/config.py`

**Interfaces:**
- Produces: `settings.gemini_api_key: str` — read from `GEMINI_API_KEY` env var (already set on Railway production and in local `backend/.env`). Consumed by Task 4 (all `build_client()` call sites).

- [ ] **Step 1: Add the field**

In `backend/app/config.py`, add after the existing `anthropic_api_key` line:

```python
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "")
```

- [ ] **Step 2: Verify it reads the real local value**

Run: `cd backend && python -c "from app.config import settings; print(bool(settings.gemini_api_key))"`
Expected: `True` (the key is already in `backend/.env`).

- [ ] **Step 3: Commit**

```bash
git add backend/app/config.py
git commit -m "feat: add gemini_api_key setting"
```

---

## Task 2: `GeminiAdapter` — request/response translation

**Files:**
- Modify: `backend/app/analysis/claude_client.py`
- Modify: `backend/tests/test_claude_client.py`

**Interfaces:**
- Consumes: `settings.gemini_api_key` (Task 1).
- Produces: `GeminiAdapter(api_key: str, model: str = GEMINI_MODEL)` — a class with `.chat.completions.create(*, max_tokens, tools, messages, **_ignored) -> SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[...]))])`, exactly matching `AnthropicAdapter`'s existing public shape. Also produces `GeminiAPIError(Exception)` and `GEMINI_MODEL = "gemini-flash-latest"`. Consumed by Task 3 (`FallbackClient`/`build_client`).

**Context:** `AnthropicAdapter`/`_AnthropicCompletions` (already in this file, right above where you'll add this) is the pattern to mirror exactly — same constructor shape, same `.chat.completions.create()` signature, same `SimpleNamespace` response-shape construction. The one existing test for it
(`test_anthropic_adapter_translates_request_and_response_to_openai_shape` in
`backend/tests/test_claude_client.py`) bypasses `__init__` via
`AnthropicAdapter.__new__(AnthropicAdapter)` and injects a fake
`.messages.create` — do the same thing here, injecting a fake `httpx.post`
instead of a fake Anthropic SDK call.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_claude_client.py`, after the existing Anthropic
adapter test and its `_translate_via_fake` helper. `httpx` is already
imported at the top of this file (line 4) — do not add another import,
just use it:

```python
def _gemini_response(function_name: str, args: dict) -> httpx.Response:
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent")
    body = {
        "candidates": [{
            "content": {
                "parts": [{"functionCall": {"name": function_name, "args": args}}],
                "role": "model",
            },
            "finishReason": "STOP",
        }],
    }
    return httpx.Response(status_code=200, request=request, json=body)


def _gemini_response_no_function_call() -> httpx.Response:
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent")
    body = {"candidates": [{"content": {"parts": [{"text": "no tool call here"}], "role": "model"}, "finishReason": "STOP"}]}
    return httpx.Response(status_code=200, request=request, json=body)


def test_gemini_adapter_translates_request_and_response_to_openai_shape(monkeypatch):
    from app.analysis.claude_client import GEMINI_MODEL, GeminiAdapter

    tool_input = {
        "category": "oil_energy",
        "companies": [{
            "name": "Reliance Industries", "ticker": "RELIANCE.NS", "is_direct": True, "sector": None,
            "direction": "bullish", "magnitude_low": 2.0, "magnitude_high": 4.0,
            "rationale": "Refiner margins expand.",
        }],
    }
    captured = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _gemini_response("record_analysis", tool_input)

    monkeypatch.setattr("app.analysis.claude_client.httpx.post", fake_post)

    adapter = GeminiAdapter("test-gemini-key")

    from app.analysis.claude_client import SYSTEM_PROMPT

    FAKE_TOOL = {
        "type": "function",
        "function": {
            "name": "record_analysis",
            "description": "test tool",
            "parameters": {
                "type": "object",
                "properties": {"category": {"type": "string"}},
                "required": ["category"],
            },
        },
    }

    result = adapter.chat.completions.create(
        max_tokens=1024,
        tools=[FAKE_TOOL],
        tool_choice={"type": "function", "function": {"name": "record_analysis"}},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Title: test\n\nContent: test"},
        ],
    )

    # Request was translated to Gemini's shape correctly.
    assert f"models/{GEMINI_MODEL}:generateContent" in captured["url"]
    assert "key=test-gemini-key" in captured["url"]
    sent = captured["json"]
    assert sent["systemInstruction"]["parts"][0]["text"] == SYSTEM_PROMPT
    assert sent["contents"] == [{"role": "user", "parts": [{"text": "Title: test\n\nContent: test"}]}]
    sent_schema = sent["tools"][0]["function_declarations"][0]["parameters"]
    assert sent_schema["type"] == "OBJECT"  # uppercased from "object"
    assert sent_schema["properties"]["category"]["type"] == "STRING"  # uppercased from "string"
    assert sent["tool_config"]["function_calling_config"]["mode"] == "ANY"
    assert sent["generationConfig"]["maxOutputTokens"] == 1024

    # Response was translated back to the OpenAI shape analyze_article expects.
    tool_call = result.choices[0].message.tool_calls[0]
    assert tool_call.function.name == "record_analysis"
    assert json.loads(tool_call.function.arguments) == tool_input  # args re-serialized to a JSON string


def test_gemini_adapter_returns_empty_tool_calls_when_no_function_call(monkeypatch):
    from app.analysis.claude_client import GeminiAdapter

    monkeypatch.setattr(
        "app.analysis.claude_client.httpx.post",
        lambda url, *, json, timeout: _gemini_response_no_function_call(),
    )
    adapter = GeminiAdapter("test-gemini-key")

    result = adapter.chat.completions.create(
        max_tokens=1024,
        tools=[{"type": "function", "function": {"name": "record_analysis", "description": "d", "parameters": {"type": "object", "properties": {}, "required": []}}}],
        tool_choice={"type": "function", "function": {"name": "record_analysis"}},
        messages=[{"role": "user", "content": "test"}],
    )

    assert result.choices[0].message.tool_calls == []


def test_gemini_adapter_raises_gemini_api_error_on_non_2xx_response(monkeypatch):
    from app.analysis.claude_client import GeminiAdapter, GeminiAPIError

    def fake_post(url, *, json, timeout):
        request = httpx.Request("POST", url)
        return httpx.Response(status_code=429, request=request, json={"error": {"message": "quota exceeded"}})

    monkeypatch.setattr("app.analysis.claude_client.httpx.post", fake_post)
    adapter = GeminiAdapter("test-gemini-key")

    try:
        adapter.chat.completions.create(
            max_tokens=1024,
            tools=[{"type": "function", "function": {"name": "record_analysis", "description": "d", "parameters": {"type": "object", "properties": {}, "required": []}}}],
            tool_choice={"type": "function", "function": {"name": "record_analysis"}},
            messages=[{"role": "user", "content": "test"}],
        )
        assert False, "Expected GeminiAPIError to be raised"
    except GeminiAPIError:
        pass
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_claude_client.py -k gemini_adapter -v`
Expected: FAIL — `ImportError: cannot import name 'GeminiAdapter'`.

- [ ] **Step 3: Implement `GeminiAdapter`**

In `backend/app/analysis/claude_client.py`, add near the top (after the
existing imports):

```python
import httpx
```

Add after `ANTHROPIC_MODEL = "claude-sonnet-4-5"`:

```python
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
    """Raised on any non-2xx response from the Gemini API -- covers rate
    limits/quota exhaustion (429), auth failures, and server errors alike,
    same "any provider-level failure should degrade to the fallback
    provider" discipline AnthropicAPIError already provides for Anthropic.
    """
```

Add a schema-translation helper and the adapter classes, right before
`class _AnthropicCompletions:` (or right after it — anywhere in the
adapter-classes section of the file is fine):

```python
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
    schemas) -- the only two places a nested schema can appear in this
    codebase's tool definitions -- uppercasing every `type` key found,
    leaving `description`/`enum`/`required` untouched.
    """
    result = dict(schema)
    if "type" in result:
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

    def create(self, *, max_tokens, tools, messages, **_ignored):
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

        body = {
            "contents": contents,
            "tools": [{"function_declarations": [function_declaration]}],
            "tool_config": {"function_calling_config": {"mode": "ANY"}},
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system_content is not None:
            body["systemInstruction"] = {"parts": [{"text": system_content}]}

        url = f"{GEMINI_BASE_URL}/models/{self._model}:generateContent?key={self._api_key}"
        response = httpx.post(url, json=body, timeout=60.0)
        if response.status_code != 200:
            raise GeminiAPIError(f"Gemini API returned {response.status_code}: {response.text}")

        data = response.json()
        candidates = data.get("candidates") or []
        parts = candidates[0]["content"]["parts"] if candidates else []
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_claude_client.py -k gemini_adapter -v`
Expected: all 3 new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/claude_client.py backend/tests/test_claude_client.py
git commit -m "feat: add GeminiAdapter -- Gemini generateContent translated to the OpenAI adapter shape"
```

---

## Task 3: Wire `GeminiAdapter` into `FallbackClient`/`build_client`

**Files:**
- Modify: `backend/app/analysis/claude_client.py`
- Modify: `backend/tests/test_claude_client.py`

**Interfaces:**
- Consumes: `GeminiAdapter`, `GeminiAPIError` (Task 2); `settings.gemini_api_key` (Task 1).
- Produces: `build_client(groq_api_key: str | list[str], gemini_api_key: str | None = None)` — same return shape as today (`OpenAI | RotatingClient | FallbackClient`), with `FallbackClient`'s primary now `GeminiAdapter` instead of `AnthropicAdapter`. Consumed by Task 4 (every call site).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_claude_client.py`:

```python
def _gemini_api_error() -> "GeminiAPIError":
    from app.analysis.claude_client import GeminiAPIError
    return GeminiAPIError("Gemini API returned 429: quota exceeded")


def test_build_client_wraps_in_fallback_when_gemini_key_given():
    from app.analysis.claude_client import GeminiAdapter
    client = build_client("groq-key", "gemini-key")
    assert isinstance(client, FallbackClient)
    assert isinstance(client._primary, GeminiAdapter)


def test_build_client_skips_fallback_wrapper_without_gemini_key():
    client = build_client("groq-key", None)
    assert not isinstance(client, FallbackClient)


def test_fallback_client_falls_through_to_secondary_on_gemini_api_error():
    sentinel = SimpleNamespace(choices=[])
    primary = _FailingUnderlyingClient(_gemini_api_error())
    secondary = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: sentinel)))

    result = FallbackClient(primary, secondary).chat.completions.create(model="m", messages=[])

    assert result is sentinel
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_claude_client.py -k "gemini_key or gemini_api_error" -v`
Expected: `test_build_client_wraps_in_fallback_when_gemini_key_given` and
`test_fallback_client_falls_through_to_secondary_on_gemini_api_error` FAIL
(`build_client` doesn't accept a `gemini_api_key` param yet; `FallbackClient`
doesn't catch `GeminiAPIError` yet). `test_build_client_skips_fallback_wrapper_without_gemini_key`
passes trivially already (no behavior change needed for that one specifically,
but run it anyway to confirm it still does).

- [ ] **Step 3: Wire it in**

In `backend/app/analysis/claude_client.py`, change `FallbackClient`'s
except tuple:

```python
    def _call(self, **kwargs):
        try:
            return self._primary.chat.completions.create(**kwargs)
        except (RateLimitError, AnthropicAPIError, GeminiAPIError):
            return self._secondary.chat.completions.create(**kwargs)
```

And replace `build_client`'s signature and body:

```python
def build_client(
    groq_api_key: str | list[str], gemini_api_key: str | None = None,
) -> OpenAI | RotatingClient | FallbackClient:
    if isinstance(groq_api_key, list):
        groq_client = RotatingClient(groq_api_key, base_url=GROQ_BASE_URL)
    else:
        groq_client = OpenAI(api_key=groq_api_key, base_url=GROQ_BASE_URL)

    if gemini_api_key:
        return FallbackClient(GeminiAdapter(gemini_api_key), groq_client)
    return groq_client
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_claude_client.py -v`
Expected: all tests in this file PASS, including the pre-existing
Anthropic-specific tests (`test_build_client_wraps_in_fallback_when_anthropic_key_given`
etc. — these call `build_client("groq-key", "anthropic-key")` positionally;
confirm they still pass with the renamed second parameter, since
`gemini_api_key` is just a parameter name and any string still wraps in
`FallbackClient(AnthropicAdapter(...), ...)`... wait: re-read this
carefully. `build_client("groq-key", "anthropic-key")` now constructs
`GeminiAdapter("anthropic-key")`, NOT `AnthropicAdapter("anthropic-key")`
-- the existing test `test_build_client_wraps_in_fallback_when_anthropic_key_given`
asserting `isinstance(client._primary, AnthropicAdapter)` will now FAIL,
correctly, since `build_client`'s second argument no longer constructs an
AnthropicAdapter at all. Delete that old test and its "skips fallback"
counterpart (`test_build_client_skips_fallback_wrapper_without_anthropic_key`)
-- they test behavior that no longer exists in this function; the new
`test_build_client_wraps_in_fallback_when_gemini_key_given`/
`test_build_client_skips_fallback_wrapper_without_gemini_key` added in
Step 1 are their direct replacements.

- [ ] **Step 5: Run the full file once more after deleting the obsolete tests**

Run: `cd backend && python -m pytest tests/test_claude_client.py -v`
Expected: all PASS, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add backend/app/analysis/claude_client.py backend/tests/test_claude_client.py
git commit -m "feat: wire GeminiAdapter as build_client's primary provider, Groq stays fallback"
```

---

## Task 4: Update every `build_client()` call site

**Files:**
- Modify: `backend/app/scheduler.py`
- Modify: `backend/backfill_business_profiles.py`
- Modify: `backend/backfill_sectors.py`
- Modify: `backend/backfill_subsectors.py`
- Modify: `backend/reanalyze_cascade.py`
- Modify: `backend/reanalyze_recent.py`

**Interfaces:**
- Consumes: `build_client(groq_api_key, gemini_api_key=None)` (Task 3); `settings.gemini_api_key` (Task 1).

**Context:** All six files currently have the exact same line:
`client = build_client(settings.groq_api_keys, settings.anthropic_api_key or None)`.
This is the ONLY line that needs to change in each file — nothing else
about these scripts changes.

- [ ] **Step 1: Update each call site**

In each of the 6 files below, replace:

```python
    client = build_client(settings.groq_api_keys, settings.anthropic_api_key or None)
```

with:

```python
    client = build_client(settings.groq_api_keys, settings.gemini_api_key or None)
```

Files: `backend/app/scheduler.py`, `backend/backfill_business_profiles.py`,
`backend/backfill_sectors.py`, `backend/backfill_subsectors.py`,
`backend/reanalyze_cascade.py`, `backend/reanalyze_recent.py`.

- [ ] **Step 2: Confirm no call site still references the old pattern**

Run: `cd backend && grep -rn "build_client(settings.groq_api_keys, settings.anthropic_api_key" --include="*.py" .`
Expected: no output (empty — every call site updated).

- [ ] **Step 3: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS, zero failures — confirms none of these
script-level changes broke anything (none of them have direct unit tests
of their own beyond what `test_claude_client.py` already covers for
`build_client` itself).

- [ ] **Step 4: Commit**

```bash
git add backend/app/scheduler.py backend/backfill_business_profiles.py backend/backfill_sectors.py backend/backfill_subsectors.py backend/reanalyze_cascade.py backend/reanalyze_recent.py
git commit -m "feat: point every build_client() call site at gemini_api_key instead of the dead anthropic_api_key"
```

---

## Task 5: Live smoke test (not part of the automated suite)

**Files:** none (verification only — no code changes expected unless the
live test surfaces a real bug, in which case fix it in the file Task 2/3
already touched and note the fix in the commit message).

**Context:** Every fix earlier this session that mattered (the tz-aware
Timestamp bug, the reasoning-model token-starvation bug, the relevance
filter's silent-no-op bug) was invisible to mocked tests and only
surfaced against a real live call. This task is that same discipline
applied to the newly-wired `GeminiAdapter` — confirm the REAL Gemini API,
through the REAL `build_client()`/`FallbackClient` path (not a hand-rolled
script bypassing the adapter), produces a correct structured-output
result end-to-end.

- [ ] **Step 1: Run a live call through the real adapter path**

From `backend/`, run:

```bash
python -c "
from app.config import settings
from app.analysis.claude_client import build_client
from app.filtering.relevance import classify_relevance

client = build_client(settings.groq_api_keys, settings.gemini_api_key or None)

cases = [
    ('RBI hikes repo rate by 25 bps', ''),
    ('Thirty-five killed, 30 injured in Syria bus collision - Reuters', ''),
    (\"How this 70-year-old honey bee farmer is keeping his family farm alive\", ''),
    ('Trump says he wont proceed with nuclear deal unless Saudis join Abraham Accords - Reuters', ''),
]
for title, content in cases:
    print(classify_relevance(client, title, content), '|', title)
"
```

Expected: `RBI hikes repo rate` → `True`; the Syria bus collision and
honey-bee-farmer stories → `False`; the nuclear-deal story's relevance
call may reasonably be `True` or `False` (it does have a stated
geopolitical mechanism, unlike the other two) — the point of including
it here isn't to pin its relevance verdict, it's to visually confirm in
Step 2 that if it DOES proceed past this filter, downstream reasoning no
longer fabricates a Reliance/oil-price link out of nothing.

- [ ] **Step 2: Run a live cascade-shaped call to confirm no fabricated mechanism**

From `backend/`, run:

```bash
python -c "
from app.config import settings
from app.analysis.claude_client import build_client
from app.analysis.cascade import _extract_facts, _identify_sectors

client = build_client(settings.groq_api_keys, settings.gemini_api_key or None)

title = \"Trump says he wont proceed with nuclear deal unless Saudis join Abraham Accords - Reuters\"
content = 'US President Donald Trump has said that he will not move forward with a nuclear deal unless Saudi Arabia joins the Abraham Accords, an agreement aimed at normalizing relations between certain countries in the Middle East.'

facts = _extract_facts(client, title, content)
print('FACTS:', facts.facts[:200])
print('CATEGORY:', facts.category)

primary_sectors = _identify_sectors(client, facts.facts, parent_sectors=None)
if not primary_sectors:
    print('ZERO PRIMARY SECTORS -- correct, honest answer for this story')
else:
    for s in primary_sectors:
        print('SECTOR:', s.sector, s.direction, '-', s.mechanism)
"
```

Expected: the facts extraction correctly identifies this as a US-Saudi
civil-nuclear-cooperation story with no oil-market mechanism (matching
what was already confirmed this session against the same story). Either
zero primary sectors are returned, OR any sector returned has a
`mechanism` that is genuinely traceable to the actual facts (not an
invented oil-price/Reliance link like the pre-fix Groq-only run produced
earlier this session). If a fabricated mechanism appears anyway, this is
a real finding — do not silently accept it; report it and treat it as
this task's discovered issue (the underlying model may still occasionally
reason poorly; that's a quality ceiling, not this integration's bug, but
it must be reported honestly either way).

- [ ] **Step 3: Confirm the call actually went through Gemini, not straight to the Groq fallback**

Add a temporary print inside `_GeminiCompletions.create` (in
`backend/app/analysis/claude_client.py`) — `print("GEMINI CALLED")` right
before the `httpx.post(...)` line — re-run Step 1's command, confirm
"GEMINI CALLED" is printed once per case (4 times total), then remove the
temporary print (do not commit it).

- [ ] **Step 4: Report**

Summarize: the exact output of Steps 1 and 2, confirmation Step 3 showed
Gemini genuinely being called (not silently falling through to Groq on
every call), and the final full-suite test count from Task 4's Step 3.
