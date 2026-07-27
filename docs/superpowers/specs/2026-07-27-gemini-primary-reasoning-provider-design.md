# Gemini as Primary Reasoning Provider Design

## Problem

`backend/app/analysis/claude_client.py`'s `build_client()` chains Anthropic
(primary) → Groq (fallback) for every LLM reasoning call in the analysis
pipeline (`cascade.py`'s multi-stage sector/company reasoning,
`refinement.py`'s summary/why/timeline generation, `relevance.py`'s
`classify_relevance` filter). `ANTHROPIC_API_KEY` is invalid (confirmed
live this session: 401 `authentication_error`), so every call has been
silently falling through to Groq's much weaker fallback path this whole
time. Confirmed hallucinating in production: a Saudi-nuclear-deal story
(no real oil-market mechanism, per its own correctly-extracted facts)
got a fabricated "may increase oil prices, benefiting Reliance" causal
link from a downstream reasoning stage.

The user provided a working `GEMINI_API_KEY` and asked for it to replace
the dead Anthropic slot. Web search grounding was explicitly investigated
and explicitly declined (Google's `google_search` tool returned `429
RESOURCE_EXHAUSTED` on the very first request — needs a billing-enabled
Cloud project, not available on this free-tier key) — **out of scope**.

## Goals

- `build_client()`'s primary slot becomes Gemini instead of Anthropic.
  Groq stays the fallback, unchanged.
- Zero changes to any call site in `cascade.py`/`refinement.py`/
  `relevance.py` — the new adapter duck-types the exact same
  `chat.completions.create(model, max_tokens, tools, tool_choice,
  messages)` → `{choices: [{message: {tool_calls: [...]}}]}` interface
  `AnthropicAdapter` already established.
- Reasoning-only. No web search, no billing changes, no new pip package
  (uses `httpx`, already a dependency).

## Non-goals

- Translation (`app/translation/groq_translator.py`) has its own
  independent `TRANSLATION_PROVIDER`-driven provider selection —
  untouched.
- Web search / grounding — explicitly declined this session.
- Removing `AnthropicAdapter` itself (still used by translation) — only
  `build_client()`'s wiring changes, not the shared adapter classes.
- Re-adding Anthropic as a dormant middle tier in the analysis chain —
  YAGNI; it's dead and staying dead per the user's explicit choice. A
  future working key is a trivial follow-up if it ever happens.

## Design

### `GeminiAdapter` (new, `claude_client.py`)

Mirrors `AnthropicAdapter`'s shape exactly: a `.chat.completions.create()`
method that translates the call into a raw `httpx.post()` to
`https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}`
and translates the response back.

**Request translation:**
- `messages` → Gemini's `contents`/`systemInstruction` split, same as
  `AnthropicAdapter` already does (extract the `system`-role message
  into its own top-level field; everything else becomes
  `{"role": "user", "parts": [{"text": ...}]}` — this codebase's
  reasoning calls are always single-turn, no assistant-role history to
  translate).
- `tools[0]["function"]` (OpenAI shape: `name`, `description`,
  `parameters` as a lowercase-typed JSON Schema) → Gemini's
  `function_declarations` shape. **Schema case translation is required**:
  Gemini's parameter schema requires uppercase type strings (`"OBJECT"`,
  `"STRING"`, `"BOOLEAN"`, `"NUMBER"`, `"INTEGER"`, `"ARRAY"`) — confirmed
  live this session that lowercase (`"object"`, `"string"`, etc., what
  every existing tool builder in this codebase emits) is not just a style
  difference but the actual required format. A small recursive helper
  (`_uppercase_schema_types(schema: dict) -> dict`) walks the schema
  tree and uppercases every `"type"` value, leaving everything else
  (`properties`, `enum`, `required`, `description`) untouched.
- Forced tool-calling: `tool_config: {"function_calling_config": {"mode":
  "ANY"}}` — Gemini's equivalent of Anthropic's
  `tool_choice={"type": "tool", "name": ...}` / OpenAI's
  `tool_choice={"type": "function", "function": {"name": ...}}`. Since
  every call site here only ever declares exactly one tool and forces
  it, `"ANY"` mode with a single declared function is equivalent —  no
  `allowed_function_names` restriction needed.
- `model`/`max_tokens` map directly (`max_tokens` → Gemini's
  `generationConfig.maxOutputTokens`).

**Response translation:**
- Gemini's response: `candidates[0].content.parts[0].functionCall.{name,
  args}`. Critically, `args` arrives as an **already-parsed object**, not
  a JSON string — unlike OpenAI/Anthropic's `arguments` field, which
  every caller in this codebase does `json.loads(...)` on. The adapter
  re-serializes with `json.dumps(function_call["args"])` before
  constructing the fake `tool_call.function.arguments`, so
  `json.loads()` at every existing call site keeps working unchanged —
  same discipline `AnthropicAdapter` already uses for its own
  `tool_use.input` → `json.dumps(...)` step.
- No function call in the response (model declined / safety block) →
  same empty-`tool_calls`-list degradation `AnthropicAdapter` already
  uses, so existing "no tool_use block" `None`-returning callers work
  identically regardless of provider.

**Error handling:** a non-2xx HTTP response raises a new
`GeminiAPIError(Exception)` (defined alongside the adapter). `429` responses
specifically (quota/rate-limit) are the case that must trigger fallback
to Groq — `GeminiAPIError` is added to `FallbackClient._call`'s except
tuple (currently `(RateLimitError, AnthropicAPIError)` →
`(RateLimitError, AnthropicAPIError, GeminiAPIError)`), so ANY Gemini
failure (auth, quota, server error, network) degrades to Groq the same
way an Anthropic failure already does — matching this codebase's
existing "a credit/billing failure is a real, expected production
scenario — not catching it here would crash the whole pipeline instead
of degrading to the fallback provider" reasoning verbatim, just for a
different provider.

### `GEMINI_MODEL` constant

`"gemini-flash-latest"` — an alias Google keeps pointed at their current
recommended flash model (currently resolves to `gemini-3.6-flash`,
confirmed live). Using the alias rather than a dated model string matches
this codebase's own established pattern of models being deprecated over
time (`FALLBACK_MODEL`'s own history: swapped from `llama-3.1-8b-instant`
to `openai/gpt-oss-20b` after the smaller model's tool-schema compliance
became unreliable) — an alias avoids needing another manual swap when
Google's lineup moves again.

Note (informational, not a design decision): this model is a "thinking"
model with real per-call token overhead (confirmed live: 128 thought
tokens for a one-word reply, 166 for a real structured-output call) —
this is Google's cost/latency trade-off for better reasoning, not
something this integration controls. If Gemini's free-tier daily quota
becomes a bottleneck the same way Groq's did earlier this session, the
existing `FallbackClient` degrades to Groq automatically — no code
change needed to handle that case, it already falls out of the fallback
chain design.

### `build_client()` change

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

Same shape as today, `anthropic_api_key` renamed `gemini_api_key` and
`AnthropicAdapter(...)` swapped for `GeminiAdapter(...)`. Every call site
that constructs this client (`app/scheduler.py`'s
`_run_ingestion_and_analysis`, any one-off `reanalyze_*.py` script) passes
`settings.gemini_api_key` instead of `settings.anthropic_api_key`.

### `config.py` change

Add `gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "")` —
`GEMINI_API_KEY` is already set on both Railway (production) and the
local `backend/.env` by the user's own request this session, just not
yet read by `Settings`. `anthropic_api_key` stays defined (still read by
`translation`'s independent provider selection) — not removed.

## Data flow

```
app.scheduler._run_ingestion_and_analysis
  -> build_client(settings.groq_api_keys, settings.gemini_api_key)
    -> FallbackClient(GeminiAdapter(gemini_api_key), groq_client)
       -- every call: try Gemini first (forced tool-calling, uppercase
          schema translation, args re-serialized to a JSON string) --
          on ANY failure (GeminiAPIError, incl. 429 quota) -> Groq
          (RotatingClient across the existing 3 same-org keys, itself
          already MODEL-then-FALLBACK_MODEL depending on call site)
