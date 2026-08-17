# MEASUREMENTS — 2026-08-17

Three measurements and one reconciliation, run against the live tree and the live
dev DB. **Read-only throughout: no migration, no insert, no suite run.** The only
files created are two probe scripts and their output under `backend/scripts/probes/`
(new, untracked, no collision with Session A) and this document.

> **§1.6's headline is SUPERSEDED by §6.** "50 of 52" counts companies with a
> machine-proposed *candidate*, not a usable one. The number that matters —
> distinct companies with at least one hand-classified USABLE hit at a leaf a crude
> shock reaches — is **17 of 52**. Read §6 before quoting anything from §1.

| § | what | headline |
|---|---|---|
| 1 | Qualitative-tag yield probe over the 52 indexed annual reports | **50 of 52** companies yield a machine-proposed *candidate*, across 19 of 28 leaves. Hand-validated precision on a 64-sentence sample: **38% usable / 27% marginal / 36% false.** **Superseded by §6.** |
| 6 | **Revised reach — every pair classified** | **17 of 52** companies have ≥1 USABLE hit at a crude-reachable leaf (vs sized **9 of 52** = **1.9×**). **34 of 52** at any leaf. Acronym rule removes 11 of 177 pairs. |
| 7 | **Role determinability at isubgroup granularity** | **It collapses.** 4 of 8 tested groups survive → **89 companies**, **1.9% of the 4,669**. No exchange-published field distinguishes producer from consumer. Role belongs on the **graph node**, not on the company. |
| 2 | Qualitative `PASS_THROUGH` sweep | **6 of 52** companies state a recovery mechanism in prose with no number. 3 of the 4 excerpts read are directly usable. |
| 3 | §G.5 mechanism-family closure check | **44 closure failures.** 15/15 shock variables orphaned, 26/28 exposure tags orphaned, 2/2 edges unlabelled, and both live edges hang off an unreachable `from_node`. |
| 4 | Universe reconciliation | **"~3,400" matches no column.** Recommend **India + NORMAL = 2,158** as the publishable denominator: it is 4% of the count you might have used and **98.8% of Indian market cap.** |

---

## 0. Corpus confirmed present

`data/` is gitignored and the ripple-bootstrap handover records that PDFs are
re-fetchable via `acquire.py`. **The corpus is present in this worktree** and no
re-acquisition was needed:

```
data/filings/          53 directories
  source.json          52
  pages.json.gz        52          <- the text layer the probe reads
  *.pdf                53
```

The 53rd directory is `INE482A01020/calls/` (the CEAT Q4 FY26 transcript, recorded in
the econometric handover §4.3). **52 indexed reports, 14,389 pages** — exactly the
denominator the sized bootstrap used, so the two numbers are directly comparable.

**One caveat that bounds every number below.** `roster.py` shows the corpus was
assembled for the *crude* families: paints 6, tyres 7, specialty chemicals 10,
packaging films 8, logistics 7, lubricants 6, FMCG distribution 8. **It is not a
random sample of the listed universe.** Leaves outside the crude complex
(`input:steel_long`, `input:wheat`, the five `revenue:` realisation leaves) score
near zero here because no steel maker, miller or refiner is in the corpus — that is a
property of the sample, not of the method.

Script: `backend/scripts/probes/qualitative_tag_yield.py`
Full output: `backend/scripts/probes/_qualitative_tag_yield_2026-08-17.txt`

---

## 1. Qualitative-tag yield — the §C.2 probe

### 1.1 Method

For each of the 28 `valid_exposure_tag` leaves, hand-authored conservative regexes
over every sentence of every page. A sentence counts as a candidate only when it
**also** carries a first-person/possessive self-reference (`the Company`, `our`,
`we`, `the Group`) and does **not** trip a macro filter (`global`, `world`, `OPEC`,
`Brent`, `the Indian economy`, …). Sentences are bounded at 24–600 chars —
`verbatim.MIN_EXCERPT_CHARS` on the low side.

Two counts per leaf, and the gap between them is the filter doing its work:

* **RAW** — the keyword appears in a sentence anywhere in the report. Includes macro
  commentary. **Not a claim.**
* **HIT** — the same sentence is self-referential and non-macro. **The candidate for
  a `FILED_QUALITATIVE` exposure row.**

### 1.2 Result

```
key                                          RAW   HIT  GATEFAIL
------------------------------------------------------------------------------
fx:usd_cost_share                             14    11         0
fx:usd_debt_share                             30    16         0
fx:usd_revenue_share                          14    10         0
input:aluminium                               17     8         0
input:atf                                      3     1         0
input:base_oil                                 6     5         0
input:bought_in_freight                       33    11         0
input:copper                                   3     1         0
input:crude_derivative_bitumen                 1     1         0
input:crude_derivative_petchem                41    32         0
input:crude_derivative_rubber                 12     6         0
input:crude_direct                             1     0         0
input:freight_diesel                          43    21         0
input:fuel_furnace_pet_coke                   14     7         0
input:intermediated_air_capacity               2     1         0
input:milk                                    20    11         0
input:palm_oil                                 7     4         0
input:steel_flat                               1     0         0
input:steel_long                               0     0         0
input:sugar                                   12     5         0
input:wheat                                    7     0         0
rate:floating_debt_share                      28    19         0
rate:nim_asset_sensitivity                     9     7         0
revenue:crude_realization                      0     0         0
revenue:gas_realization_apm                    0     0         0
revenue:gas_realization_market                 0     0         0
revenue:marketing_margin_retail_fuel           0     0         0
revenue:refining_gross_margin                  0     0         0
------------------------------------------------------------------------------
leaves with >=1 company-named hit             19  of 28
DISTINCT COMPANIES with >=1 hit               50  of 52
```

