# PATCH-002 — two corrections found by measurement

**Status:** PATCH, NOT APPLIED. `mechanism_edge` untouched, no ledger row written.
**Section B REWRITTEN 2026-08-17** after re-verification against the dev DB: its
original premise (no Delhivery ledger row) was false. See the box in §B.
Both were found by the contradiction sweep
(`MEMBERSHIP_CLAIM_ASSESSMENT.md` §7, `_contradiction_2026-08-17.txt`).

| # | correction | layer | evidence |
|---|---|---|---|
| A | `packaging_film_makers` becomes a **BOTH-edge node** | node / manifest layer 6 | 3 of 6 corpus members are backward-integrated |
| B | ~~Delhivery is tagged at the wrong leaf~~ → **`NODE_FOR_ISUBGROUP` is coarser than the ledger** | **probe / node mapping, NOT ledger** | the ledger already carries the correct tag |

---

## A. `packaging_film_makers` — a BOTH-edge node, like Specialty Chemicals

### A.1 What was measured

Of the 6 corpus companies at this node, **3 disclose that they manufacture the polymer
their node says they buy** — a 50% backward-integration rate, the highest of any node
tested:

| company | p | excerpt |
|---|---|---|
| **POLYPLEX** | 58 | *"The Company produces its own film grade PET resin."* |
| **UFLEX** | 7 | *"our PET resin manufacturing operations, with the upgraded Panipat, India, facility now capable of producing 480 TPD bottle-grade virgin PET chips"* |
| **JINDALPOLY** | 72 | *"The company started manufacturing polyester chips for captive use in 1993."* |

Not backward-integrated: HUHTAMAKI, COSMOFIRST, XPROINDIA.

**This is a property of the node, not of three companies.** BOPET film-making is
capital-intensive and polymerisation sits one step upstream of film extrusion; half a
listed film sector integrating into it is structural, not coincidental.

### A.2 The correction

`packaging_film_makers` carries **two opposite-signed edges**, exactly as
`specialty_chemical_makers` does:

```yaml
# manifest layer 3 -- REPLACES the single consumer edge
mechanism_edges:
  - edge_id: petchem_packaging_film_input_cost
    from_node: BRENT_CRUDE
    to_node: industry:packaging_film_makers
    exposure_tag: input:crude_derivative_petchem
    relationship_type: INPUT_COST                 # buys resin       -> NEGATIVE
    distance: 2
    derivation: AUTHORED
    confidence: <REQUIRED>
    source_url: <REQUIRED>

  - edge_id: petchem_packaging_film_realization
    from_node: BRENT_CRUDE
    to_node: industry:packaging_film_makers
    exposure_tag: input:crude_derivative_petchem
    relationship_type: REVENUE_REALIZATION        # makes resin      -> POSITIVE
    distance: 2
    derivation: AUTHORED
    confidence: <REQUIRED>
    source_url: <REQUIRED>
    note: >
      Added because 3 of 6 corpus members disclose in-house PET resin or
      polyester chip manufacture. Without this edge the node asserts a pure
      consumer position that half its members contradict in their own filings.
```

### A.3 The consequence, and it is not free

Both edges fire for **every** member, so the whole node publishes **MIXED** — including
the three that are **not** integrated (Huhtamaki, Cosmo First, Xpro India). That is
the same over-broadening that put Specialty Chemicals in the withheld pile.

**Three options. (2) is recommended.**

| | option | effect |
|---|---|---|
| 1 | leave as a pure consumer edge | 3 of 6 published against their own disclosure. **Rejected** — this is the case §5.3 calls indefensible |
| 2 | **BOTH edges + per-company node membership** | integrated members sit at **both** `packaging_film_makers` and `petrochemical_producers` → MIXED. Non-integrated members sit at the consumer node only → NEGATIVE. **6 companies, named individually, one reviewed call each** |
| 3 | BOTH edges for the whole node | all 6 MIXED, node joins the withheld pile |

Option 2 is the `role`-as-per-company-override mechanism from
`FAMILY_MANIFEST_DESIGN` §2.1, used for the first time on measured evidence:

