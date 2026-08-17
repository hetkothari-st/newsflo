# MEMBERSHIP AS THE PER-COMPANY CLAIM — assessment

**Status:** ASSESSMENT ONLY. Nothing implemented, no schema changed, no row written.
**Tests:** the owner's 2026-08-17 reframing — that with `role` on the graph node, the
per-company question collapses from *exposure* to *industry membership*.

---

## 0. Verdict, plainly

**The reframing is substantially right, and it is the largest single improvement to
this design so far.** Two corrections, one of which changes a number you are working
from and one of which is a hazard you have not weighted.

**Correction 1 — what the probe measured.** You wrote that 17-of-52 is (B)-style
evidence. It is not. The probe never looked for a magnitude; it looked for a
company-named sentence *naming the input*, with no figure on the page — Veedol's
*"it is a purchaser of base oil"*. There are **three** claim types, not two:

| | claim | needs | measured reach on 52 filings |
|---|---|---|---|
| **A** | "this is a paint maker" | industry membership | see §1 |
| **A+** | "its own filing says it buys base oil" | a page number, **no figure** | **17 of 52** |
| **B** | "28% of COGS is crude-derived" | a page number **and** a figure | **9 of 52** |

Your requirement needs **A**. The fallback from A+ to A is therefore a **smaller**
step than you thought — and what A+ buys over A is narrower than I had implied. That
strengthens your case, not weakens it.

**Correction 2 — membership does not work for every exposure family**, and the
split is not the one we have been using. §4.2.

---

## 1. Reach, if membership is the only per-company fact

**Role was what collapsed 4,669 to 89. Role now lives on the node. Membership does
largely survive — the number is ~336 for the crude complex, against 89.**

But it does not survive *uniformly*, and the reason it fails is different from why
role failed. **Role failed because a group was heterogeneous in SIDE. Membership fails
only when an isubgroup maps to MORE THAN ONE NODE** — which is a granularity problem,
not a knowability problem.

### 1.1 Cleanly assignable by `official_isubgroup` alone

| isubgroup | n | → node |
|---|---|---|
| Specialty Chemicals | 110 | `specialty_chemical_makers` (BOTH) |
| Plastic Products - Industrial | 58 | `plastic_converters` |
| Cement & Cement Products | 39 | `energy_intensive_mfg` |
| Other Construction Materials | 22 | `energy_intensive_mfg` |
| Tyres & Rubber Products | 17 | `tyre_makers` (−1: Cochin Malabar, a plantation) |
| Petrochemicals | 14 | `petrochemical_producers` |
| Refineries & Marketing | 13 | `refiners` + `fuel_retailers` |
| Plastic Products - Consumer | 12 | `plastic_converters` |
| Ceramics | 10 | `energy_intensive_mfg` |
| Paints | 9 | `paint_makers` |
| Lubricants | 8 | `lubricant_blenders` |
| Oil Exploration & Production | 7 | `upstream_producers` |
| Road Transport | 7 | `road_freight_operators` |
| Glass - Industrial / Consumer | 5 | `energy_intensive_mfg` |
| Airline | 4 | `airlines` |
| Printing Inks | 1 | `paint_makers` |
| **total** | **336** | **17 nodes** |

### 1.2 Needing a sub-split or per-company assignment

| isubgroup | n | why |
|---|---|---|
| Auto Components & Equipments | 136 | five material bases in one group |
| Civil Construction | 125 | only road builders buy bitumen |
| Packaging | 75 | glass / paper / film are three different nodes |
| Commodity Chemicals | 72 | chlor-alkali, soda ash, fertiliser, phthalics |
| Logistics Solution Provider | 58 | four modes → four different leaves |
| Rubber | 11 | producers, plantation and consumer in one group |
| Road Assets — Toll/Annuity | 7 | operator, not builder |
| **total** | **484** | |

### 1.3 The number

| model | crude-complex reach |
|---|---|
| role on the classification map (measured, §7) | **89** |
| role on the node, exposure claim still required | 213 (103 directional) |
| **role on the node, membership-only** | **336 cleanly + up to 484 with sub-splits** |

**336 against 89 — 3.8×.** And unlike the 213, this number does **not** depend on
acquiring a single filing.

The 484 are not lost, only more expensive: each needs one reviewed sub-split (e.g.
Packaging → film / glass / paper) or a per-company call. That is bounded, one-off work
against a stable taxonomy — not a per-event or per-company cost.

