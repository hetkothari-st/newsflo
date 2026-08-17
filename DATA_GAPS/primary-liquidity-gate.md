# DATA GAPS — The PRIMARY liquidity gate

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

## 12. The PRIMARY liquidity gate is unenforced — OPEN, **blocker on PRIMARY cutover**

`backend/config/gates.yaml` sets `primary.min_adv_inr: null` and
`primary.unknown_liquidity_passes: true`. Together those mean the spec's
PRIMARY liquidity rule **is not evaluated for any company, ever**. Not
"evaluated leniently" — not walked at all. Every company in the universe
clears the liquidity bar today, including a ₹28cr shell that trades a few
thousand rupees a day.

This was recorded in §3 as one row in a table of four unwired gate inputs,
alongside three whose owner is "a later V5 phase". That framing is wrong for
this one and it is promoted here for two reasons:

1. **It is acquisition work, not phase work.** Phases 2 and 5 do not produce
   an ADV series as a by-product of anything. Somebody has to obtain a daily
   traded-value feed.
2. **It is the only one of the four whose absence lets a *wrong company* be
   published rather than a *weakly-evidenced claim*.** A PRIMARY call on an
   illiquid microcap is unactionable regardless of how good the exposure
   evidence behind it is.

| | |
|---|---|
| **Config** | `backend/config/gates.yaml` → `primary.min_adv_inr` (null), `primary.unknown_liquidity_passes` (true) |
| **Interface** | the gate already accepts `adv_20d_inr`; nothing supplies it |
| **What is needed** | 20-day average traded value in INR per listed company, refreshed daily, for the whole universe — plus a threshold value for `min_adv_inr`, which is a policy decision, not a measurement |
| **Where it comes from** | exchange bhavcopy (NSE + BSE) aggregated to a rolling 20-day mean of `close × volume`, or a licensed EOD feed. `market_moves.avg_traded_value` is NOT this: 48 alert-scoped rows, no universe coverage, no schedule |
| **Who must supply it** | **repo owner** — the feed and the threshold |
| **Blocks** | PRIMARY cutover. Both keys must be set (a real `min_adv_inr`, `unknown_liquidity_passes: false`) in the same change that serves V5 — see item 5 of the cutover checklist |

**Consequence for work done before it closes:** any company-selection step
that was supposed to filter on ADV cannot, and must say so. The Phase 1
ripple-exposure bootstrap substituted a **disclosed market-cap floor of
₹1,500cr** as an owner-approved proxy. A market-cap floor is not a liquidity
filter — a large-cap can be tightly held and thinly traded, and the proxy has
no bearing on the gate at runtime. It is a sampling convenience for one
manual exercise and must not be read as this gap being partially closed.
