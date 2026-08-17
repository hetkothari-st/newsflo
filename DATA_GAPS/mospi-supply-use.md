# DATA GAPS — MOSPI Supply-Use at ripple-family granularity

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

## 15. MOSPI Supply-Use is unusable at ripple-family granularity — MEASURED 2026-08-17

**A correction to a claim I made in `docs/v5/decisions/ADR-001-econometric-exposure.md`
before checking it. Recorded here rather than quietly fixed.**

**What I claimed:** MOSPI Supply-Use tables reach the same coverage goal as the
rejected econometric amendment at 2–3 pw, with no amendment and no §A3.2
exposure — implying the econometric route was moot.

**What is actually true.**

* **Granularity is one to two levels above the ripple families.** Per the MOSPI
  methodology note, NAS publishes manufacturing in 30 activity groups —
  *"compilation category, which is a combination of NIC codes representing similar
  activity"* — and *"these 30 compilation categories have been kept as 30 industries
  in the SUT."* Industry names are NIC-division style
  (*"Manufacture of coke and refined petroleum products"*). So **paints, adhesives,
  specialty chemicals and fertilisers collapse into one chemicals industry, and
  tyres and packaging films into one rubber-and-plastics industry.** The SUT gives
  an input share for *chemicals*, not for *paints*. §A5.2's sector-coherence rule
  wants families; the SUT cannot supply them. **MOSPI does not solve the failing
  measurement in §14. It solves a coarser version of it.**
* **The crosswalk is the real cost, not a detail.** `companies.official_isubgroup`
  is populated for 4,669 of 4,814 Indian companies, but its vocabulary is **BSE's
  Basic Industry classification — 190 distinct values,
  `classification_source = 'BSE'`** (e.g. *Consumer Durables → Consumer Durables →
  Paints*). It is **not NIC**. Mapping 190 BSE basic industries onto ~66 SUT
  industries is a many-to-one, lossy, **hand-authored** crosswalk — which is
  exactly what `config/industry_mapping.yaml` is, and why it refuses to load
  (§7). My "the join key already exists" was wrong: the *granularity* to join at
  exists, the *crosswalk* does not, and it is judgement work the owner or an
  analyst must do.
* **Retrievability is unverified.** Latest release is SUT 2022-23 and 2023-24;
  the prior release (2020-21 and 2021-22, published 30 July 2025) covers 140
  products × 66 industries from NAS 2024 and ASI. The landing page,
  `https://mospi.gov.in/publication/supply-use-tables`, returns HTTP 200 but is a
  client-side application: it served **no file links** to `curl` with a browser
  user-agent, and a headless browser redirected to the site root with an empty
  snapshot. The PIB release page returns **403**. The one confirmable file,
  `https://www.mospi.gov.in/sites/default/files/NMDS_SUT.xlsx`, is HTTP 200 with
  an xlsx content-type and **16,149 bytes** — far too small to be a 140 × 66
  matrix pair, so almost certainly a metadata-structure file, not the tables.
  **No machine-parseable URL for the tables themselves has been located.**

**Revised estimate: 3–5 pw, contingent on a file format nobody has confirmed.**
If the tables are PDF-only, add 2–3 pw and the route is materially less
attractive. **Owner: repo owner** — one browser session settles the format
question.

**What this does NOT change.** ADR-001's rejection of the econometric amendment
stands on grounds (a) §A3.2 tag-assignment silence, (b) §A2.4's existing ruling,
and (c) zero quarters of margin history for 5,321 of 5,321 companies. Each is
independently sufficient and (c) is dispositive. Ground (d) — the MOSPI
alternative — is the one weakened here, and it was never load-bearing.