**One caveat carried forward:** 110 of the 336 are Specialty Chemicals, still
MIXED-by-construction. Directional membership-only reach for crude is **226**.

---

## 2. What evidence class a membership claim should carry

### 2.1 It is not a `claim` in the §11.1 sense, and that matters

`claims.CLAIM_TYPES` has nine entries and **none of them fits**. Membership is not
`COST_EXPOSURE` — under node-based modelling the *exposure* assertion lives on the
edge, authored by a human under invariant 13. What is left per company is a
**classification fact**, which is a different epistemic object:

| | an exposure claim | a membership fact |
|---|---|---|
| shape | "X% of base, sourced" | "this company is in this industry" |
| contains a numeral | yes | **no** |
| can be wrong by a factor | yes | **no — it is true or false** |
| falsifiable by | reading a filing page | **inspection, in seconds** |
| decays | yes (freshness windows) | slowly, on corporate action |

**Recommendation: a new claim type `INDUSTRY_MEMBERSHIP`, `fact_class = FACT`, and
it stays out of `EVIDENCE_REQUIRED_TYPES`.** Those four
(`PASS_THROUGH`, `HEDGE`, `COMPETITIVE`, `TIMING`) are the fabrication hot spots
because each is a magnitude-bearing assertion a model can invent plausibly. Membership
is not in that class and forcing it through the same gate would refuse a fact that is
better evidenced than most of what the system already publishes.

### 2.2 Is BSE classification sufficient provenance? Argued against the guard

**The fabrication guard's own text, read literally, is about magnitudes.** Every
prohibition it lists is a number:

> *Never invent pass-through ratios, hedge ratios, input cost shares, segment weights,
> or elasticities … never populate `company_exposure`, `company_modifier`,
> `io_coefficient` or `transmission_empirical` with values you produced from your own
> knowledge.*

A BSE industry classification is **none of those**. It is not a value produced from
anyone's knowledge — it is a stored, dated, externally-published record
(`classification_source = 'BSE'`, `classification_as_of = 2026-08-04`, 4,669 rows).

**Four arguments for sufficiency:**

1. **The ONE RULE is satisfied.** *"Every statement shown to a user must be
   reconstructible from stored structured records with provenance."* A BSE
   classification **is** a stored structured record with provenance. That is more than
   `companies.sector` has (a keyword map, no source) and more than `business_desc` has
   (Wikipedia).
2. **Invariant 2 is untouched.** No numeral.
3. **It is checkable by the reader**, which no parameter in this system is. An analyst
   can falsify "Asian Paints is a paint maker" instantly. They cannot falsify a
   pass-through curve at all. **The claim's auditability is inversely related to its
   fabrication risk, and membership is at the good end.**
4. **Precedent already exists, and it is worse.** `params._sector_of` reads
   `companies.sector` directly — no evidence record, no provenance, a keyword map — and
   uses it to select **sector-median parameters**. Membership-with-BSE-provenance is a
   strict improvement on a path already deployed.

**Two arguments against, both of which survive and constrain the answer:**

1. **BSE classifies the company, not the segment.** A diversified company gets one
   label. Grasim is `Paints`-adjacent, `Cement`, `Textiles` and `Chemicals` at once;
   whatever single isubgroup it carries overstates one and hides three. **This is the
   real limit and it is §5's answer to "where indefensible".**
2. **The precedent above is a warning as well as a licence.** The handover records that
   one curve written against `sector = 'other'` would become the pass-through for
   thousands of unrelated companies. The lesson is not "classification is unusable" —
   it is **"classification must never carry a magnitude"**. Membership carries none,
   so the hazard does not transfer.

**Verdict: sufficient, for a claim that is not about magnitude, at a capped grade.**

### 2.3 Grade and tier ceiling

| evidence for the company's presence | grade | ceiling |
|---|---|---|
| **A+** — the company's own filing names the input | **C** | qualitative tier, top rung |
| **A** — BSE membership of a node an authored edge points at | **D** | qualitative tier, floor. **Never PRIMARY, never SECONDARY_RIPPLE.** |

D is the right cap and it is not arbitrary: `materiality.yaml`'s
`exposure_measurement_grade_cap` already puts `ESTIMATED → D`, and `gates.yaml` gives
`primary: [A,B,C]`. **A membership-only company therefore cannot reach PRIMARY by
construction, through machinery that already exists** — no new rule.

The chain has two links and **the weakest is named honestly**: the edge is authored
(strong, human, invariant 13) and the membership is classified (weaker, external,
dated). `weakest_link` should read `industry_membership:CLASSIFIED`, which is exactly
what that field is for.

