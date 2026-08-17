# THE MECHANISM-FAMILY MANIFEST — design

**Status:** DESIGN ONLY. Nothing implemented. No schema changed, no row written,
`mechanism_edge` untouched.
**Supersedes:** §G.2 of `docs/v5/QUALITATIVE_TIER_DESIGN.md`, which this revises in
two places — the layer count is **six**, not four, and `role` moves off the
classification map onto the graph node (`docs/v5/MEASUREMENTS_2026-08-17.md` §7.5).

---

## 1. What this exists to fix

Adding one mechanism family currently requires edits in **six** places, each with a
different rule, each individually valid, and **no reviewer ever sees all six at
once.** Measured today (`MEASUREMENTS_2026-08-17.md` §3): **44 closure failures** —
15/15 shock variables orphaned, 26/28 exposure tags orphaned, 2/2 edges unlabelled,
and both live edges hanging off a `from_node` no shock walks from.

| # | layer | artefact | rule for changing it |
|---|---|---|---|
| 1 | shock variable | `config/discovery.yaml::modelled_shock_variables` | an unmodelled `from_node` is reported `unmodelled` and never walked |
| 2 | exposure leaf | `config/exposure_tags.yaml` | its own header: a code review of THAT file plus a loader re-run; enforced at the **database** by the `valid_exposure_tag` trigger |
| 3 | causal edge | `mechanism_edge` row | invariant 13 — authored by a named human, never by a model |
| 4 | section label | `config/section_taxonomy.yaml::labels` | absent → `UNCLASSIFIED MECHANISM (<mangled uuid>)` in a user-facing header, **and its own singleton section** |
| 5 | policy modifier | `config/policy_modifiers.yaml` | same `pending_tag` convention; on the same seam |
| 6 | node membership | *(new)* `official_isubgroup` → node map | which companies sit at the node the edge points to |

**The layers are not independent.** A tag with no edge is unreachable; an edge with
no tag is refused by the trigger; an edge with no label renders an internal id to a
reader; a variable with no edge is silently inert; a node with no membership publishes
nothing. Each is individually reviewable and the *combination* is what carries
meaning — so six separate reviews make the completeness check structurally
impossible.

**One reviewed unit. One loader. All-or-nothing.**

---

## 2. Shape

One file per family: `backend/config/families/<family_id>.yaml`.

The shape is **not invented** — `config/mechanism_edges_authored.yaml` is already
~80% of it (`shock_variables` with a `status`, `pending_tag`, `edges`,
`section_label_proposed`). This promotes that file's shape into the reviewed path.