### 1.3 `GATEFAIL = 0` IS A TAUTOLOGY, NOT A RESULT — read this before quoting it

The probe re-checks every reported sentence through the deployed gate
(`verbatim.contains_verbatim`, both against the whole document and against the cited
page). **It passed 100%, and that proves nothing.** The probe *extracts* sentences
from the page text and whitespace-normalises them the same way
`documents.normalize_whitespace` does, so containment is true by construction.

The CEAT `"T he Company does not have any exposure hedged…"` glyph split defeated the
gate because a **human retyped** the sentence with the artefact removed. A machine
lifting the string verbatim cannot reproduce that failure. **The gate has not been
exercised by this probe and must not be reported as having validated anything.** It
will do real work at the point a reviewer edits a proposed excerpt, and that is
where it should be measured.

### 1.4 Hand-validated precision — 64 sentences read

The probe printed up to 4 excerpts per leaf (first 4 distinct companies in ISIN
order). **All 64 were read and classified by hand.** This is the number that matters,
and it discounts the headline substantially.

| verdict | n | % | meaning |
|---|---|---|---|
| **USABLE** | 24 | **38%** | a reviewer would approve this excerpt as-is |
| **MARGINAL** | 17 | **27%** | evidences the exposure but needs the surrounding note read |
| **FALSE** | 23 | **36%** | not a claim about this company's exposure |

Sample of the strongest — these are complete, citable qualitative exposure claims:

* `input:base_oil` · **VEEDOL** p120 — *"The Company's exposure to market risk with
  respect to commodity prices primarily arises from the fact that it is a purchaser
  of base oil."*
* `input:crude_derivative_rubber` · **JKTYRE** p169 — *"Its operating activities
  require the purchase of raw material and manufacturing of tyres and therefore
  require a continuous supply of certain raw materials such as natural rubber,
  synthetic rubber, carbon black, fabric, crude oil, bead wire rubber chemicals etc."*
* `input:base_oil` · **GULFOILLUB** p151 — *"The Company being a sizable user of
  imported Base oil…"*
* `input:aluminium` · **PIDILITIND** p253 — *"Certain key raw materials and packing
  materials used by the Company are derivatives of commodities such as crude oil,
  paper, aluminium, etc."*
* `input:fuel_furnace_pet_coke` · **DEEPAKNTR** p160 — *"the Company continues to
  rely partly on conventional fuels such as coal and furnace oil, which exposes it to
  energy cost volatility…"*
* `fx:usd_revenue_share` · **BRITANNIA** p123 — *"The Company has export sales (2% to
  3% of total sales) primarily denominated in US dollars and Euro."* — note this one
  even carries the share.
* `input:intermediated_air_capacity` · **BLUEDART** p328 — *"'Express Air Charter
  Services' income is generated from the charter flight services rendered exclusively
  to the Company."*

### 1.5 Five systematic failure modes — the reusable finding

These are more valuable than the counts, because they are what any future extractor
must handle and three of them are **not** fixable by tuning patterns.

**(1) Acronym collisions. Fixable, and severe.**
* `ATF` matched **APOLLOTYRE**'s CSR foundation — *"The Company through ATF promotes
  inclusive programme delivery…"*. 1 of 1 hits false.
* `SMP` matched **Senior Management Personnel** (ASIANPAINT, JUBLINGREA) instead of
  Skimmed Milk Powder.
* `milk` matched **DELHIVERY**'s *"legacy milk-run model"* — a logistics term.
* **Rule: no 2–4 letter uppercase abbreviation may be a standalone pattern.** The
  vocabulary is full of them (`ATF`, `SMP`, `CGD`, `ECB`, `GRM`, `NIM`, `CPO`,
  `HSD`, `MEG`, `PTA`).

**(2) PRODUCER/BUYER INVERSION. Not fixable by pattern tuning. This is the dangerous one.**
* **UFLEX** — *"Every day, we convert 6 tonnes of waste into liquid fuel, hydrocarbon
  gas, and carbon black."* UFLEX **produces** carbon black.
* **JUBLCPL** — *"engaged in the business of manufacturing of Performance Polymers &
  Chemicals."* JUBLCPL **produces** polymers.

The sentence correctly names the input. The `mechanism_edge` supplies the direction
and assumes a **buyer**. **The published direction would be exactly backwards** — the
single worst outcome available to a system whose only claim is direction. No regex
distinguishes "we buy X" from "we make X" reliably, and a self-reference filter makes
it *worse*, because a producer describes its own products in the first person.

**This is the concrete argument for §F.2(iv), the `primacy` test.** The
`official_isubgroup → tag` mapping must carry a **sign**, not merely a primacy flag:
`Commodity Chemicals` producing polymers and `Paints` consuming them are opposite
sides of the same tag. **Recommend upgrading the §F.2(iv) proposal from
`primacy: PRIMARY|INCIDENTAL` to `role: CONSUMER|PRODUCER|BOTH|INCIDENTAL`** before
any mapping is authored.