---

## 3. Where an LLM legitimately operates

**Your reading is correct on both counts, and it is a narrower and safer envelope
than the system currently permits.** Confirmed:

| # | model task | output space | checkable against |
|---|---|---|---|
| 1 | propose `(company, industry_node)` membership | closed node list × existing companies | node exists; company exists; **BSE isubgroup agrees or the disagreement is surfaced** |
| 2 | propose which authored mechanisms an event triggers | closed `modelled_shock_variables` (15) × {UP, DOWN} | the variable is in the list |

Both are proposal-only, both are reviewable, **neither writes `mechanism_edge`**, and
neither emits a numeral. Task 2 is also the one place a model is genuinely *necessary*:
mapping free-text news onto a closed vocabulary is what a language model is for, and
V4's failure there (45 of 58 mechanism ids resolving to nothing) was caused by the
output space being **open**, not by a model being used.

One addition to your list, because it is already deployed and belongs in the envelope:
**entity resolution from article mentions** (`resolve_mentions`) — but note it is
currently *exact-match only, no fuzzy rung*, which is correct and should stay.

### 3.1 Every point where model output would still be unverifiable

Named exhaustively, because this is the list that decides what needs a human:

| # | judgement | why a closed vocabulary does not verify it | severity |
|---|---|---|---|
| 1 | **The shock's SIGN** | the vocabulary constrains the *variable*, not the direction. "OPEC+ signals output cut" → `BRENT_CRUDE UP` requires inference | **HIGHEST — a wrong sign inverts every company in the feed** |
| 2 | **Whether the event is ABOUT the variable** | an article mentioning crude in passing and an article about crude are lexically similar. No vocabulary distinguishes them | HIGH — produces a whole feed from nothing |
| 3 | **Membership where BSE is silent or wrong** (652 unclassified; the 484 needing sub-splits) | the model falls back on its own knowledge of the company — the exact fabrication surface | HIGH — but bounded, one-off, and reviewable |
| 4 | **Which node a DIVERSIFIED company sits at** | no field resolves it; `company_segment` would, and has 0 rows | HIGH — see §5 |
| 5 | **Event status** (`CONFIRMED` / `OFFICIAL` / `RUMOUR`) | a judgement about a source's authority | MEDIUM — already a gate input |
| 6 | **Magnitude confidence** | already hard-blocked below 0.5 | MEDIUM |
| 7 | **Whether an excerpt supports the claim it is attached to** | containment proves the sentence is in the document, not that it means what the proposal says | MEDIUM — the verbatim gate does not check semantics |

**Points 1 and 2 are not addressed anywhere in this design and they gate everything
downstream.** Both are event-level, both are single judgements per event rather than
per company, and both are cheap to review — one human glance per event. That is the
correct place to spend review budget, and it is a much smaller budget than
per-company review.

**What a model must NOT do, restated:** propose an exposure tag for a company (the
edge owns it), propose a direction (the edge owns it), propose a magnitude (nothing
owns it), or write `mechanism_edge` (invariant 13).

---

## 4. What breaks

### 4.1 The failure is not noise. It is SAMENESS — and your four filters do not touch it

If crude moves, all 9 paint makers publish. **That is not wrong** — every paint maker
*is* exposed to crude derivatives, and the claim is true for each. The problem is that
it is identical for each.

Testing the §F.2 filters against membership-only:

| filter | holds? | but |
|---|---|---|
| (i) distance | **holds fully** — a graph property, evidence-independent | operates **between** nodes |
| (ii) evidence class | **survives as a RANKING key** — A+ above A | orders, does not reduce |
| (iii) leaf specificity | **holds** — publish at the leaf the edge names | operates **between** nodes |
| (iv) role/primacy | **holds** — now on the node | operates **between** nodes |

**Three of four filters discriminate between industries and do nothing within one.**
That is the honest finding. Membership-only gives you: correct set, correct direction,
correct mechanism, correct distance ordering — and **N identical companies inside each
node**.

Which is, precisely, what you asked for and no more. §E already concluded that
companies identical on every rung should be rendered as an unordered alphabetical set
rather than falsely ranked. Membership-only makes that the normal case rather than the
edge case.

**The real constraint is volume.** 17 crude nodes × node size ≈ 336 names.
`discovery.yaml` already says where that lands: *"past a couple of hundred names an
event stops being an analysis and becomes a screen"* (`max_candidates_per_event: 250`).
**336 exceeds the system's own stated limit for what counts as an analysis.**