```yaml
family_id:   fertilizer_subsidy
version:     1
owner:       <named human>          # required. No default. The loader refuses null.
reviewed_at: <date>                 # required
supersedes:  null                   # a prior version, when this replaces one

# ---------------------------------------------------------------- LAYER 1
shock_variables:
  - name: FERTILIZER_SUBSIDY_OUTLAY
    status: PENDING                 # PENDING | MODELLED (already in discovery.yaml)
    definition: >
      The budgeted-versus-actual nutrient subsidy outlay. Moves on budget day,
      on supplementary demands, and on every import-price swing.
    observed_at: <URL of the published series>   # required to leave PENDING
    sign_convention: >
      UP = outlay rises. Stated because a subsidy is one of the few variables
      where "up" is ambiguous without it.

# ---------------------------------------------------------------- LAYER 2
exposure_leaves:
  - tag:    revenue:subsidy_realization_share
    family: revenue                 # must be an existing family key
    group:  realization             # organisational; never part of the wire form
    definition: >
      The share of revenue that arrives from the government rather than from
      the customer.
    carried_by: urea and complex fertiliser producers
    exposure_kind: REVENUE_REALIZATION      # must have a §5.1 formula, or say why not
    freshness_days: 400                     # must resolve in config/freshness.yaml
    not_a_substitute_for: >
      rate:floating_debt_share describes how the borrowing reprices, not how
      much of the revenue is a receivable in the first place.

# ---------------------------------------------------------------- LAYER 3
mechanism_edges:
  - edge_id:  fertilizer_subsidy_receivable_wc
    from_node: FERTILIZER_SUBSIDY_OUTLAY
    to_node:   industry:urea_producers        # see LAYER 6 -- role lives HERE
    exposure_tag: revenue:subsidy_realization_share
    relationship_type: REGULATORY
    distance: 1
    derivation: AUTHORED
    confidence: <required. No default. The loader will not invent one.>
    source_url: <required>
    mechanism: >
      A urea maker sells at a farm-gate price the government fixes and recovers
      the difference as subsidy. When disbursement lags the sale, the unpaid
      balance sits as a receivable and the company borrows to fund the gap.

# ---------------------------------------------------------------- LAYER 4
section_labels:
  fertilizer_subsidy_receivable_wc: FERTILIZER SUBSIDY RECEIVABLES

# ---------------------------------------------------------------- LAYER 5
policy_modifiers: []                # same pending_tag convention; often empty

# ---------------------------------------------------------------- LAYER 6
nodes:
  - node: industry:urea_producers
    # THE SIGN LIVES ON THE EDGE THAT POINTS HERE, NOT ON THIS LIST.
    # See MEASUREMENTS_2026-08-17.md §7.5. A node is a POSITION IN THE CHAIN;
    # membership is the only question this section answers.
    membership:
      default_from_isubgroup: ["Fertilizers"]
      # Named exceptions, each with a reason. A group whose members do not all
      # sit at the same node is REFUSED unless every deviation is named here.
      exclude:
        - company: <ticker>
          reason: <why this member is not at this node>
      include:
        - company: <ticker>
          reason: <why this non-member is>
    role_note: >
      Free text for the reviewer. NOT a machine field: the machine reads the
      relationship_type of the edge pointing at this node.
```

### 2.1 The one substantive change from §G.2 — `role` moved

§G.2 put `primacy: PRIMARY|INCIDENTAL` on the classification map, and the owner
upgraded it to `role: CONSUMER|PRODUCER|BOTH|INCIDENTAL`. **§7 of the measurements
shows why neither belongs there.**

Role on a *company mapping* fails four ways, all measured:

| case | on the map | **on the node** |
|---|---|---|
| Petrochemicals (14), Rubber (11) — producers of the very input the leaf names | mis-signed unless every member is flagged | point the group at a **producer node**; the edge's `REVENUE_REALIZATION` supplies the sign |
| Balkrishna (own carbon black), Finolex (own PVC) — `BOTH` | a third enum value no §5.1 formula consumes | membership of **two** nodes → two channels, opposite signs → **MIXED**, which the reducer already produces honestly (invariant 9) |
| Cochin Malabar, Harrisons Malayalam — plantations inside rubber groups | a wrong default needing a per-company override of a field | a per-company override of **node membership** — one concept, one review surface |
| Logistics (58) — role right, **leaf** wrong per member | unaffected; still broken | **fixed** — four different nodes, one per member's actual leaf |

And it is where invariant 13 already puts a human. **The sign of a mechanism is
already a human-authored property of an edge. Putting it on a company map would be a
second place the sign is decided, and the two would drift.** So: nodes carry
membership; edges carry direction; the map answers *"which node"*, which is a
question a sector taxonomy can actually answer.

---

## 3. `MITIGATED` / `UNMITIGATED` — where the state lives

**Not in the manifest.** A recovery mechanism is a **company** fact backed by a
company-named filing sentence; a manifest is a **family** artefact. Putting it in the
manifest would put a company claim in a file that carries none, and would make it
un-reviewable per company.

The manifest declares only that the family **admits** the state and which claim type
carries it:

```yaml
pass_through:
  claim_type: PASS_THROUGH                # claims.EVIDENCE_REQUIRED_TYPES already
  states: [MITIGATED, UNMITIGATED]        # both first-class
  evidence_requirement: COMPANY_NAMED_FILING   # already enforced by claims.py:108
  qualitative: true                       # no curve, no ratio, no lag in days
  applies_to_tags: [revenue:subsidy_realization_share]
```