```yaml
nodes:
  - node: industry:packaging_film_makers
    membership:
      default_from_isubgroup: ["Packaging"]      # NOTE: needs the sub-split --
                                                 # "Packaging" also holds glass
                                                 # and paper. See A.4.
  - node: industry:petrochemical_producers
    membership:
      default_from_isubgroup: ["Petrochemicals"]
      include:
        - company: POLYPLEX.NS
          reason: "produces its own film grade PET resin (AR FY2026 p58)"
        - company: UFLEX.NS
          reason: "PET resin manufacturing, 480 TPD Panipat (AR FY2026 p7)"
        - company: JINDALPOLY.NS
          reason: "manufactures polyester chips for captive use (AR FY2026 p72)"
```

**Each `include` carries a filing citation.** These are not classification judgements —
they are `EXAMINED_CONFIRMS` findings, and they are why the membership-only default
needs the filing exception handler at all.

### A.4 Blocked on the Packaging sub-split

`Packaging` (75 companies) also contains glass (AGI Greenpac, Haldyn) and paper (TCPL,
Subam, B&B Triplewall), which carry **no** petchem exposure. This node cannot take
`default_from_isubgroup: ["Packaging"]` until that sub-split exists
(`MEMBERSHIP_CLAIM_ASSESSMENT` §1.2). **Until then, membership is the 6 named corpus
companies and nothing else.**

---

## B. DELHIVERY — a correction to `NODE_FOR_ISUBGROUP`, not to the ledger

> **REWRITTEN 2026-08-17, and the original was wrong.** This section previously
> claimed *"No `company_exposure` row exists for Delhivery on any leaf"* and treated
> the fix as a pre-emptive ledger correction. **Re-verified against the dev DB:
> Delhivery HAS a ledger row, and it is ALREADY at `input:bought_in_freight` — the tag
> this section says is correct.**
>
> ```
> company_id     216  DELHIVERY.NS
> exposure_tag   input:bought_in_freight        <- already correct
> share_of_base  0.3133         base_kind  TOTAL_COST
> measurement    ESTIMATED      source     ANNUAL_REPORT p."145 + 127"
> reviewed_by    ST269 (repo owner)
> ```
>
> **The ledger was ahead of this design.** What was wrong was not the stored tag but
> `NODE_FOR_ISUBGROUP` in `backend/scripts/probes/contradiction_rate.py`, which
> collapsed the whole `Logistics Solution Provider` isubgroup onto one node asserting
> `["diesel", "freight"]`. The "wrong leaf" finding was an artefact of **my own node
> mapping being coarser than data that already existed.**
>
> Consequences, all recorded rather than buried: **the contradiction rate drops from
> 2/33 to 1/33** (`MEMBERSHIP_CLAIM_ASSESSMENT` §7, corrected), Delhivery is **not** a
> contradiction, and there is **nothing to migrate**.

### B.1 What was measured

The contradiction probe placed Delhivery at `logistics_operators`, a node **this
probe invented**, asserting `input:freight_diesel` (a company **burning** diesel it
bought). Its own filing, p67:

> *"Commodity price risk or foreign exchange risk and their respective hedging
> activities — The Company considers commodity price risk and currency risk to be low
> and does not hedge these risks."*

Surfaced as a `DISCLOSED_IMMATERIAL` candidate against **the probe's node**, not
against the ledger.

Delhivery is **asset-light**: it buys transport capacity from operators who burn the
diesel. `config/exposure_tags.yaml` already makes exactly this distinction, in its own
words:

> `freight_diesel` is a company **BURNING** diesel it bought: the price moves, the cost
> moves, promptly and roughly one-for-one. `bought_in_freight` is a company buying
> transport **CAPACITY** from an operator who burns the diesel. The bill it pays
> contains driver wages, tolls, tyres, financing and the operator's margin, so a crude
> move reaches it lagged, diluted and only to the extent the operator has pricing
> power.

**Delhivery's "commodity price risk is low" is precisely what the vocabulary predicts
an intermediated buyer would say** — the bill it pays is diluted by driver wages,
tolls, tyres, financing and the operator's margin. **Against the tag the ledger
actually carries, the disclosure contradicts nothing. It corroborates.**

The disclosure was never a contradiction of the economics. It was a contradiction of a
node the probe invented, and the ledger had already got it right.

