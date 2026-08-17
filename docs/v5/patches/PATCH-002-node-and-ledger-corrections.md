# PATCH-002 — two corrections found by measurement

**Status:** PATCH, NOT APPLIED. `mechanism_edge` untouched, no ledger row written.
Both were found by the contradiction sweep
(`MEMBERSHIP_CLAIM_ASSESSMENT.md` §7, `_contradiction_2026-08-17.txt`).

| # | correction | layer | evidence |
|---|---|---|---|
| A | `packaging_film_makers` becomes a **BOTH-edge node** | node / manifest layer 6 | 3 of 6 corpus members are backward-integrated |
| B | Delhivery is tagged at the **wrong leaf** | ledger | the company's own filing |

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

## B. DELHIVERY — wrong leaf

### B.1 What was measured

Delhivery sits at `logistics_operators`, which asserts `input:freight_diesel`
(a company **burning** diesel it bought). Its own filing, p67:

> *"Commodity price risk or foreign exchange risk and their respective hedging
> activities — The Company considers commodity price risk and currency risk to be low
> and does not hedge these risks."*

Surfaced as a `DISCLOSED_IMMATERIAL` candidate, and it is one — **but the more useful
reading is that the leaf is wrong.**

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
an intermediated buyer would say.** The disclosure is not a contradiction of the
economics; it is a contradiction of the tag.

### B.2 The correction

`logistics_operators` is **not one node.** Its members buy different things, and the
sub-split was already flagged (`MEMBERSHIP_CLAIM_ASSESSMENT` §1.2, "role determinate,
tag indeterminate"). Corpus members, by mode:

| company | leaf | node |
|---|---|---|
| VRLLOG | `input:freight_diesel` — own CV fleet, *"pioneered usage of Bio diesel for its CV fleet"* | `road_freight_operators` |
| TCI | `input:freight_diesel` — own fleet + ships | `road_freight_operators` |
| **DELHIVERY** | **`input:bought_in_freight`** — asset-light, buys capacity | **`asset_light_3pl`** |
| **MAHLOG** | **`input:bought_in_freight`** — 78% 3PL contract logistics (AR p54) | **`asset_light_3pl`** |
| TCIEXP | `input:bought_in_freight` — express, largely bought-in | `asset_light_3pl` |
| BLUEDART | `input:intermediated_air_capacity` — *"charter flight services rendered exclusively to the Company"* | `express_air_logistics` |
| CONCOR | rail haulage bought from Indian Railways — **no leaf fits** | see B.4 |

### B.3 Ledger impact — none today

**No `company_exposure` row exists for Delhivery on any leaf.** This is a correction to
a node mapping that has not been authored yet, not a rewrite of stored data. **Cheap
now; a review-path ledger migration once the row exists**, because `exposure_tag` is
one of the columns the 0012 trigger guards and there is no reviewed UPDATE path for it.

**Delhivery's `DISCLOSED_IMMATERIAL` status is retained** and is not superseded by the
retag: the company said its commodity risk is low, and that remains true and cited
under `bought_in_freight` too. It should publish at the correct leaf **with** the
disclaimer attached — which is `EXAMINED_CONTRADICTS` doing exactly what §3 of
TICKET-001 specifies.

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