Everything else is already built and needs no change:

* `claims.EVIDENCE_REQUIRED_TYPES` contains `PASS_THROUGH` and forces
  `BOUND`-or-`UNBOUND` — no sector proxy, no exceptions, *"deliberately not
  configurable"*;
* `ACCEPTED_SOURCES` already restricts it to the four filing types;
* an `UNBOUND` claim is a hard gate REJECT.

**Three states, and the third is not optional.** `MITIGATED` and `UNMITIGATED` are
what the owner accepted. The corpus produced a third by accident and it is the only
thing measured that can honestly keep a company **out** of a section without a
percentage:

> **GOODYEAR** — *"The company has limited exposure to foreign exchange risk due to
> low reliance on imported raw materials and thus the company does not hedge."*

That is a filed, positive disclosure of **low exposure** — evidence of absence, not
absence of evidence. It is `DATA_GAPS/modifier-staleness.md` §17.4's missing
"asked and not disclosed" state, in its stronger form. **Recommend a third state,
`DISCLOSED_IMMATERIAL`**, storable and publishable as a reason a company does *not*
appear. Without it, the only way to exclude Goodyear from a crude section is to have
never looked at it — which is D10 wearing a different hat.

Rendering, per tier:

| state | published as | tier effect |
|---|---|---|
| `MITIGATED` | *"states a contractual recovery mechanism"* | keeps the company, softens the direction label |
| `UNMITIGATED` | *"states it cannot fully reprice"* | keeps the company, **strengthens** the claim |
| `DISCLOSED_IMMATERIAL` | *"discloses low exposure"* | **excludes** the company, with the citation shown |
| absent | nothing | no effect — silence is not a claim |

---

## 4. The loader — one entry point

`backend/app/graph/family_loader.py`. Generalises `authored_edges.blockers()`, whose
discipline is already right: *"ALL blockers are reported, not the first one."*

### 4.1 `--validate` (default; always runs first)

Validates the **whole manifest** and **writes nothing if anything is blocked.**
A run that silently landed four of six layers is not a possible outcome.

Refusals, each of which is a guarantee rather than a validation nicety:

* `owner` or `reviewed_at` null → **a manifest is somebody's judgement and it is signed**
* any `confidence` null → `mechanism_edge.confidence` is `NOT NULL` and a confidence
  is a judgement; the loader does not invent one
* any `reviewed_by` present → **a loader may not approve.** Approval is
  `app/ledger/edge_review.approve_edge`, which records who did it