### B.2 The correction

`logistics_operators` is **not one node.** Its members buy different things, and the
sub-split was already flagged (`MEMBERSHIP_CLAIM_ASSESSMENT` §1.2, "role determinate,
tag indeterminate"). Corpus members, by mode — **and the `leaf` column is now read off
the ledger, not proposed**:

| company | leaf | node |
|---|---|---|
| VRLLOG | `input:freight_diesel` — own CV fleet, *"pioneered usage of Bio diesel for its CV fleet"* | `road_freight_operators` |
| TCI | `input:freight_diesel` — own fleet + ships | `road_freight_operators` |
| **DELHIVERY** | **`input:bought_in_freight`** — asset-light, buys capacity | **`asset_light_3pl`** |
| **MAHLOG** | **`input:bought_in_freight`** — 78% 3PL contract logistics (AR p54) | **`asset_light_3pl`** |
| TCIEXP | `input:bought_in_freight` — express, largely bought-in | `asset_light_3pl` |
| BLUEDART | `input:intermediated_air_capacity` — *"charter flight services rendered exclusively to the Company"* | `express_air_logistics` |
| CONCOR | rail haulage bought from Indian Railways — **no leaf fits** | see B.4 |

### B.3 Ledger impact — NONE, and not for the reason first given

**Nothing to migrate. The ledger already carries the correct tag for all six logistics
companies**, verified read-only against the dev DB:

| tag | companies | share_of_base |
|---|---|---|
| `input:bought_in_freight` | DELHIVERY · TCIEXP · TCI · MAHLOG | 0.313 · 0.705 · 0.613 · 0.705 |
| `input:freight_diesel` | VRLLOG · CONCOR | 0.276 · 0.015 |

VRL's **0.276** matches the 27.6% diesel cost share the ripple-bootstrap handover
records independently — a useful cross-check that these rows are the ones that
handover describes.

**So the sub-split this patch proposes as new work is already done in the data, for 6
of 6 corpus members.** What remains is authoring the **nodes** that point at those
tags, which is manifest layer 6 and touches no ledger row.

**Delhivery's `DISCLOSED_IMMATERIAL` status is retained** — the company did say its
commodity risk is low, and that is worth storing. But it is **no longer an
`EXAMINED_CONTRADICTS`**: under `bought_in_freight` the disclosure agrees with the
tag. It is `EXAMINED_CONFIRMS` with a low-sensitivity qualifier, which is a different
record and a different render. **Goodyear remains the only `EXAMINED_CONTRADICTS` in
the corpus.**

### B.3a What this says about the method

Recorded because it is the reusable part. **The probe's node table was a design
artefact written from an isubgroup name; the ledger was written from filings.** Where
they disagreed, the filings were right. Two rules follow:

1. **A node mapping must be checked against existing ledger rows before it is used to
   score anything.** `contradiction_rate.py` never queried `company_exposure` for the
   tags it was testing — it asserted them from `NODE_FOR_ISUBGROUP` and measured
   against its own assertion.
2. **This is the same failure class as the leaf-vocabulary one PATCH-001 Rule 2
   exists to catch** — a structure authored from a name rather than checked against
   data. There it was `steel_flat` against buyer prose; here it was
   `logistics_operators` against the ledger. **PATCH-001's rule should be read as
   covering nodes as well as leaves.**

### B.4 CONCOR — a gap this exposes, not fixed here

CONCOR buys **rail haulage from Indian Railways**, an administered tariff. That is
neither `freight_diesel` (it burns nothing) nor `bought_in_freight` (whose comment
says "bought-in road/rail capacity" — but a rail tariff set by a government is a
**policy** variable, not a market price, and the vocabulary's own bitumen/diesel
precedent says an administered price is a Phase 4 policy question, not an elasticity).

CONCOR's strongest evidence — *"Rail freight expenses 5,022.02 / Road freight expenses
326.65"* (p412) — is a **table**, which the sentence sweep systematically under-finds
(`MEASUREMENTS` §6.5b).

**Recorded, not patched.** It needs a vocabulary decision, and per PATCH-001 Rule 2 no
leaf should be authored for it until a rail-logistics corpus has been swept.