**The fix is presentational and it follows from the epistemics, not from taste.** Under
membership-only the claim genuinely *is* industry-level — *"crude up hits paint
makers"* — with a member list as its extension. So publish the **section as the unit**,
with its member enumeration behind it, and promote to a named per-company line only
where A+ or a pass-through state differentiates. That is not a compromise; it is the
output shape matching the evidence shape.

### 4.2 The asymmetry you have not weighted — membership does not work for every family

**An industry node determines input-cost exposure. It does not determine
balance-sheet exposure.**

| family | is exposure industry-determined? | membership-only works? |
|---|---|---|
| `input:*` — crude, metals, agri | **yes.** Paint makers buy resins because they are paint makers | **yes** |
| `revenue:*` — realisation, margins | **yes.** Upstream producers realise crude prices | **yes** |
| **`fx:usd_*`** | **NO.** Whether a company imports, exports or holds USD debt is a **balance-sheet** fact, not an industry fact. Two paint makers can differ completely | **no** |
| **`rate:floating_debt_share`** | **NO.** Whether a company carries floating-rate debt is a financing choice | **no** |

This inverts the acquisition finding in `MEASUREMENTS` §9.2. There, the
**cross-cutting** leaves (fx, rate) were the *cheap* ones, because Ind AS 107 puts them
in every filing. Under membership-only they become the **only** ones that still
require a filing — because no classification can answer them.

**Consequence for sequencing, and it reverses §6 of the manifest design:**

* **crude / metals / agri feeds** → membership-only, **no acquisition**, 336 companies
* **USDINR / repo-rate feeds** → still need A+ evidence per company, but that evidence
  is in **every** annual report, so the constraint is corpus size, not hit rate
  (measured: `fx:usd_cost_share` 91% precision, `rate:floating_debt_share` 13 of 18)

Neither is blocked. They are blocked on **different** things, and the plan should stop
treating them as one problem.

---

## 5. Honest cost comparison, and where membership-only becomes indefensible

### 5.1 Cost

| | membership-only (A) | filing-cited (A+) |
|---|---|---|
| reach, crude complex | **336** (226 directional) | 17 of 52 acquired |
| per-company marginal cost | **zero** — already in the DB | one filing acquired, indexed, swept, reviewed |
| one-off cost | ~17 nodes, ~21 edges, ~16 isubgroup mappings, plus sub-splits for 484 | per-sector corpus acquisition |
| evidence grade | D | C |
| decays on | corporate action | filing freshness window (400 days) |
| covers `fx:*` / `rate:*` | **no** | yes |

### 5.2 What an analyst could fault

| fault | A | A+ |
|---|---|---|
| "every paint maker, every crude story — I knew that" | **yes** | partly |
| "which one is hurt most?" | no answer | no answer |
| "this one has repriced / hedged / exited" | **invisible** | visible if the filing says so |
| "this is a conglomerate, paints are 8% of it" | **invisible** | visible via segment note |
| "you missed half the sector" | no — coverage is complete | **yes** — 17 of 52 |

Note the last row: **membership-only is the only one of the two with complete sector
coverage.** A+ publishes whichever members happened to write a usable sentence, which
is an arbitrary subset — and A5.2's coherence rule exists precisely because a
partially-covered section *"reads like a bug"*. **Membership-only fixes the coverage
problem that A+ creates.**

### 5.3 Where exactly it becomes indefensible

Three places, in increasing severity:

1. **Undifferentiated volume.** 336 names on one story is a screen, not an analysis, by
   the system's own definition. **Mitigable** — publish industry-level (§4.1).
2. **Diversified companies.** A single BSE label on a conglomerate asserts an exposure
   for a company whose named business is 8% of it. **Partly mitigable** — exclude
   `Diversified` (13 companies) and any name whose segment note contradicts, once
   `company_segment` has rows. Today it has 0.
3. **A member whose own filing contradicts the industry claim — and we publish it
   anyway.** This is the one that is genuinely indefensible, because it is not merely
   unsized, it is **wrong and checkable**. The corpus already contains the case:

   > **GOODYEAR** — *"The company has limited exposure to foreign exchange risk due to
   > low reliance on imported raw materials and thus the company does not hedge."*

   Under membership-only, Goodyear publishes with the other tyre makers on any crude
   story, and its own annual report says the opposite. **An analyst who checks one
   name and finds that has grounds to disbelieve the whole feed** — and they are right
   to, because nothing in the output distinguishes a member we read from one we did
   not.