```

## Testing

`backend/tests/test_claude_client.py` (252 lines, existing) already has
the exact convention to mirror: `AnthropicAdapter`'s own test
(`test_anthropic_adapter_translates_request_and_response_to_openai_shape`)
bypasses `__init__` via `AnthropicAdapter.__new__(...)`, injects a fake
`.messages.create` that records `last_kwargs`, and asserts both the
translated request shape and the translated response shape in one test.
`FallbackClient` tests use a `_FailingUnderlyingClient` fake that raises
a given exception, and real `httpx.Request`/`httpx.Response` objects to
construct real typed exceptions (see `_anthropic_rate_limit_error()`,
`_rate_limit_error()`) rather than generic mocks. `build_client` tests
check `isinstance(client._primary, AnthropicAdapter)`.

New/changed tests, same file, same conventions:
- `test_gemini_adapter_translates_request_and_response_to_openai_shape`
  — fake HTTP response shaped like Gemini's real
  `candidates[0].content.parts[0].functionCall.{name,args}`; asserts the
  request sent had `systemInstruction` set, the tool schema's `type`
  values uppercased, `tool_config.function_calling_config.mode == "ANY"`,
  and the response's `tool_call.function.arguments` is a JSON *string*
  that `json.loads()`s back to the original `args` dict.
  `test_gemini_adapter_returns_empty_tool_calls_when_no_function_call`
  (no function call in the response → empty list, matching
  `AnthropicAdapter`'s degradation).
- `test_gemini_adapter_raises_gemini_api_error_on_non_2xx_response`.
- `test_fallback_client_falls_through_to_secondary_on_gemini_api_error`
  — same shape as
  `test_fallback_client_falls_through_to_secondary_on_anthropic_rate_limit`.
- `test_build_client_wraps_in_fallback_when_gemini_key_given` /
  `test_build_client_skips_fallback_wrapper_without_gemini_key` — same
  shape as the existing anthropic-key pair, renamed.
- `backend/tests/test_config.py` (check it exists; if `Settings` has no
  dedicated test file, a one-line assertion is fine folded into whichever
  test file already covers `Settings` field defaults) — confirms
  `gemini_api_key` reads from `GEMINI_API_KEY`.
- A live, manually-run (not part of the automated suite) smoke test
  against the real Gemini API before considering this done — this
  codebase's own established discipline this session was to verify each
  fix against real live data, not just mocks, given how the
  tz-aware-Timestamp and reasoning-model-token-starvation bugs earlier
  this session were both mock-invisible and only surfaced against real
  calls.