**(3) ESG/sustainability framing. Partly fixable, needs a decision.**
Most `input:fuel_furnace_pet_coke` and `input:palm_oil` hits are *"we are reducing
our use of X"* (GODREJCP, BRITANNIA, PIDILITIND, COLPAL, HINDUNILVR). The exposure is
evidenced — you cannot reduce what you do not consume — but the sentence is about a
transition, not a current cost structure. **Honest, and it is the majority of the
MARGINAL bucket.** A reviewer must decide whether a reduction commitment is
sufficient evidence of present exposure. It probably is; it should be a stated rule
rather than a per-reviewer judgement.

**(4) Wrong-scope sentences. Partly fixable.**
The self-reference filter admits sentences that are about someone else's economics:
**DELHIVERY** *"Our early customers have already realised up to a 12% reduction in
freight costs"* (the customers' costs), **COLPAL** *"Sugar Acid Shield"* (a product
name), **DEEPAKNTR** *"Dhampur Sugar Mills Limited"* (a directorship disclosure),
**INDIGOPNTS** *"The Executive Director is entitled to claim the fuel expenses"*
(a remuneration note).

**(5) Tag-precision mismatch. Not a probe bug — a vocabulary finding.**
**ASIANPAINT** p213 — *"Cross Currency Interest Rate Swap… related to its JPY
denominated external commercial borrowing"* — matched `fx:usd_debt_share`. The
disclosure is **JPY**; the leaf says **USD**. Either the vocabulary needs a
currency-general FX-debt leaf, or the extractor must refuse a non-USD disclosure on a
USD leaf. **Worth an owner decision before any FX tagging starts.**

Separately, `rate:nim_asset_sensitivity` scored **7 hits, all false** — every one is a
non-financial company's Ind AS 107 interest-rate sensitivity note, not a bank's NIM.
The leaf's comment says *"-> banks"* and the corpus contains no bank. Pattern error
on my side, reported for completeness.

### 1.6 The comparison you asked for — stated honestly

| | sized route | qualitative route |
|---|---|---|
| corpus | 52 annual reports | the same 52 |
| yield | **9 companies** with a usable `share_of_base` (7 logistics) | **50 companies** with ≥1 machine-proposed company-named sentence |
| outside logistics | **2 of 45** | not separately measured |
| leaves covered | 7 families, 6 of them thin (<3 companies) | **19 of 28 leaves** |
| after human review | 9 (the number already *is* post-review) | **not measured — 38% of a 64-sentence sample was directly usable, 27% needed a read** |
| reviewer's task | find a ratio that mostly is not disclosed | read ~5 candidate sentences and approve or reject |
| binding constraint | **Schedule III removed the class-wise breakup** | **acquisition — 52 reports is the whole corpus** |

**The honest one-line statement:** the qualitative route changes the reviewer's job
from *searching for a disclosure that usually does not exist* to *reading a handful of
candidate sentences that usually do*, and it raises per-corpus coverage from 9
companies to a candidate set covering 50 — **but roughly a third of those candidates
are wrong, and one class of error (producer/buyer inversion) would publish a
backwards direction rather than a weak one.**

**Not extrapolated to 3,400, deliberately.** The corpus is 52 crude-family reports.
Nothing here supports a claim about companies whose filings are not on disk.

---

## 2. Qualitative `PASS_THROUGH` sweep

Same method, four hand-authored pattern families for a **recovery mechanism stated in
prose with no number** — the §F.3.2 claim that separates two companies inside one
section.

```
key                                          RAW   HIT  GATEFAIL
------------------------------------------------------------------------------
FUEL_SURCHARGE                                 3     1         0
PRICE_ADJUSTMENT_CLAUSE                       13     3         0
REGULATED_TARIFF_PASS                          0     0         0
RM_ESCALATION                                 14     3         0
------------------------------------------------------------------------------
DISTINCT COMPANIES with >=1 hit                6  of 52
companies with BOTH an exposure hit and a pass-through hit:  6
```

**All 6 pass-through companies also have an exposure hit.** The claim composes: every
company for which a mitigation was found is a company the exposure sweep had already
found. That is the property §F.3.2 needs.

The excerpts, all four read:

* **TCIEXP** p86 — *"This risk is mitigated through a dynamic fuel surcharge
  mechanism, periodic freight rate revisions, and contractual arrangements that
  enable partial pass-through of cost fluctuations…"* — **USABLE. Exactly the
  §F.3.2 claim, and it is the second-best filing-sourced pass-through lead in the
  corpus after Blue Dart's.**
* **GANDHAR** p86 — *"To manage input-cost fluctuations, the Company enacts
  price-pass-through clauses in certain customer contracts."* — **USABLE.**
* **UFLEX** p116 — *"The pricing policy of the Company['s] final product is
  structured in such a way that any change in price of raw materials is passed on to
  the customers in the final product however, with a time lag which mitigates the raw
  material price risk."* — **USABLE, and it states a lag qualitatively** ("with a
  time lag"), which is the shape §F.3.2 predicted.
* **POLYPLEX** p97 — *"any adverse fluctuations in the cost of PET resin can impact
  the Company's operating margins depending upon the Company's ability to pass on
  cost increases to its customers."* — **MARGINAL, and instructive: it is a risk
  statement, i.e. an admission that pass-through may FAIL.** Read as a mitigation it
  says the opposite of what it means.
* **APOLLOTYRE** p58 — *"The Company's profitability remains sensitive to volatility
  in raw material prices, particularly in scenarios of sharp cost escalation."* —
  **this is a NEGATIVE pass-through statement**, and it is at least as useful as a
  positive one. My key mislabelled it as `RM_ESCALATION`.