### 5.4 The consequence — and it inverts the acquisition argument

Membership-only is not defensible *alone*. It is defensible **as the default, with
filings as the exception handler**:

* **membership publishes the set** — complete coverage, zero marginal cost, grade D;
* **A+ evidence promotes a member** — grade C, named line, its own sentence;
* **`DISCLOSED_IMMATERIAL` removes a member** — with the citation shown;
* **`MITIGATED` / `UNMITIGATED` annotates one** — the within-node discriminator that
  §4.1 showed the four filters cannot supply.

**This inverts what filings are for.** Under the previous design, 50 filings per sector
bought you the *right to publish*. Under this one, they buy you the right to
**correct** — and correction is worth more per filing, because you can spend it where
it changes an answer (Goodyear) instead of spreading it evenly to establish facts a
classification already gives you.

It also means the feed is publishable **now**, at grade D, on data already in the
database, and improves monotonically with every filing acquired. Nothing has to be
finished before anything ships.

---

## 7. CONTRADICTION RATE — measured (supersedes §6's falsifier 2)

Script: `backend/scripts/probes/contradiction_rate.py`
Output: `backend/scripts/probes/_contradiction_2026-08-17.txt`

**Denominator: 33.** Of the 52-report corpus, 33 companies sit at a crude node that
would publish them, 10 are Specialty Chemicals (withheld, MIXED by construction), and
9 sit in isubgroups no crude node claims (Personal Care 4, Diversified FMCG 2,
Packaged Foods 2, Commodity Chemicals 1) — which is itself a small validation: the
roster's `fmcg_distribution` family, which scored 0% on its core leaf in §9.3, is
also the family no node claims.

### 7.1 The headline, and it is not the one I expected

| kind of contradiction | n | rate | does it make the published claim FALSE? |
|---|---|---|---|
| **direction-inverting** — node says consumer, company is a net producer | **0** | **0%** | would be fatal |
| **attenuating** — company is backward-integrated into the input | **6** | **18%** | **no** — it makes the effect smaller, not wrong |
| **disclaiming** — company states the exposure is low or absent | **2** | **6%** | **yes** |
| union, distinct companies | 8 | 24% | |

**Not one of the 33 had its SIGN wrong.** The failure I named as most dangerous in
§4.1 of the design report — publishing a producer under a consumer edge — did not
occur once. `official_isubgroup` membership plus a directional edge got the direction
right **33 of 33**.

**And that is the claim the requirement makes.** The design publishes direction and
refuses magnitude, so the 18% attenuation class does not make a published statement
false — a backward-integrated paint maker still buys resin, just less of it. Under a
design that published magnitude it would be six wrong numbers; under this one it is
six correct directions.

**So the rate that matters — published claims that would be FALSE — is 2 of 33 = 6%.**

By your rule: **low. Membership-only publishes, with the caveat labelled** — and §7.3
specifies the field that labels it.

### 7.2 Every instance

**DISCLAIMING (2) — these are the ones that would publish a false claim:**

* **GOODYEAR** (`tyre_makers`) p100 — *"The company has limited exposure to foreign
  exchange risk due to low reliance on imported raw materials and thus the company
  does not hedge for the foreign currency exposure…"*
* **DELHIVERY** (`logistics_operators`) p67 — *"The Company considers commodity price
  risk and currency risk to be low and does not hedge these risks."*
  Note: Delhivery is asset-light, so this is arguably a **tag** error rather than a
  magnitude disclaim — it belongs at `bought_in_freight`, not `freight_diesel`. Either
  way the node's claim as stated is contradicted by the filing.

**ATTENUATING (6) — backward integration, sign unchanged:**

| company | node | excerpt |
|---|---|---|
| **POLYPLEX** | packaging_film_makers | *"The Company produces its own film grade PET resin."* |
| **UFLEX** | packaging_film_makers | *"our PET resin manufacturing operations, with the upgraded Panipat facility now capable of producing 480 TPD bottle-grade virgin PET chips"* |
| **JINDALPOLY** | packaging_film_makers | *"The company started manufacturing polyester chips for captive use in 1993."* |
| **BERGEPAINT** | paint_makers | *"we enhanced in-house resin manufacturing capabilities through strategic capacity additions"* |
| **ASIANPAINT** | paint_makers | *"Our VAM-VAE … emulsion manufacturing project at Dahej, Gujarat, has also progressed well."* |
| **BALKRISIND** | tyre_makers | *"Our carbon black and specialty materials business is evolving … from a backward integration initiative into a key pillar"* |

