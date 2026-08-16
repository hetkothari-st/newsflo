# NEWSFLO V5 — EXECUTION CONTRACT
## The plan that ends the rebuild loop

**Version:** 1.0 · **Status:** FROZEN on signature · **Owner:** Naman Bothra
**Amendment:** only via §7. Verbal changes are not changes.

This document governs *how* NewsFlo V5 gets built. The architecture is in
`NEWSFLO_V5_BUILD_SPEC.md`. The tasks are in `newsflo_v5_tasks/`.
This document exists because the architecture was never the problem.

---

# §1. WHY THE LOOP HAPPENS

The pattern to date:

```
build architecture  →  "this isn't accurate enough"  →  ask an LLM for a better
architecture  →  build it  →  "this isn't accurate enough"  →  repeat
```

Four causes, in order of severity:

**1. The target is unfalsifiable.** "Accurate enough that no expert finds a fault"
cannot be passed or failed. An unfalsifiable target can never be reached, so the
project can never end, so rebuilding always looks reasonable.

**2. There is no measurement.** Three architectures have been built. Not one has a
recorded precision number. Without a baseline, improvement and churn are
indistinguishable, and every version feels equally unproven.

**3. Rebuilding is the pleasant option.** Architecture with Claude Code is fast and
satisfying. Parsing 200 annual reports and labeling 300 events is slow and dull.
The bottleneck has always been data, and every rewrite is a legitimate-looking way
to postpone it. This is the single most important sentence in this document.

**4. Every attempt went broad and shallow.** Fifteen sectors handled mediocrely
never feels finished, so nothing ever ships, so the whole thing looks like a
failure that needs restarting.

**None of these are fixed by a better architecture.** They are fixed by measurement,
scope discipline, and change control. That is what follows.

---

# §2. GATE ZERO — NOTHING PROCEEDS UNTIL THIS IS DONE

**No further architecture work, no Phase 0, no refactoring, until Gate Zero passes.**

### Gate Zero deliverables

1. **40 labeled crude-shock events** (30 real crude events + 10 null events —
   financial news that should produce no company impact).
2. Each labeled by **two independent people**, event-only, without seeing system
   output. Expected PRIMARY set, expected ripple families, expected absent.
3. **The current production system run against all 40**, scored.
4. A one-page baseline recorded in `BASELINE.md`.

### The baseline that must exist before anything else

```
NEWSFLO BASELINE — [date] — commit [sha]
PRIMARY precision            ____%
PRIMARY recall               ____%
Wrong-direction rate         ____%
Ripple family recall         ____%
False PRIMARY on null events ____ of 10
Fabricated numerals found    ____
Internal contradictions      ____
```

**Effort:** roughly 5–8 person-days. **Do it this week.**

Until these numbers exist, every claim about whether the system is good is an
opinion, and every rebuild decision is a coin flip.

---

# §3. THE DEFINITION OF WANT

"What I want" translated into twelve statements that can each be passed or failed.
This replaces the previous goal. **The previous goal is retired and must not be
reintroduced in review conversations.**

| # | Criterion | Measurement | Target |
|---|---|---|---|
| W1 | Every published company has a named mechanism, a magnitude with a band, and a source URL | automated audit over golden set | 100% |
| W2 | No fabricated numerals reach output | firewall + audit | 0 |
| W3 | No company has two contradictory representations | contradiction test | 0 |
| W4 | PRIMARY precision on crude events | golden set | ≥ 95% |
| W5 | Wrong-direction rate on PRIMARY | golden set | ≤ 2% |
| W6 | Ripple family recall on crude | expected-ripple map | ≥ 80% |
| W7 | Ripple precision | golden set | ≥ 80% |
| W8 | False PRIMARY on null events | 10 null events | 0 |
| W9 | Known regulatory modifiers applied where relevant | audit of upstream/OMC cases | 100% |
| W10 | Rejected candidates visible with reasons | review console | present |
| W11 | **External analyst objections that we cannot answer**, per 20 events | §5 expert review | **≤ 2** |
| W12 | p95 publish latency, cached shock template | instrumentation | ≤ 90s |

