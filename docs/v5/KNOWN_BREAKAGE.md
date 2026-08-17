# KNOWN BREAKAGE — tests that fail on master, with nobody assigned

A ticket here means: **this fails today, it is not yours, and a red suite
containing exactly these is still a clean run.** It exists so the next session
does not spend an hour deciding whether it broke something.

**Rules.** Append a section, never rewrite another ticket (protocol §6). A
ticket leaves this file only when the test passes or the test is deleted — not
when someone decides it is unimportant. `Owner: none` is a real state and is
not a placeholder to fill in by guessing; assigning an owner is the repo
owner's act.

**Reporting a suite number that includes these is correct**, provided the
count is stated. Quote it as `N passed / K known-broken`, never as `N passed`.

| # | tests | since | owner |
|---|---|---|---|
| KB-001 | `test_scheduler_universe.py` ×2, supply-links refresh | ≤ 2026-08-17 | **none** — see the 2026-08-17 correction; NOT permanently red |

---

## KB-001 — supply-links refresh tests patch a symbol the code no longer calls

**Status:** OPEN · **Owner: none** · **Not fixed, deliberately.**
**Raised:** 2026-08-17, during the 2a/2b/2c merge sequence.

### The two tests

```
tests/test_scheduler_universe.py::test_supply_links_refresh_isolates_a_poisoned_doc
tests/test_scheduler_universe.py::test_supply_links_refresh_circuit_breaker_stops_after_consecutive_llm_failures
```

### Measured, in four independent trees

| tree | commit | result |
|---|---|---|
| `.worktrees/merge-integration` | `master` @ `eb177f84` + docs only | 2 failed · 3933 passed · 10 skipped |
| `.worktrees/merge-integration` | after 2a | 2 failed · 3961 passed · 10 skipped |
| `.worktrees/merge-integration` | after 2b | 2 failed · 3961 passed · 10 skipped |
| `.worktrees/merge-integration` | after 2c | 2 failed · 3961 passed · 10 skipped |
| `.worktrees/session-a` | `ee302d11`, no branch work at all | 2 failed · 13 passed (file only) |

The `session-a` run is the genericity session's independent check and predates
this ticket. **The same two fail at four different commits including one with
none of the merged work in it, and no third failure ever appears.** They are
not caused by anything merged today.

### Root cause — established, not guessed

Both tests do:

```python
monkeypatch.setattr(scheduler, "build_client", lambda *a, **kw: object())
```

`scheduler._run_supply_links_refresh` (`app/scheduler.py:451`) does **not**
call `scheduler.build_client`. It calls:

```
app/scheduler.py:451              build_extraction_client()
app/companies/supply_links/llm.py:52   -> build_client(settings.groq_api_keys, ...)
app/analysis/claude_client.py:694      -> GroqAdapter(RotatingClient(groq_api_key, ...))
app/analysis/claude_client.py:216      -> ValueError: RotatingClient requires at least one API key
```

The patch lands on `scheduler.build_client`, which nothing reads; the live path
resolves `build_client` through `supply_links.llm`, a **different module-level
binding the monkeypatch never touches**. With no API keys in the test
environment the real constructor raises.

`_run_supply_links_refresh` then catches it and logs, so the failure is silent
at the job level:

```
ERROR app.scheduler:scheduler.py:565 Supply links refresh failed
```

The job returns having done nothing, and the assertion sees an empty list:

```
E   assert 0 == 5
E    +  where 0 = len([])
E    +  and   5 = config.SUPPLY_LLM_FAILURE_BREAKER
```

So **neither test is testing what it names.** The poisoned-doc isolation test
never reaches a poisoned doc, and the circuit-breaker test never reaches the
breaker — both die at client construction, before the behaviour under test
begins. They are currently proving that the job swallows a startup exception.

### Why the seam moved

The indirection through `build_extraction_client` is provider-migration shaped:
the client construction moved behind a helper in `supply_links/llm.py` and the
test's patch target stayed on `scheduler`. A patch of a name that has stopped
being the call site fails **open** — it does not error, it just does not apply
— which is why this reads as a behavioural failure rather than a broken test.

**Not verified**, and deliberately not chased: which commit moved it. Naming a
culprit needs a bisect this ticket did not run, and a wrong attribution is
worse than none.

### What a fix must satisfy — for whoever picks this up

* Patch the binding the call site actually resolves, i.e.
  `app.companies.supply_links.llm.build_client`, or inject the client rather
  than patching a module global. Patching `scheduler.build_client` cannot work
  regardless of what else changes.