* **JSWDULUX** p72 — *"The Company provides research and development services under
  cost plus agreed mark-up basis."* — **FALSE** (a revenue-recognition note about a
  service line).

**The finding that changes the design:** a qualitative pass-through claim has
**three** states, not two — `MITIGATED` (a mechanism exists), `UNMITIGATED` (the
company says it is exposed to input prices with no recovery named), and absent
(nobody said). POLYPLEX and APOLLOTYRE are the second kind, and the second kind is
**more** decision-relevant than the first, because it is the company telling its
shareholders it cannot reprice. **A design that only looks for mitigation finds the
less useful half.**

6 of 52 is a floor, not a ceiling: the four pattern families were written in one pass
and `REGULATED_TARIFF_PASS` found nothing at all, which for a corpus with no utility
or regulated-tariff name is the expected result.

---

## 3. §G.5 mechanism-family closure check

Script: `backend/scripts/probes/mechanism_family_closure.py` (read-only, `mode=ro`).
Four assertions — A1/A3/A4 are §G.5's three, A2 is the reverse of A1 that caught the
live defect in §A.2 of the design report.

```
live config : 15 modelled shock variables, 28 valid exposure tags, 43 section labels
live db     : 2 mechanism_edge rows (0 rejected, 2 unreviewed)

[A1] modelled shock variables with NO mechanism_edge:  15 / 15
       BRENT_CRUDE  NATURAL_GAS  USDINR  REPO_RATE  GSEC_10Y  STEEL_FLAT
       STEEL_LONG  ALUMINIUM  COPPER  PALM_OIL  WHEAT  SUGAR  MILK
       PET_COKE  FREIGHT_RATE

[A2] mechanism_edge from_nodes that are NOT modelled variables: 1
       UNREACHABLE FROM_NODE  commodity:crude_oil
         edges = ['ca78e5c5-049c-4731-931d-b9ab1bedebf9',
                  'ed030571-b85f-4a9a-92b5-f277a7f18585']

[A3] valid exposure tags NO mechanism edge reaches:  26 / 28

[A4] mechanism edges with NO section label (post-normalize):  2 / 2
       ca78e5c5-…  would render: UNCLASSIFIED MECHANISM (ca78e5c5_049c_4731_931d_b9ab1bedebf9)
       ed030571-…  would render: UNCLASSIFIED MECHANISM (ed030571_b85f_4a9a_92b5_f277a7f18585)

[ref] V4 knowledge.MECHANISMS without a label post-normalize:  0 / 42

======================================================================
TOTAL CLOSURE FAILURES: 44
======================================================================
```

### 3.1 The backlog, read off the failures

**A1 — 15 of 15 shock variables are orphans.** `config/discovery.yaml` declares
fifteen variables this system "claims to model". **Not one has a mechanism edge.**
Every event, on every variable, produces **zero** MECHANISM candidates today. The
`MECHANISM` source — the entire recall fix that `discovery/engine.py`'s docstring
describes as the reason the module was rewritten — is inert.

**A2 — both live edges are unreachable.** Confirms §A.2 of the design report exactly.
The two CEAT edges hang off `commodity:crude_oil`; the modelled variable is
`BRENT_CRUDE`. `authored_edges.blockers()` refuses precisely this
(*"discovery would report it unmodelled and never walk this edge"*) — the rows were
hand-`INSERT`ed around the loader. **The guard was correct and was bypassed, and
nothing detected it until this script.**

**A3 — 26 of 28 exposure tags are orphans.** Only `input:crude_derivative_rubber` and
`input:crude_derivative_petchem` are reachable — and per A2, not actually, because
their edges hang off an unreachable node. **The true reachable-tag count is 0.** The
eleven `company_exposure` rows sit on five tags, and discovery can surface **none** of
them.

**A4 — both edges are unlabelled, and worse than D6 recorded.**
`normalize_node_id` converts the UUID's hyphens to underscores, so the section header
would read `UNCLASSIFIED MECHANISM (ca78e5c5_049c_4731_931d_b9ab1bedebf9)` — **a
mangled UUID that cannot be pasted back into the database to find the row it names.**
DEFECTS-001 D6 records the hyphenated form; the persisted dialect makes it worse.

**The `[ref]` line is the sharpest statement in this document.**
`config/section_taxonomy.yaml` has **43 labels covering 42 of 42 V4
`knowledge.MECHANISMS` keys — 100%** — and **0 of the 2 V5 `mechanism_edge` rows.**
The taxonomy is complete for the vocabulary V5 is replacing and empty for the
vocabulary V5 uses. That is the four-layer gap in one number.

### 3.2 Why this is the first honest coverage number

Every one of these 44 is individually a valid row or a valid config line. Each layer
passes its own review. **The combination has never been checked, because no reviewer
ever sees all four layers at once** — which is §G.4's argument, now measured rather
than asserted.

The script is deliberately **not yet a test**: as a test it would fail the suite on
day one, and 44 failures in CI is noise, not signal. **Recommend it becomes a test at
the moment the first family manifest lands**, with the current 44 recorded as the
baseline it must monotonically reduce.

---

## 4. Universe reconciliation

Read-only over `companies` (5,321 rows: **4,814 INDIA / 507 GLOBAL**).

### 4.1 The candidate denominators, with market cap