**W11 is the real goal, made measurable.** Everything else is a proxy for it.

### What "cannot answer" means

An objection is *answered* if we can point to a stored record — a mechanism, a
filing, a modifier, a band, an offset we did consider — that addresses it. An
objection is *unanswerable* if the analyst is right and the system has no reply.
Disagreement about a judgment call where our reasoning is visible and sound is
**not** an unanswerable objection. Two analysts disagree daily; that is not a
defect and must never be scored as one.

---

# §4. CRUDE-COMPLETE — THE ONLY MILESTONE THAT MATTERS

Depth-first. One shock class taken to expert grade before any second class is
touched.

### Scope of Crude-Complete

**In scope:** Brent/WTI price shocks, both directions. All four axes complete for
this class — modelled variable, mechanism edges, tagged companies, tuned gates.
Exposure ledger populated for every company that can plausibly appear. Policy
modifiers for upstream realization and retail fuel. Three horizons. Empirical
transmission. Full evidence chain. Expert-reviewed.

**Out of scope until Crude-Complete passes:** every other shock class. Metals,
FX, rates, policy, agri, earnings, M&A. All of it. They stay on the old code path
or produce nothing.

### Why this is non-negotiable

If the architecture cannot make one shock class unfaultable with full data behind
it, no rewrite will help and you will have learned that for the price of one class
instead of fifteen. If it can, every subsequent class is replication — the same
tags, the same gates, the same review flow, with new data. Replication is boring,
cheap, parallelisable across your team, and does not reopen design debates.

**Ship Crude-Complete to real users before broadening.** A feed that is excellent
on oil stories and silent elsewhere is a credible product. A feed that is mediocre
across fifteen sectors is not.

### Crude-Complete definition of done

All twelve W-criteria pass on the crude golden set, W11 verified by an external
analyst, and the system has run in production for two weeks without a defensibility
incident.

---

# §5. THE EXPERT REVIEW RITUAL

The measurement for W11. Run at the end of each phase from Phase 2 onward.

### Setup

Engage a working sell-side or buy-side analyst covering Indian energy — a
consultant for four hours is sufficient and cheap relative to what it buys. Not
someone on your team. Not someone who has seen the architecture.

### Protocol

1. Give them **20 events** from the golden set with full system output: companies,
   mechanisms, bands, evidence links, applied modifiers, rejected set.
2. They mark every objection with a type from the §6 taxonomy.
3. **You do not defend anything during the session.** Write the objection down.
   Arguing during review destroys the data.
4. Afterwards, classify each objection:
   - `ANSWERABLE` — we have a record that addresses it; the UI failed to surface it
   - `UNANSWERABLE` — they are right, we have no reply
   - `JUDGMENT` — legitimate disagreement, our reasoning is sound and visible
5. **Score = count of `UNANSWERABLE` per 20 events.** Target ≤ 2.
6. Every `UNANSWERABLE` becomes a ticket with a root-cause axis (V/M/C/G/data/UI).

### What this ritual protects against

It is the only mechanism in the entire plan that catches the failure mode where
the system passes all automated tests and is still naive. Automated metrics measure
what you thought to measure. The analyst measures what you didn't.

---

# §6. OBJECTION TAXONOMY

Shared vocabulary for the review ritual and the review console.

```
WRONG_COMPANY        exposure isn't there, or sits in a different entity
WRONG_DIRECTION      sign is backwards
WRONG_MECHANISM      the transmission path described is not how it works
WRONG_MAGNITUDE      the number is off by an order that changes the conclusion
OFFSET_IGNORED       a material counter-channel was not considered
REGIME_IGNORED       a policy/regulatory modifier was missed
ALREADY_PRICED       the event was consensus; there is no surprise
MISSING_COMPANY      an obvious affected name is absent
MISSING_SECTOR       an entire ripple family is absent
FALSE_PRECISION      certainty asserted beyond what the evidence supports
NAIVE                technically defensible but reads as unsophisticated
UNCLEAR              correct but the user cannot tell why it is on screen
```

`NAIVE` is the most valuable label and the one an internal team will never produce.

---

# §7. CHANGE CONTROL — THE ANTI-LOOP MECHANISM