* **A test whose subject is the circuit breaker must fail if the breaker never
  runs.** Today, client construction blowing up and the breaker working
  perfectly are indistinguishable at the assertion — both give `calls == []`.
  Assert the breaker's own trace, not just the absence of calls.
* Consider whether `_run_supply_links_refresh` should catch a *construction*
  error at all. Swallowing "no API key configured" as a refresh failure is what
  made this invisible; a config error and a mid-run provider error are not the
  same event and the log cannot currently tell them apart.

### Explicitly NOT done here

No fix, no skip marker, no `xfail`. Marking them `xfail` would be worse than
leaving them red: it would retire two test names that currently assert nothing,
while making the suite green and the loss invisible. They stay red and
documented until someone owns them.

---

## KB-001 — CORRECTION, 2026-08-17: environment-dependent, not permanently red

**The root cause above is right about the mechanism and wrong about the
consequence.** Correcting it in place would hide the error, so it is corrected
here.

### What the earlier entry got wrong

It states, unconditionally, that *"neither test is testing what it names"* and
that *"both die at client construction, before the behaviour under test
begins"*. **That is true only where no API key is configured.** Both tests
pass on `master` in the main tree.

Measured at the same commit (`02a70365`), same suite, 3981 collected in both:

| tree | result |
|---|---|
| main tree (`backend/.env` present) | **3981 passed · 0 failed · 10 skipped** — both orderings |
| `.worktrees/merge-integration` (no `.env`) | **3979 passed · 2 failed · 10 skipped** — both orderings |

`backend/.env` is gitignored, so it **does not follow into a worktree**
(SESSION_PROTOCOL §1). It carries a non-empty `GROQ_API_KEY`.

- **No key:** `build_extraction_client()` → `RotatingClient` raises
  `ValueError("RotatingClient requires at least one API key")` → the job
  catches and logs → the assertions see an empty list → red.
- **Key present:** the client constructs; `extract_profile` is monkeypatched to
  a lambda that ignores it, so **nothing is ever sent to a provider**; the test
  proceeds and genuinely exercises poisoned-doc isolation and the LLM-failure
  circuit breaker → green.

**No API calls are made in either case.** That was checked, not assumed —
`supply_extract.extract_profile` and `supply_loader.apply_extraction` are both
stubbed by the tests.

The unchanged part: the monkeypatch on `scheduler.build_client` **is** aimed at
a symbol `_run_supply_links_refresh` never calls, and therefore never applies.
The live path resolves `build_client` through
`app/companies/supply_links/llm.py`. That is a real defect. It is just not the
defect of "these tests never test anything".

### The six red measurements proved something narrower than claimed

All six came from worktrees. They are six measurements of *the same
unconfigured environment*, not six independent confirmations that the tests are
vacuous. Repetition in one environment is not evidence about another.

### Recommendation: FIX, do not delete

The proposal to delete rests on *"a test that has never exercised its subject
is not coverage being lost."* The principle is right; **the premise does not
hold here.** These tests exercise their subject wherever `.env` exists —
including the tree `master` lives in. Deleting them discards working coverage
of two real behaviours: poisoned-document isolation, and the consecutive-LLM-
failure circuit breaker.

The fix is one line per test — patch the binding the call site actually
resolves:

```python
monkeypatch.setattr(
    "app.companies.supply_links.llm.build_client", lambda *a, **kw: object())
```

That makes them **hermetic**: green in a worktree and in the main tree,
dependent on no ambient key, and no longer silently sensitive to whether a
provider is configured. It also removes the `.env` divergence in
SESSION_PROTOCOL §1 for these two tests.

**Then arm the fix (§7.3):** remove the key from the environment, confirm the
tests still pass, and record that in the commit. A hermeticity fix whose
hermeticity was never observed is the same assumption §7.3 is about.

### The gap to file even if they are fixed

Whichever way this goes, one thing is genuinely untested and should be recorded
rather than assumed:

> **`_run_supply_links_refresh` swallows a client-CONSTRUCTION failure and a
> mid-run provider failure identically.** Both surface as `Supply links refresh
> failed` and an empty result. A missing API key and a provider outage are not
> the same operational event, and nothing distinguishes them in the log or in
> any assertion. That is what let this defect sit unnoticed across six
> measurements — the failure mode was indistinguishable from the success path's
> absence.

That gap is real whether the tests are fixed or deleted, and it is the part
that would actually have caught this.
