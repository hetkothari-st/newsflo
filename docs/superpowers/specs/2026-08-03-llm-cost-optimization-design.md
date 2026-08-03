# LLM cost optimization — design and operating notes

Cuts what the analysis pipeline spends on LLM calls **without** reducing the
reasoning it does on the work that matters. Every change here either removes
redundant input, caches repeated input, moves latency-tolerant work off the
critical path, or filters obvious junk before it costs a call.

The one class of change that *can* cost quality — running a weaker model on a
call — is built as a routing layer that is **off by default**. Nothing is
downgraded until a human has diffed strong against cheap output on real
articles, and the two calls that decide which companies are affected and why
cannot be downgraded at all.

## What shipped

### 1. Refinement reasons from `facts`, not the raw article

The cascade's stage 1 (`_extract_facts`) already distils each article into a
`facts` string, and every later cascade stage reasons from that string rather
than the article. Refinement did not: `refine_alert` re-sent the full body
(~1500 tokens) on all four of its calls.

It now reasons from the same `facts` the cascade used.

- `AnalysisOutput.facts` carries the distillation out of `analyze_article`.
- `Alert.facts` persists it, so a refinement re-run (or the deferred pass
  below) still has the evidence long after the analysis call.
- `generate_event_summary`, `generate_impact_whys`, `generate_ripple_layers`
  and `generate_timeline_effects` take `facts` instead of `content`.
- An alert with no stored facts — one persisted before this shipped — falls
  back to the article text, exactly as before.

This is also a **consistency improvement**, not only a saving: refinement now
explains the same evidence base the cascade used to pick the companies and
directions it is explaining. Previously the two layers read different text and
could disagree.

Because refinement now depends on `facts` being complete, `_extract_facts` was
widened to capture what refinement needs and previously only the article had:
the entities the article itself names, its figures and dates, and whether the
event is confirmed or a rumor/denial (`generate_event_summary` classifies
`is_unconfirmed`, which the old facts prompt gave it no basis for). The prompt
still forbids *inferring* companies or sectors the article does not name —
that remains a later stage's job.

### 2. Prompt caching on the stable prefix

The system prompt and tool schemas are identical on every call; only the
trailing user message varies.

- **Anthropic**: `cache_control: {"type": "ephemeral"}` on the system block and
  the tool schema. Anthropic's cacheable prefix is ordered tools → system →
  messages, so a breakpoint on each caches as much as is cacheable.
- **Gemini** (the analysis pipeline's primary): caches a repeated prefix
  implicitly, with nothing to mark. Its explicit `cachedContents` API is the
  wrong tool here — it has a minimum-token floor this system prompt is under,
  and charges storage per entry.
- **Groq**: no prompt-cache API. Caching is a no-op, never an error.

Message order was audited at every call site. One was wrong:
`_identify_companies` put ~6k tokens of constant field instructions *after* the
per-article facts, which left almost nothing cacheable. Those instructions now
lead, with a one-line pointer at the end preserving the adjacency-to-the-answer
the old ordering got for free.

Caching changes billing only — the model receives the same tokens either way.

### 3. Conservative pre-filter before the relevance LLM call

`app/filtering/prefilter.py` short-circuits articles that are unambiguously not
market news, before they cost a `classify_relevance` call. It is deliberately
lopsided: a wrongly-admitted article costs one cheap call, a wrongly-rejected
one loses a real story from the feed with nothing to notice it by.

Two mechanisms enforce that:

1. **A veto.** Any market signal anywhere in the article — headline or body —
   admits it, whatever else matched. The signal list is over-broad on purpose.
2. **Headline-only noise matching.** The noise patterns describe article
   *formats* that are never market news (horoscope, recipe, match report), and
   match the headline alone — a body mention proves nothing.

Both must agree before anything is rejected. Anything arguable is absent from
the rules by design: weather (this system has `monsoon_weather` as a
first-class event type), box office (media-company revenue), an executive's
death (moves a stock).

**Defaults to shadow mode**, where it logs what it would have rejected and
changes nothing.

### 4. Per-call model tiering

`resolve_tier(call_name)` maps each logical call to a tier, and the client
adapters resolve a tier to a concrete model per provider (`LLM_TIER_MODELS`).

The layer only ever **downgrades**. A reasoning-tier call is sent exactly as
its call site built it — which matters on the Groq path, where the cascade
already picks `MODEL` vs `FALLBACK_MODEL` per stage for quota reasons that
predate tiering.

- `LLM_PROTECTED_CALLS` (`extract_facts`, `identify_companies`) can never be
  downgraded, whatever the configuration says.
- `LLM_TIERABLE_CALLS` are *eligible*, which is not the same as approved.
- `LLM_CHEAP_TIER_CALLS` is empty by default. A call's name goes in only after
  its strong-vs-cheap diff has been run and reviewed.

### 5. Deferred refinement

Refinement is the only LLM work in this pipeline nothing waits on — an alert is
stored, measured, matched to holdings and broadcast before refinement
contributes anything, and every field it writes is nullable at every read site.

With `REFINEMENT_MODE=deferred`, `_persist_alert` marks the alert
`refinement_status="pending"` and a scheduler pass
(`run_pending_refinements`, every `REFINEMENT_INTERVAL_MINUTES`) fills the
fields in later, in batches, without competing with the cascade for rate-limit
headroom. Per-alert failures are contained and capped at
`MAX_REFINEMENT_ATTEMPTS`.

Defaults to `inline` — the historical behavior.

### 6. Per-call token accounting

`app/analysis/usage_log.py` records call name, provider, model, tier, input and
output tokens, and the cache read/write split for every LLM call. It is wired
into the **adapters**, not the call sites, so every provider path is covered by
construction.

A structured log line is always emitted; `llm_call_usage` rows are written only
when `LLM_USAGE_DB_LOGGING=true`. Recording can never raise.

## Configuration

| Setting | Default | Effect |
| --- | --- | --- |
| `PROMPT_CACHE_ENABLED` | `true` | Mark the stable prefix for the provider's cache |
| `RELEVANCE_PREFILTER_MODE` | `shadow` | `off` / `shadow` / `enforce` |
| `LLM_CHEAP_TIER_CALLS` | *(empty)* | Comma-separated calls to move to the cheap tier |
| `REFINEMENT_MODE` | `inline` | `inline` / `deferred` |
| `REFINEMENT_BATCH_LIMIT` | `20` | Alerts per deferred pass |
| `REFINEMENT_INTERVAL_MINUTES` | `5` | Deferred pass cadence |
| `LLM_USAGE_DB_LOGGING` | `false` | Persist `llm_call_usage` rows |

Model names, tier maps, cache TTL, pre-filter rules and pricing all live in
`app/config.py`.

## Running the gates

`backend/cost_optimization_report.py` is the harness. It reads articles already
in the database and calls the configured provider — it never uses fixtures,
because a gate that passes on synthetic input has answered nothing.

```
python cost_optimization_report.py prefilter-shadow --limit 50   # no API key needed
python cost_optimization_report.py refinement-diff  --limit 10
python cost_optimization_report.py tier-diff        --limit 15
python cost_optimization_report.py cost --limit 30 --articles-per-day 50
```

Each gate prints both versions of the output side by side and states the bar.
The judgement is a human's.

`LLM_MODEL_PRICING_USD_PER_MTOK` ships empty on purpose: provider list prices
change, and a stale hardcoded number would produce a confident, wrong cost
report. The `cost` command always reports real token counts, and reports
dollars only for models priced there.