### 7.1 What is frozen

On signature, these are frozen for the duration of Crude-Complete:

- the architecture in `NEWSFLO_V5_BUILD_SPEC.md`
- the twelve W-criteria in §3
- the phase order in `newsflo_v5_tasks/`
- the Crude-Complete scope boundary in §4

### 7.2 The rewrite rule

> **No architectural change may be made without a failing measurement that traces
> to an architectural cause.**

Before proposing any structural change, complete this in writing:

```
PROPOSED CHANGE:      ______________________________________
FAILING METRIC:       ______  current: ____  target: ____
ROOT CAUSE AXIS:      V / M / C / G / data / UI / architecture
EVIDENCE THIS IS ARCHITECTURAL, not a data gap:
                      ______________________________________
WHY A DATA FIX WON'T WORK:
                      ______________________________________
COST OF THE CHANGE:   ____ person-weeks
WHAT IT INVALIDATES:  ______________________________________
```

If `ROOT CAUSE AXIS` is anything other than `architecture`, the change is rejected
and the corresponding data or UI ticket is raised instead. **In this project, the
answer has been "data" every single time so far.** Expect that to continue.

### 7.3 The three-strike rule

If the same W-criterion fails three consecutive measurement cycles *and* the
root-cause analysis says `architecture` all three times, then and only then is an
architectural revision opened. Anything less is churn.

### 7.4 When another LLM offers a better architecture

It will. They always do, because producing a plausible architecture is easy and
producing a *populated* one is hard. The response is fixed:

1. Identify which of the twelve W-criteria the new architecture would improve.
2. If none — decline. It is aesthetics.
3. If some — run it through §7.2. If the root cause is data, the new architecture
   changes nothing, because it would sit on the same empty tables.
4. Log the decision in the ADR (§8) and move on.

**Do not start a fresh chat and ask a fresh model for a fresh architecture. That
is the loop.** The next architecture will look better than this one for exactly the
same reason this one looked better than the last: it hasn't met data yet.

### 7.5 Amendment

Amendments require: the §7.2 form completed, a written decision in the ADR, and a
version bump on this document. Verbal agreement in a meeting is not an amendment.

---

# §8. DECISION LOG

`docs/v5/decisions/ADR-NNN-short-title.md`. One file per decision. Never edited
after acceptance — superseded, with a link forward.

```markdown
# ADR-007: Materiality is computed, not LLM-assigned
Date: 2026-08-20 · Status: ACCEPTED · Supersedes: ADR-003

## Context
V4 asked the model to assign HIGH/MEDIUM/LOW. Measured confidence variance
across 40 golden-set candidates was 0.03 — effectively constant.

## Decision
Materiality is ΔEBITDA computed from ledger exposures with Monte Carlo bands.
LLMs are removed from materiality assignment entirely.

## Consequences
Requires the exposure ledger (blocking). Companies without ledger rows abstain
rather than publish. Expected short-term drop in published company count.

## Alternatives rejected
Prompt-engineering the materiality call — rejected, no ground truth for the model
to anchor on.
```

**The purpose of the ADR log is to stop decisions reopening.** When someone asks in
week 9 why materiality isn't LLM-assigned, the answer is a link, not a debate.

---

# §9. THE PLAN

Assumes a small team: 1 backend engineer with Claude Code, 1 data analyst, 1
domain-literate reviewer (you), plus a contract analyst for reviews.

### Week 1 — Gate Zero
Golden set (40 crude + 10 null), dual-labeled. Current system scored.
`BASELINE.md` written and circulated.
**Exit:** baseline numbers exist. No code has been written.

### Weeks 2–3 — Phase 0, and data work begins in parallel
Engineer: reducer, single writer, claims, entailment firewall.
Analyst: begins ledger extraction for the ~35 crude-exposed companies.
**Exit:** three hard-zero gates pass. Contradictions gone. Fabrication blocked.
**Ship note:** this alone fixes the most visible current defects.

### Weeks 4–7 — Phase 1, ledger for crude
Filing parsers, review workflow, exposure rows for every crude-touching company.
Pass-through curves for the top 15. This is the slowest phase and the one that
determines whether the project works. It is not skippable and it is not
automatable away.
**Exit:** ≥ 90% of the crude company set has filed exposure rows.
**Parallel:** golden set expands to 100 events.