| cut | n | % of India market cap |
|---|---|---|
| INDIA, all | 4,814 | 100.0% |
| INDIA, not SUSPENDED | 4,767 | 100.0% |
| INDIA, NORMAL + RESTRICTED | 4,258 | 99.8% |
| **INDIA, NORMAL + SME** *(your lean)* | **2,667** | **99.0%** |
| **INDIA, NORMAL** *(recommended)* | **2,158** | **98.8%** |
| INDIA, NORMAL, with `official_isubgroup` | 2,058 | 98.8% |

Tradeability × classification, INDIA only:

```
NORMAL      2,158   (2,058 with isubgroup)
RESTRICTED  2,100   (2,056 with isubgroup)
SME           509   (  509 with isubgroup)
SUSPENDED      47   (   46 with isubgroup)
```

`tradeability` is derived by `universe/sector_map.derive_tradeability`: NSE series
outside the normal set → `RESTRICTED`; BSE surveillance/T-group → `RESTRICTED`;
BSE SME boards → `SME`; **most-permissive listing wins**, so a name that is NORMAL on
NSE and T-group on BSE is `NORMAL`. These are real listed companies, not delistings.

### 4.2 "~3,400" matches nothing

No column, no combination, and no filter in this table yields ~3,400. The nearest
cuts are 4,258 (NORMAL+RESTRICTED) and 2,667 (NORMAL+SME). It may be a stale count, a
different source, or the ~3,400 of the 4,814 that carried a market cap at some earlier
snapshot. **Recommend retiring the figure** rather than reverse-engineering it — a
denominator nobody can derive will silently disagree with every metric built on it.

### 4.3 Recommendation: **India + NORMAL = 2,158**, and I argue against 2,667

**For NORMAL:**

1. **The market-cap argument settles it.** 2,158 companies carry **98.8%** of Indian
   market capitalisation. The 2,656 companies excluded carry **1.2% between them**.
   Every name a reader could plausibly act on is inside the cut.
2. **SME buys almost nothing.** Adding SME grows the denominator **24%** (2,158 →
   2,667) for **0.2%** of market cap. That is a denominator that makes coverage look
   worse while adding nothing publishable — and coverage numbers exist to direct
   effort. A metric that sends you to source 509 SME-board filings for 0.2% of the
   market is a metric working against you.
3. **The gate already agrees, it just is not wired.** `gates.yaml` carries
   `min_adv_inr: null` with the comment *"no liquidity feed wired yet"*. The moment a
   liquidity feed exists, the SME and RESTRICTED populations fall out at the gate
   anyway. Choosing NORMAL now makes the denominator agree with where the gate is
   going instead of contradicting it later.
4. **RESTRICTED is a surveillance status, not an economic one — and that is the
   argument for excluding it, not against.** A T-group/trade-to-trade name cannot be
   taken as a normal position. Publishing it as "affected" is a claim a reader cannot
   use. 2,100 companies, 1.0% of market cap.

**Against — stated, because it is a real cost:**

* Excluding RESTRICTED removes 2,100 genuinely listed companies that file genuine
  annual reports. If the product's promise is *breadth of the listed universe*, that
  is a 49% cut of the count. **This is a product decision, not a data one**, and if
  the promise is breadth then `not SUSPENDED` (4,767) is the honest denominator and
  coverage will simply read low for a long time.
* `market='GLOBAL'` rows are `NORMAL` **by default, not by evidence** —
  `derive_tradeability` returns `NORMAL` for a company with no listings, and all 507
  GLOBAL rows have none. Scoping to `market='INDIA'` is therefore load-bearing, not
  cosmetic: without it, `tradeability='NORMAL'` silently includes 507 companies whose
  status was never measured.

### 4.4 Report two denominators, and weight the primary one

They answer different questions and conflating them is how the "~3,400" happened:

| metric | denominator | n | answers |
|---|---|---|---|
| **Publishable coverage** *(primary)* | `market='INDIA' AND tradeability='NORMAL'` | **2,158** | of what we would ever show a reader, how much can we say something about? |
| **Analysable backlog** *(secondary)* | `market='INDIA' AND tradeability<>'SUSPENDED'` | **4,767** | how much of the listed universe could ever be tagged? |

And **market-cap-weighted coverage should be the headline, not count coverage** —
`exposure_coverage` (migration 0012) already computes
`tagged_market_cap / sector_market_cap` per (sector, tag). Count coverage over 2,158
will read in the low single digits for a long time and will not distinguish tagging
Reliance from tagging a micro-cap. **One caveat before that view is used:** it groups
by `companies.sector`, which is `'other'` for 3,161 rows — so it currently reports one
enormous meaningless bucket. Re-keying it on `official_isubgroup` is the same
one-line change §D.3 of the design report recommends for `_industry_of`, and it does
not touch `companies.sector`.

---

## 6. REVISED REACH — every (company, leaf) pair classified (supersedes §1.6)

Script: `backend/scripts/probes/qualitative_tag_yield_v2.py`.
Output: `_v2_clean.tsv` (acronym rule applied), `_v2_acronyms.tsv` (with them).

### 6.1 Three method changes from v1

1. **The acronym rule, applied retroactively.** Every bare 2–4 letter uppercase
   alternative moved to `BARE_ACRONYMS` and switched off: `ATF`, `SMP`, `CPO`, `HSD`,
   `LDO`, `PTA`, `MEG`, `BOPP`, `BOPET`, `SBR`, `PBR`, `TMT`, `GRM`, `CGD`, `ECB`,
   `MCLR`, `NIM`, `HR coil`, `CR coil`.
2. **One row per (company, leaf) pair**, not 4 per leaf — the reach question needs
   the whole population, not a sample.