Two marginal (MRF — *"Trading in Rubber and Rubber Chemicals"*; SIRCA — *"deepen our
manufacturing integration"*), which would take the attenuating rate to 24%.

**Concentration is the actionable part: `packaging_film_makers` is 3 of 6 — 50%
backward-integrated.** That is a property of the node, not of the companies, and it
argues that node should carry `BOTH` edges like Specialty Chemicals rather than a pure
consumer edge.

### 7.3 Does the output distinguish a member we read from one we didn't?

**No. And the fix is one column.**

`evidence_grade` C vs D distinguishes *filing-cited* from *membership-only*. But D
conflates three different states:

1. no filing on disk — **we never looked**;
2. filing read, silent on this leaf — **we looked and it said nothing**;
3. filing read, disclaims — **we looked and it said no** (should not publish at all).

**That is D11 arriving at member level**: absence of measurement and measured absence
wearing the same label. A reader cannot tell Goodyear (read, contradicted) from a
company whose annual report nobody has downloaded.

**Minimum field — one column, four values:**

```
member_evidence:  NOT_EXAMINED        no filing on disk           -> publish, grade D, caveat shown
                  EXAMINED_SILENT     read; no statement on leaf  -> publish, grade D, NO caveat
                  EXAMINED_CONFIRMS   A+ excerpt found            -> publish, grade C, cite it
                  EXAMINED_CONTRADICTS  disclaimer found          -> DO NOT PUBLISH, cite why
```

`EXAMINED_SILENT` is the load-bearing value and the easiest to leave out. It is
strictly stronger evidence than `NOT_EXAMINED` — we opened the document and the
company did not disclaim — and separating them is exactly what stops the D11
conflation from reappearing here.

This closes §5.3's indefensible case. The claim was never that we had read every
member; it was that the output made no distinction. **With this column the reader can
see which members were read, and the Goodyear case becomes an exclusion with a
citation rather than a silent falsehood.**

### 7.4 Limits of this measurement

* **6% is a FLOOR on disclaimers, not an estimate.** The sweep finds what its patterns
  catch. A disclaimer phrased outside them is invisible.
* **n=2.** Better than n=1 and still small. The rate is stable enough to choose a
  design; it is not stable enough to quote.
* **One methodological finding worth carrying forward: a disclaimer is phrased
  GENERICALLY and an affirmation SPECIFICALLY.** Goodyear says *"imported raw
  materials"*, never "carbon black". The first run anchored both directions on leaf
  terms and found **0 of the 2 real disclaimers**. Any future extractor must anchor
  the two directions differently or it will systematically under-find the only class
  that makes a claim false.
* **`"does not hedge"` is not `"is not exposed"` — they point opposite ways.** JK
  Tyre's *"The Company does not have any exposure hedged through commodity
  derivatives"* surfaced as a disclaimer candidate and is the opposite: an unhedged
  company is **more** exposed. It is an `UNMITIGATED` signal, and it is the same SEBI
  LODR Reg 34(3) sentence shape that produced the CEAT `hedge_ratio = 0.0` FILED rows.
* **A literal `\x08` byte in the pattern silently broke the first repaired run** and
  produced a false negative on Goodyear. Same class as the CEAT glyph split: an
  invisible character defeating a match, failing toward "nothing found". Recorded
  because it is the second time this corpus has produced that failure mode.

---

## 6. What would falsify this

Stated because three architectural arguments have been wrong today, and this is a
fourth architectural argument:

1. **Measure the diversification rate.** Of the 336, how many carry material revenue
   outside their isubgroup? Requires `company_segment`, which has 0 rows. **If it is
   high, §5.3(2) moves from "partly mitigable" to fatal.** Nothing measured.
2. **Measure the contradiction rate.** Of members with a filing on disk, how many
   disclose an exposure materially at odds with their node? One case found (Goodyear)
   from 52 filings, on one leaf. **n=1 is not a rate.** Cheap to measure: the corpus is
   on disk and the sweep exists.
3. **Test whether a reader can tell 336 names from a screen.** No measurement proposed;
   this is a product judgement and it is yours.

**(1) and (2) are the two numbers that decide whether membership-only ships as the
default or as a fallback. Both are measurable from what is already on disk. Neither has
been measured, and I am not going to reason my way to them.**