### Weeks 8–9 — Phase 2, sensitivity
ΔEBITDA with bands, driver ranking, sign-consistency rule. LLM materiality removed.
**Exit:** 20 hand-computed examples reproduce. Confidence variance test passes.
**First expert review here** — establishes the W11 baseline.

### Weeks 10–11 — Phase 3, ripple
Tag index, IO bootstrap, coverage harness, ripple gates.
**Exit:** paints and tyres surface. Ripple family recall ≥ 80%.

### Week 12 — Phase 4, policy and horizons
Windfall levy, APM ceiling, fuel price state. Three-horizon output.
**Exit:** upstream-on-crude reflects the levy. OMC MIXED split reproduces.

### Weeks 13–14 — Phase 5, empirical and calibration
Event studies for crude. Calibration if the corpus supports it, disabled if not.
**Exit:** conflict handling live. Divergence queue populated.

### Weeks 15–16 — Phase 6, falsification and console
Adversarial stage, deterministic sections, review console.
**Second expert review.** W11 must be ≤ 2.

### Week 17 — Crude-Complete gate
All twelve W-criteria measured. Ship to real users or fix and re-measure.
**No second shock class before this passes.**

### Weeks 18+ — Replication
One shock class at a time: metals, FX, rates, policy. Each is data work against a
proven architecture. Parallelisable across the team. No design debates.

---

# §10. THE WEEKLY RITUAL

Thirty minutes. Same day each week. Non-negotiable. Same agenda:

1. **The numbers.** Current W-criteria vs baseline vs target. Read them out loud.
2. **Movement.** What moved, what didn't, why.
3. **The one blocker.** Named, owned, with a date.
4. **Data gaps.** Read `DATA_GAPS.md`. Is it shrinking?
5. **Anything that wants to reopen a frozen decision** → route to §7.2 or drop it.

If the numbers didn't move, say so plainly. A week where they didn't move and you
noticed is far better than a week where nobody looked.

---

# §11. THE FIVE THINGS THAT WILL KILL THIS PROJECT

Pinned. Re-read monthly.

1. **Skipping Gate Zero because it's boring.** Then you're back to opinions and the
   loop restarts by week 6. This is the most likely failure and it will feel
   reasonable at the time.
2. **Broadening before Crude-Complete.** Every sector added before crude is proven
   multiplies the cost of every later fix.
3. **Letting Claude Code populate financial tables.** It will produce a
   complete-looking system on invented data, and you will not notice for weeks.
   The Hollow Implementation Check exists for this. Run it. Spot-check five rows
   against a real PDF after every phase.
4. **Treating the analyst review as a threat instead of a measurement.**
   Defending during the session destroys the only real signal you have.
5. **Starting a fresh chat with a fresh model to get a fresh architecture.**
   Every future architecture will look superior to this one until it meets data.
   That asymmetry is permanent, and it is the engine of the loop.

---

# §12. WHAT DONE LOOKS LIKE

Not "no expert can ever find a fault." That was never achievable and pursuing it
literally is what kept the project moving in circles.

Done is:

- A crude story publishes in under 90 seconds.
- Every company on screen carries a mechanism, a band, a filing, and a date.
- The paints and tyres names are there, because a tag index found them.
- The upstream call shows the windfall levy was applied.
- The OMC call shows positive immediate and negative near-term, and explains why.
- Where the system disagrees with history, it says so.
- Fourteen rejected candidates sit one click away with reasons.
- An external analyst reviewing twenty events raises two objections you can't answer,
  and both become tickets.

They will still disagree with some calls. That is the job, and it is not a defect.
They will not be able to say the system is naive, fabricating, or inconsistent.

That is the achievable version of what you asked for, and it is worth more than
the unachievable one — because it can actually be finished.

---

## SIGNATURE

```
Frozen by: ____________________   Date: __________
Baseline recorded in BASELINE.md: __________
Crude-Complete target date:       __________
Next amendment permitted only via §7.
```