3. **A claim-strength scorer replaced "longest sentence wins".** v2's first run
   ranked by length and surfaced boilerplate tables over the crisp disclosures v1
   had found by accident — GULFOILLUB's base-oil pair became an interest-rate
   table. **Length is not evidence.** The scorer ranks on procurement/cost-risk
   verbs, penalises boilerplate markers and digit-dense table rows. It **ranks**
   for a reviewer; it does not classify, and it never decides whether a row may be
   written.

### 6.2 The acronym-rule delta

| | pairs | companies ≥1 hit | companies ≥1 crude-reachable hit |
|---|---|---|---|
| with bare acronyms | 177 | 50 | 45 |
| **acronym rule applied** | **166** | **49** | **44** |
| removed | **−11 (6.2%)** | −1 | −1 |

**Small at the pair level, and that understates it.** The 11 removed pairs sat on
the leaves with the worst precision in v1 — `input:atf` was 1 hit and 1 false
(a CSR foundation), `input:milk`'s `SMP` was matching Senior Management Personnel.
The rule removes 6% of the volume and a much larger share of the *errors*.

### 6.3 The numbers you asked for

**All 166 pairs hand-classified** (USABLE = a reviewer would approve the excerpt
as a `FILED_QUALITATIVE` exposure row as it stands).

| | pairs | USABLE pairs | **distinct companies with ≥1 USABLE** |
|---|---|---|---|
| crude-reachable leaves | 84 | 19 | **17 of 52** |
| all other leaves | 82 | 37 | 26 of 52 |
| **union** | **166** | **56 (34%)** | **34 of 52** |

**The FILED_QUALITATIVE crude reach is 17 of 52.** Against the sized route's
**9 of 52**, that is **1.9× — not the 5.5× the "50 of 52" headline implied.**

34% usable at pair level corroborates the 38% from v1's 64-sentence sample, so that
sample was representative.

### 6.4 Per-leaf, crude-reachable