* an `exposure_kind` with no §5.1 formula, unless the leaf declares
  `sizes: false` explicitly (the qualitative tier's normal case)
* a `freshness_days` that does not resolve in `config/freshness.yaml` — the file
  RAISES for three kinds by design, and a manifest must not route around it
* a `to_node` with no `nodes:` entry, or a `nodes:` entry no edge points at
* an `official_isubgroup` in `membership` that does not exist in `companies`
* a `default_from_isubgroup` whose members do not all sit at the node, **unless every
  deviation is named** in `exclude`/`include` with a reason

### 4.2 `--emit-patch`

**Does not edit the config files.** Layers 1, 2, 4 and 5 are vocabulary, and their
headers make extending them a review of *that* file. The loader emits the exact YAML
fragments; a human reads them, commits them, and re-runs.

This is the single most important property of the design. **A loader that appended to
`exposure_tags.yaml` would make vocabulary extension a side effect of a data run**,
which that file's header exists to forbid.

### 4.3 `--apply`

Re-reads the **committed** configs (not the manifest's copy of them — if the human
edited the fragment, the edit wins), then:

1. resync `valid_exposure_tag` from `exposure_tags.yaml` (migration 0016 is the
   precedent);
2. insert `mechanism_edge` rows as `derivation: AUTHORED`, `review_status: PENDING`,
   `reviewed_by: NULL` — **always**, invariant 13 intact;
3. insert node membership;
4. re-run the closure assertions and **print the six-layer checklist with ✓/✗**.

Idempotent on `edge_id`. **An edge already present is never overwritten** — a re-run
must not quietly un-review a decision a person made.

### 4.4 One semantics the manifest must confront, not inherit

`traverse.usable()` walks an `AUTHORED` edge while `review_status` is still
`PENDING`, deliberately, per Task 3.4 — and `edge_review.pending_edges` selects only
`IO_TABLE`/`EMPIRICAL`, so **`AUTHORED` edges are not in the review queue at all.**

Consequence, which `mechanism_edges_authored.yaml`'s header already states:
**running the loader IS the approval act.** That is defensible for an edge a person
wrote by hand. It is *not* defensible for one a model drafted into a manifest.

**Recommend the manifest carry `authorship: HUMAN | MODEL_DRAFTED`, and that
`MODEL_DRAFTED` load as `derivation: AUTHORED` but be forced into the review queue**
— because DEFECTS-001 D2 is exactly this hole and it is still open. Without it, the
manifest becomes a supported path for model-drafted content to go live unreviewed,
which is invariant 13 defeated by process rather than by code.

---

## 5. The completeness test

`test_no_orphan_mechanism_family`, asserting over live config + DB:

| # | assertion |
|---|---|
| A1 | every `modelled_shock_variables` entry is the `from_node` of ≥1 edge, or `PENDING` in a manifest |
| A2 | every edge's `from_node` **is** a modelled shock variable |
| A3 | every `valid_exposure_tag` leaf is the `exposure_tag` of ≥1 edge, or declared unused |
| A4 | every edge's mechanism has a section label **after `normalize_node_id`** |
| A5 | every `to_node` has a `nodes:` entry with non-empty membership |

Already built and running as a script:
`backend/scripts/probes/mechanism_family_closure.py` (A1–A4). **Current baseline: 44
failures.**

**Do not make it a test yet.** 44 failures in CI is noise, not signal. It becomes a
test **when the first manifest lands**, with 44 recorded as a baseline it must
monotonically reduce — so the suite enforces "no new orphans" long before it can
enforce "no orphans".

---

## 6. Sequencing — what §7 of the measurements changes

The classification route yields **89 companies for the crude family, not 4,669**
(1.9%), and the survivors — Lubricants, Paints, Tyres, Plastic Products — **overlap
the population the filing route already reaches.** Its marginal contribution is
smallest exactly where the filing route works.

Therefore:

1. **Filing route first.** 17 of 52 measured, on a corpus already on disk.
2. **The manifest second**, for the crude family, using the 89 as layer 6 — with
   Lubricants and Paints as the first two nodes, because they are the only groups
   that survived the role test **uniformly** (no named exceptions) and both are
   independently corroborated by filing sentences.
3. **`crude_derivative_petchem` needs splitting before either.** It scored 4 usable
   of 32 pairs and produced 9 producer-inversions — the worst leaf measured — because
   it is swept by eleven generic words (`polymer`, `resin`, `solvent`, `polyester`…).
   Leaf precision tracks **term specificity**; this leaf is too coarse to extract
   against and too coarse to classify against. **Splitting it is layer-2 work and
   belongs in the manifest that first uses it.**

---

## 7. What this design does not do

* Does not relax the entailment firewall, the `mechanism_id` requirement, the closed
  exposure vocabulary, invariant 13, evidence citation, or the single-writer reducer.
* Does not let a model write `mechanism_edge` — §4.4 tightens the one process route
  by which that could have happened.
* Does not fix D10 / D10.1 / D11 / D12 / D13. Those are prerequisites, not
  consequences: **a manifest that lands while D10 is open publishes its first
  starved company as `NO_MATERIAL_IMPACT`.**
* Does not author a map, a node, an edge or a leaf. Nothing here is data.
