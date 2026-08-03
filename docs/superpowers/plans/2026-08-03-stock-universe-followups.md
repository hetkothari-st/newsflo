# Stock Universe — Known Follow-ups

Deferred findings from the 20-task implementation of
`docs/superpowers/specs/2026-08-03-stock-universe-cap-tiers-design.md`.

Every item here was raised by a review, judged non-blocking, and consciously deferred.
None is a merge blocker. They are recorded because the reasoning behind each deferral
was specific, and re-deriving it later would cost more than writing it down.

Ordered by what would bite first in production.

## Operational

**Listing rows are never retired.** `loader.upsert_records` adds and updates listings but
never removes one that has vanished from the exchange master. A stale row holds
`uq_listing_exchange_symbol` hostage, so a later legitimate reuse of that symbol is
skipped forever. Watch the `skipped` count in ingest output; add retirement before the
daily job has been running for a long stretch.

**Snapshot directories are never pruned.** `data/universe/<day>/` accumulates daily
master files plus a monthly ~5,000-file detail directory, indefinitely. Add retention.

**`latest_detail_day` accepts any day with at least one JSON file.** A crashed monthly
pass on a newer day therefore shadows a complete older one. This degrades to staleness
only and can never clobber stored classification, because `upsert_records` refuses to
write absent classification — but the newest-wins rule is cruder than it looks.

**`flag_missing_tickers` never clears `SUSPENDED`** when a symbol reappears in a master.
Low impact: it is a one-shot script, and the daily ingest recomputes `tradeability` via
`_ALWAYS_FIELDS` for anything still present in a master.

**`rebuild_aliases` issues two statements per company** — roughly 10k round trips against
Postgres on every daily run (4.1 s for 4,967 companies on in-memory SQLite). Batch the
delete and use a bulk insert.

**`ripple.py` resolves cap tier per row**, so one full companies scan and sort per
card-back row (~15 rows/alert). Measured 105 ms per card back at 4,967 companies versus
49 ms for a single `cap_tier_map` pass. Tolerable; worth switching.

**`ingest_universe.py` reports failures with `print()`, not `logging`** — so nothing
routes to log aggregation now that Task 20 runs it under the scheduler rather than
interactively.

## Correctness hardening

**`app/companies/loader.py`'s keyword `SECTOR_MAP` is still live.** `sector_map.py` says
it "REPLACES" it, but the old path survives via `nifty_loader._normalize_sector` and
`seed_nifty_indices.py`. Re-running that seeder after the ingest silently overwrites
official-derived `sector` and `name` for ~500 companies. The runbook warns about this;
the real fix is to retire the keyword map.

**`_HISTORY_FKS` / `_DERIVABLE_TABLES` in `backfill_universe.py` are hand-maintained.** A
future model adding a foreign key onto `companies.id` would silently orphan rows during a
merge. A test asserting that `Base.metadata` FKs onto `companies.id` are a subset of those
two tuples would make it self-defending.

**`normalize.is_sme` re-declares the SME group set** instead of reading
`sector_map._BSE_SME_GROUPS`; drift would make `listing.is_sme` disagree with
`tradeability == "SME"`.

**`build_records` never re-applies `is_company_isin`**, so a caller bypassing the parsers
could inject an `"NA"` ISIN.

**`normalize` treats any BSE `Status` other than literally `"SUSPENDED"` as active.**
Safer inverted: anything not `"ACTIVE"` becomes `SUSPENDED`. The only current guard is
that our own fetcher pins `status=Active`.

**A BSE `SCRIP_CD` emitted as a JSON float** (`590002.0`) would stringify to `"590002.0"`
and miss a details dict keyed on `"590002"`. The integer case is covered; the float case
is not.

**A blank-`Sector` detail payload** would store `official_industry`/`igroup`/`isubgroup`
without provenance. Unreachable today — `loader._CLASSIFICATION_FIELDS` gates on
`classification_source` — but the write path exists.

**`written += 1` in `_sync_listings` counts entries processed, not rows written**, so two
BSE listings under one ISIN report `listings: 2` while the second overwrites the first.
Reporting accuracy only.

**`_sqlite_savepoint_patched` is keyed on `id(engine)`** and CPython recycles ids. A
`WeakSet` would remove the doubt. No leaking dry run could be produced in practice.

## Coverage gaps

**`USE_ALIAS_MATCHER=false` is untested.** It is the documented rollback lever for the
matcher; one test is cheap insurance.

**`UNIVERSE_MAX_AGE_DAYS` and `CLASSIFICATION_MAX_AGE_DAYS` are declared but read
nowhere.** Spec §6.3 is half implemented: market-cap and AMFI staleness are enforced,
universe and classification staleness are not.

**Only the "no snapshot directory" shape of a missing snapshot is tested**, not "directory
exists but one master file is missing". Same guard clause; verified by hand.

**`compute_cap_tiers`' docstring still says `market_cap_cr`.** Wrong since the unit fix —
`Company.market_cap` is absolute rupees everywhere now. A misleading docstring about the
exact units that caused this branch's one Critical bug is worth a one-word correction.

## Outside this plan's scope

**`app/companies/kite_instruments.py` and `tests/test_companies_api.py` use the numeric
`.BO` form** (`500325.BO`). Probed against live Yahoo: `scrip_id.BO` returns a full series
for all five BSE-only companies tested, while the numeric form returns zero bars for
recently-listed ones (NSDL, SELECTRIC) and partial history for the rest. The numeric form
happens to work for the specific older scrips those files reference, but it is wrong in
general and affects 2,811 BSE-only companies.

**`tests/test_api.py::test_list_alerts_limits_to_the_most_recent_alerts` fails after every
IST midnight.** Pre-existing, unrelated to this branch, verified failing at the branch
base. `/api/alerts` returns only today's IST alerts while the test seeds 205 alerts
staggered backwards from `now`, so the oldest fall into yesterday. It passes during the
day and fails overnight. Worth fixing independently — it will masquerade as branch damage
during any migration run near midnight.

**Curated trade names do not scale.** Three entries now share one shape: news drops
trailing corporate words the registry keeps (`SBI Cards` vs *SBI Cards and Payment
Services*, `Apollo Hospitals` vs *Apollo Hospitals Enterprise*, `SBI Life` vs *SBI Life
Insurance Company*). At 4,967 companies there will be many more, and the general rule that
would catch them automatically was proven unsafe: a token-subset matching rung produced
confident wrong attributions (`Air India` → Tenneco Clean Air India, `Vodafone` → IDEA,
`Suzuki` → Maruti) for 488 of 718 alias tokens. Any future attempt needs a fundamentally
different approach, not a looser threshold.