| leaf | pairs | USABLE | note |
|---|---|---|---|
| `input:base_oil` | 5 | **5** | **100%.** Castrol, Gandhar, Gulf Oil, Panama Petro, Veedol — all state base-oil purchase in a commodity-price-risk note. |
| `input:crude_derivative_rubber` | 6 | **3** | CEAT (note 45(iv) itself), JK Tyre, MRF. 1 producer-inversion (UFLEX), 1 backward-integrated (Balkrishna). |
| `input:bought_in_freight` | 11 | 3 | CONCOR (rail/road freight expense lines), Vinati, **VRL — *"Lorry hire charges reduced as a percent to revenue from 5.54% to 4.80%"*, which carries its own share.** |
| `input:fuel_furnace_pet_coke` | 7 | 2 | Deepak Nitrite, Kansai Nerolac. 5 marginal, all "we are reducing furnace oil". |
| `input:crude_derivative_petchem` | **32** | **4** | **The worst leaf.** Colpal, Dabur, Kansai, Polyplex usable; **9 producer-inversions**; 8 other false; 11 marginal. |
| `input:intermediated_air_capacity` | 1 | 1 | Blue Dart. |
| `input:freight_diesel` | **21** | **1** | **Near-worthless as swept.** `fuel (cost\|expense\|consumption)` catches ESG energy-management prose in nearly every report. Only VRL is usable — and the sweep **missed** the real freight-diesel disclosures (VRL's 27.6% cost share, per the bootstrap handover) because those live in cost *tables*, not sentences. |
| `input:crude_derivative_bitumen` | 1 | 0 | |

### 6.5 Two findings that change the design

**(a) The best leaves are narrow-vocabulary leaves.** `base_oil` scores 5/5 because
"base oil" is an unambiguous two-word term with one meaning. `crude_derivative_petchem`
scores 4/32 because it is swept by eleven generic words (`polymer`, `resin`,
`solvent`, `polyester`…) that appear in product descriptions, waste-disposal notes and
directors' biographies. **Leaf precision tracks term specificity, not corpus quality**
— which means the vocabulary's own granularity is a lever on extraction precision,
and `crude_derivative_petchem` is too coarse to extract against.

**(b) Table-form disclosures are systematically missed, and they are often the best
evidence.** CONCOR's freight lines and VRL's lorry-hire percentage are the strongest
`bought_in_freight` evidence in the corpus and both are table rows; the scorer
*penalises* them (CONCOR scored −7). A sentence-based sweep structurally
under-finds exactly the disclosures that carry a number. **A production extractor
needs a table-aware second pass**, and it is where the sized and qualitative routes
would converge.

### 6.6 `MITIGATED` / `UNMITIGATED`, now first-class

v2 sweeps both halves. `UNMITIGATED` — the company telling its shareholders it
cannot reprice — is the half v1 was not looking for and is at least as
decision-relevant:

* **POLYPLEX** — *"any adverse fluctuations in the cost of PET resin can impact the
  Company's operating margins depending upon the Company's ability to pass on cost
  increases to its customers."*
* **APOLLOTYRE** — *"The Company's profitability remains sensitive to volatility in
  raw material prices, particularly in scenarios of sharp cost escalation."*

And a third state the sweep surfaced by accident, which the design has no room for:

* **GOODYEAR** on `fx:usd_cost_share` — *"The company has limited exposure to foreign
  exchange risk due to low reliance on imported raw materials and thus the company
  does not hedge."*

That is a **positive disclosure of LOW exposure** — the "asked and answered no"
state that `DATA_GAPS/modifier-staleness.md` §17.4 records as missing. It is not
absence of evidence; it is evidence of absence, filed. **It should be storable**, and
it is the only thing in this corpus that can honestly keep a company *out* of a
section without a percentage.

---

## 7. ROLE DETERMINABILITY AT ISUBGROUP GRANULARITY

**The question this settles:** can one `role` be assigned to a whole
`official_isubgroup` for a given tag, or does the group contain both producers and
consumers of the same input? If indeterminate, the group cannot publish via
classification and the 4,669-company route does not exist for it.

> **Provenance warning, stated plainly.** The role judgements below are **my own
> knowledge of these companies**, cross-checked against the group membership listed
> from the DB and — where available — against the probe's filing excerpts. They are
> a **feasibility signal only**. They are not sourced, not importable, and must not
> become a mapping. `business_desc` was not used as evidence (Wikipedia, 10.9% fill,
> already ruled non-importable); the DB was used only to enumerate membership.

### 7.1 Group by group

| isubgroup | n | tag tested | verdict |
|---|---|---|---|
| **Lubricants** | **8** | `input:base_oil` | **SURVIVES — uniform CONSUMER.** Castrol, Gulf Oil, Savita, Panama Petro, Veedol, Gandhar, GP Petroleums, Greenhitech. All base-oil blenders. **Independently corroborated: the probe found usable filing sentences for 5 of the 8.** |
| **Paints** | **9** | `input:crude_derivative_petchem` | **SURVIVES — uniform CONSUMER.** Asian, Berger, Kansai, JSW Dulux, Indigo, Sirca, Shalimar, Kamdhenu, Retina. No producer of resins or solvents in the group. |
| **Tyres & Rubber Products** | 17 | `input:crude_derivative_rubber` | **SURVIVES WITH 2 NAMED EXCEPTIONS → 15.** 15 tyre/tread makers are consumers. **Balkrishna Industries** runs its own carbon-black business (backward integration) = `BOTH`. **Cochin Malabar Estates & Indus.** is a *plantation* — a natural-rubber **grower** — sitting inside "Tyres & Rubber Products". |
| **Plastic Products - Industrial** | 58 | `input:crude_derivative_petchem` | **SURVIVES WITH 1 NAMED EXCEPTION → 57.** Pipes (Supreme, Astral, Prince, Apollo, Captain, Kisan, Prakash, Kriti), films, moulded goods, irrigation — all resin consumers. **Finolex Industries** makes its own PVC resin = `BOTH`. |
| **Packaging** | 75 | `input:crude_derivative_petchem` | **FAILS — indeterminate on TWO axes.** The group mixes **glass** (AGI Greenpac, Haldyn) and **paper/carton** (TCPL, Subam, B&B Triplewall) — zero petchem exposure — with BOPET film makers; and several film makers (**Uflex, Ester, Dhunseri**) *produce* PET resin. Applicability and role both fail. |
| **Specialty Chemicals** | 110 | `input:crude_derivative_petchem` | **FAILS — structurally `BOTH` for essentially every member.** A specialty chemical maker buys petchem intermediates and sells petchem derivatives. Net is a **margin** effect whose sign is genuinely indeterminate. That is a legitimate publishable state (MIXED, invariant 9) but it cannot be *assigned* from a classification. |
| **Commodity Chemicals** | 72 | `input:crude_derivative_petchem` | **FAILS — heterogeneous on the input axis itself.** Chlor-alkali (power-driven: Gujarat Alkalis, Chemfab, Lords Chloro, TGV SRAAC), soda ash (energy: Tata Chemicals, GHCL), fertiliser (gas: Deepak Fert, GNFC), phthalic anhydride (genuine crude-derivative consumers: IG Petrochemicals, Thirumalai), borax, fluorine. One tag cannot describe them. |
| **Auto Components & Equipments** | 136 | any single tag | **FAILS.** Forging/steel (Bharat Forge, Ramkrishna, Sundram), glass (Asahi India), lead-acid batteries (Exide, Amara Raja), rubber/plastic parts (Gabriel, Minda), electronics (Bosch). No single input tag applies to the group. |
| **Logistics Solution Provider** | 58 | crude family | **FAILS on a DIFFERENT axis — role determinate, TAG indeterminate.** Every member is a consumer, but of a *different leaf*: **VRL** burns diesel (`freight_diesel`); **Mahindra Logistics / TCI Express** buy road capacity (`bought_in_freight`); **Blue Dart** buys air capacity (`intermediated_air_capacity`); **CONCOR** buys rail haulage. Assigning any one leaf to the group would misdescribe most of it. |

Also examined because it is the inverted population:

| **Petrochemicals** | 14 | `input:crude_derivative_petchem` | **FAILS, and dangerously.** Mostly **PRODUCERS** of crude derivatives — Supreme Petrochem (polystyrene), Manali Petro (polyols), Bhansali (ABS), **Rain Industries (carbon black + calcined pet coke)**, Agarwal Industrial (bitumen) — mixed with acrylic-fibre *consumers* (Pasupati Acrylon, Indian Acrylics). Tagging this group as consumers would publish **backwards direction** on 14 companies. |
| **Rubber** | 11 | `input:crude_derivative_rubber` | **FAILS, and it contains producers of the very input the leaf names.** Apcotex (synthetic latex/NBR **producer**), Rubfila (latex thread), GRP and Tinna (reclaim rubber **producers**), **Harrisons Malayalam (plantation — natural rubber grower)**, against Pix Transmissions (belts — consumer). |

### 7.2 The collapse, quantified

| | companies |
|---|---|
| classified with `official_isubgroup` | **4,669** |
| **surviving the role test for the crude family** | **89** |
| | Lubricants 8 + Paints 9 + Tyres 15 + Plastic Products 57 |
| **share of the classification route** | **1.9%** |

**You expected the 4,669 to collapse hard for crude. It collapses harder than that.**
Four of eight tested groups survive, two of them with named per-company exceptions,
and the survivors are small: three of the four have fewer than 20 members. The one
large survivor (Plastic Products, 57) survives on a single tag.

The 89 also **overlaps** the filing route rather than extending it: Lubricants and
Tyres are exactly where the probe already found usable filing sentences. **The
classification route's marginal contribution over the filing route is smallest
precisely where the filing route already works.**

### 7.3 Does `official_igroup` or `official_industry` disambiguate better?

**No — strictly worse, and the data shows why.** They are coarser, not orthogonal:
190 isubgroups → 58 igroups → 22 industries. Going coarser can only merge
populations that are already mixed.

Two measured examples:

* `Tyres & Rubber Products` (17, uniform-ish) sits inside igroup **`Auto Components`**
  — the same igroup as the 136-member `Auto Components & Equipments` that fails
  outright. **The one group that survives is merged with the one that fails hardest.**
* `Commodity Chemicals`, `Specialty Chemicals` and `Petrochemicals` — a
  consumer-mixed group, a `BOTH` group and a **producer** group — all collapse into
  igroup **`Chemicals & Petrochemicals`**. Consumers and producers of the same input,
  in one bucket.

Note also that `Paints` sits in igroup `Consumer Durables` and industry
`Consumer Durables`, which says nothing about resin.

### 7.4 Is there any exchange-published field that distinguishes producer from consumer?

**No. Neither BSE nor NSE publishes one, and there is a structural reason:** an
exchange classification answers *"what market does this company sell into"*. Producer
versus consumer is a position in an **input-output chain** — a different question,
and one no sector taxonomy is built to answer.

Three sources that genuinely could, none of them exchange-published:

1. **The Ind AS 108 segment note.** It is a **filed** disclosure naming what the
   company *sells*, and the materials note names what it *buys*. Together they
   determine role from evidence. **`company_segment` already exists in the schema
   (migration 0012) and has 0 rows.** This is the structurally correct source and
   V5 already anticipated it.
2. **The MCA NIC code** (5-digit, on MGT-7 and in the annual report). NIC is
   *activity*-based and does separate "manufacture of rubber tyres" from "growing of
   rubber" — it would have caught Cochin Malabar and Harrisons Malayalam. Company-filed,
   not exchange-published, and not in this DB.
3. **The filing sentence itself** — which is the route §6 already measures, at 17 of 52.

### 7.5 Recommendation — put `role` on the graph node, not on the company

The role test failing at group granularity is not only a data problem; it is a
**modelling** problem, and the fix removes most of the need for the field.

`mechanism_edge` already encodes role, and a human already authors it:

* an edge to `industry:tyre_makers` with `relationship_type: INPUT_COST` **is** the
  consumer statement;
* an edge to `industry:carbon_black_producers` with
  `relationship_type: REVENUE_REALIZATION` **is** the producer statement.

Two nodes, two edges, opposite signs, both authored under invariant 13 by the person
who already has to author the mechanism. **The classification map then answers only
"which node is this company at" — which is a question a sector taxonomy CAN answer** —
and the sign is read off the edge, never off the map.

This makes the four failure classes tractable rather than fatal:

| failure | under `role`-on-company | under `role`-on-node |
|---|---|---|
| Petrochemicals, Rubber (producers) | mis-signed unless every member is flagged | point the group at the **producer node**; correct by construction |
| Balkrishna, Finolex (`BOTH`) | a third enum value that no formula consumes | membership of **two** nodes → two channels, opposite signs → **MIXED**, which the reducer already produces honestly |
| Cochin Malabar, Harrisons (plantations) | a wrong default needing a named override | a per-company override of **node membership** — same review surface, one concept |
| Logistics (right role, wrong leaf) | unaffected — still broken | **fixed**: four different nodes, one per member's actual leaf |

So `role` survives, but **as an override on node membership, not as a column on a
mapping** — a group-level default plus named per-company exceptions, both reviewed
through the same path. That is what §8 of the manifest design encodes.

**The consequence for the plan, stated plainly:** the classification route delivers
**89 companies for the crude family**, not 4,669. It is a supplement to the filing
route, not a replacement for it, and it should be sequenced **after** the filing
route rather than instead of it.

---

## 8. What I did not do

* Did not implement the tier, write the isubgroup map, or touch `mechanism_edge`.
* Did not run migrations, insert rows, or run the suite.
* Did not read `docs/v5/CONSOLIDATED_STATE_2026-08-17.md` — still absent from this
  tree.
* Did not measure the qualitative route's **post-review** yield. 38% precision comes
  from a 64-sentence sample drawn as "first 4 distinct companies per leaf in ISIN
  order" — **not a random sample**, and the confidence interval on it is wide.
* Did not extrapolate any count to 3,400 or to the 2,158 recommended universe.
* Did not verify §D.3's peer-closure noise bug by execution.
* `rate:nim_asset_sensitivity` returned 7 false positives from my own pattern error
  (no bank in the corpus); not corrected, reported as-is.
