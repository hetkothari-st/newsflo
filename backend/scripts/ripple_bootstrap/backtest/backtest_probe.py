"""FEASIBILITY PROBE - can a gross-margin regression recover a KNOWN exposure?

SCRATCH ONLY. Writes nothing to the repo, no migration, nothing to
pass_through_curve. Two companies, both with a filing-sourced crude share
already in the ledger:

  CEAT        input:crude_derivative_rubber + petchem = 0.3100 of materials
              (a FLOOR -- the 53% "Rubber" line merges natural with synthetic)
  Savita Oil  input:base_oil = 0.8608 of materials, near pure-play

If the method cannot recover Savita's 86%, the redirect is dead.

DATA
  quarterly P&L : NSE corporate-filings-financial-results -> Ind-AS XBRL
                  (RevenueFromOperations, CostOfMaterialsConsumed,
                   PurchasesOfStockInTrade, ChangesInInventories...)
  crude         : FRED DCOILBRENTEU (Brent, daily spot, USD/bbl), quarterly mean

THE IDENTITY BEING TESTED
  g = gross-margin ratio = 1 - (materials + purchases + inv change) / revenue
  m = materials-ish cost / revenue          k = total cost / revenue
  s = crude-linked share OF MATERIALS (the filed number)
  phi = pass-through

  A crude move of dlnP raises crude-linked cost by s*m*R*dlnP and revenue by
  phi times that, so

      dg/dlnP  =  -s*m*(1 - phi*k)                      [beta]
      phi      =  (1 + beta/(s*m)) / k                  [implied pass-through]

  phi = 0 gives beta = -s*m. phi = 1 does NOT give beta = 0: passing the whole
  cost increase through preserves the absolute margin but still dilutes the
  RATIO, because the denominator grew. That is the arithmetic the probe leans
  on and it is worth checking by eye.
"""
from __future__ import annotations

import io
import json
import math
import re
import sys
from datetime import date

import numpy as np
import pandas as pd
import requests
from pathlib import Path

SCRATCH = Path(__file__).resolve().parent

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
NSE_REF = ("https://www.nseindia.com/companies-listing/"
           "corporate-filings-financial-results")

# (symbol, basis to match the filed row, filed crude share OF MATERIALS)
TARGETS = [
    ("CEATLTD", "Non-Consolidated", 0.3100, "CEAT (floor: carbon black + "
                                            "chemicals + fabrics / materials)"),
    ("SOTL", "Consolidated", 0.8608, "Savita Oil (base oils / materials)"),
]

FACTS = ("RevenueFromOperations", "CostOfMaterialsConsumed",
         "PurchasesOfStockInTrade",
         "ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade",
         "Expenses", "EmployeeBenefitExpense", "OtherExpenses")


# ---------------------------------------------------------------- t-dist
def _betacf(a, b, x):
    tiny, eps = 1e-30, 3e-16
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        c = 1.0 + aa / c
        if abs(d) < tiny:
            d = tiny
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        c = 1.0 + aa / c
        if abs(d) < tiny:
            d = tiny
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbeta) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbeta) * _betacf(b, a, 1 - x) / b


def t_sf(t, df):
    """two-sided p-value"""
    return betainc(df / 2.0, 0.5, df / (df + t * t))


def t_crit(df, p=0.975):
    """inverse t by bisection -- no scipy in this environment"""
    lo, hi = 0.0, 100.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if 1.0 - t_sf(mid, df) / 2.0 < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- NSE
def nse_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    for u in ("https://www.nseindia.com/", NSE_REF):
        try:
            s.get(u, timeout=25)
        except requests.RequestException:
            pass
    return s


def results_index(s, symbol):
    r = s.get("https://www.nseindia.com/api/corporates-financial-results",
              params={"index": "equities", "symbol": symbol,
                      "period": "Quarterly"},
              headers={"Referer": NSE_REF}, timeout=60)
    r.raise_for_status()
    return r.json()


XBRLI = "{http://www.xbrl.org/2003/instance}"


def parse_xbrl(text, want_start, want_end, allow_convention=False):
    """Facts whose context is EXACTLY the target period and carries no
    dimension. A result XBRL holds the quarter, the prior quarter, the
    year-to-date and the prior year in one document, so taking the first
    match would silently mix periods.

    Uses a real XML parser. The first version of this used regex over
    `<xbrli:context ...>` and SILENTLY LOST 16 of 25 resolvable CEAT files,
    which would have been reported as missing data. It was not missing; the
    parser could not see it. Recorded because that is exactly the kind of
    error that turns a tooling limit into a false finding about the world.
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text.encode("utf-8", "replace"))
    except ET.ParseError:
        return {}
    plain = set()
    for ctx in root.iter(f"{XBRLI}context"):
        period = ctx.find(f"{XBRLI}period")
        if period is None:
            continue
        st = period.findtext(f"{XBRLI}startDate")
        en = period.findtext(f"{XBRLI}endDate")
        if st != want_start or en != want_end:
            continue
        entity = ctx.find(f"{XBRLI}entity")
        if entity is not None and entity.find(f"{XBRLI}segment") is not None:
            continue
        if ctx.find(f"{XBRLI}scenario") is not None:
            continue
        plain.add(ctx.get("id"))

    # CONVENTION FALLBACK. Older NSE result XBRLs reference a context id
    # ("OneD" = current period, standalone; "FourD" = the comparative) that
    # the document NEVER DECLARES. The numbers are there; the period they
    # belong to is not. Reading them means ASSUMING the naming convention
    # observed in the newer files, which is an inference about the document
    # rather than a statement in it. Allowed for a probe, tagged, and never
    # acceptable as ledger provenance.
    assumed = False
    if not plain and allow_convention:
        declared = {c.get("id") for c in root.iter(f"{XBRLI}context")}
        if "OneD" not in declared:
            plain = {"OneD"}
            assumed = True

    out = {}
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag not in FACTS or el.get("contextRef") not in plain:
            continue
        if tag in out:
            continue
        try:
            out[tag] = float((el.text or "").strip())
        except ValueError:
            pass
    if out and assumed:
        out["_context_assumed"] = 1.0
    return out


def quarters_for(s, symbol, basis):
    rows = results_index(s, symbol)
    picked = {}
    for r in rows:
        if r.get("consolidated") != basis:
            continue
        if (r.get("cumulative") or "").lower().startswith("cumulative"):
            continue
        key = (r["fromDate"], r["toDate"])
        # keep the LATEST filing for a period (restatements supersede)
        prev = picked.get(key)
        if prev is None or r["filingDate"] > prev["filingDate"]:
            picked[key] = r
    return picked


def fetch_quarters(s, symbol, basis):
    picked = quarters_for(s, symbol, basis)
    recs = []
    for (fd, td), r in sorted(picked.items(),
                              key=lambda kv: pd.to_datetime(kv[0][1])):
        url = r.get("xbrl")
        if not url:
            recs.append({"from": fd, "to": td, "why": "no xbrl link"})
            continue
        try:
            x = s.get(url, headers={"Referer": "https://www.nseindia.com/"},
                      timeout=60)
        except requests.RequestException as e:
            recs.append({"from": fd, "to": td, "why": f"fetch {e.__class__.__name__}"})
            continue
        if x.status_code != 200:
            recs.append({"from": fd, "to": td, "why": f"http {x.status_code}"})
            continue
        start = pd.to_datetime(fd).strftime("%Y-%m-%d")
        end = pd.to_datetime(td).strftime("%Y-%m-%d")
        facts = parse_xbrl(x.text, start, end)
        recs.append({"from": fd, "to": td, "end": end, "facts": facts,
                     "url": url})
    return recs


# ---------------------------------------------------------------- Brent
def brent_quarterly():
    """Brent, quarterly mean of monthly closes.

    SOURCE NOTE: FRED's DCOILBRENTEU (daily spot, the series a production
    implementation should use) is unreachable from this machine -- curl and
    requests both get the connection reset, repeatably. This probe therefore
    uses Brent FUTURES (BZ=F) monthly closes from the Yahoo chart endpoint,
    which starts 2007-08 and is a coarser instrument than daily spot.
    That is a limitation of the PROBE and is reported as one.

    Invariant 3 note: this is a COMMODITY price used as the regressor. The
    invariant forbids a COMPANY's market price from influencing fundamental
    direction; it does not forbid measuring a fundamental against a commodity
    price, which is the whole point of a sensitivity engine.
    """
    import datetime as dt
    raw = json.loads((SCRATCH / "brent_bzf.json").read_text(encoding="utf-8"))
    res = raw["chart"]["result"][0]
    rows = [(dt.datetime.fromtimestamp(t, dt.timezone.utc).date(), c)
            for t, c in zip(res["timestamp"],
                            res["indicators"]["quote"][0]["close"]) if c]
    df = pd.DataFrame(rows, columns=["date", "brent"])
    df["date"] = pd.to_datetime(df["date"])
    df["q"] = df["date"].dt.to_period("Q")
    return df.groupby("q")["brent"].mean()


# ---------------------------------------------------------------- OLS
def ols(y, X, names):
    n, k = X.shape
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = n - k
    sigma2 = float(resid @ resid) / dof
    XtX_inv = np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(XtX_inv) * sigma2)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / ss_tot if ss_tot else float("nan")
    adj = 1 - (1 - r2) * (n - 1) / dof if dof else float("nan")
    tc = t_crit(dof)
    return {"names": names, "beta": beta, "se": se, "n": n, "dof": dof,
            "r2": r2, "adj_r2": adj, "tcrit": tc,
            "t": beta / se,
            "p": np.array([t_sf(abs(b / s), dof) for b, s in zip(beta, se)]),
            "lo": beta - tc * se, "hi": beta + tc * se}


def show(fit, label):
    print(f"  {label}: n={fit['n']} dof={fit['dof']} "
          f"R2={fit['r2']:.3f} adjR2={fit['adj_r2']:.3f}")
    for i, nm in enumerate(fit["names"]):
        crosses = "CI CROSSES ZERO" if fit["lo"][i] * fit["hi"][i] <= 0 else ""
        print(f"    {nm:<16}{fit['beta'][i]:+.5f}  se={fit['se'][i]:.5f}  "
              f"t={fit['t'][i]:+.2f}  p={fit['p'][i]:.3f}  "
              f"95%CI[{fit['lo'][i]:+.5f},{fit['hi'][i]:+.5f}] {crosses}")


def main():
    brent = brent_quarterly()
    print(f"Brent DCOILBRENTEU quarterly means: {len(brent)} quarters, "
          f"{brent.index[0]} .. {brent.index[-1]}\n")

    s = nse_session()
    for symbol, basis, share, label in TARGETS:
        print("=" * 78)
        print(f"{label}   [{symbol}, {basis}, filed crude share of "
              f"materials = {share}]")
        recs = fetch_quarters(s, symbol, basis)
        listed = len(recs)
        parsed = [r for r in recs if r.get("facts")]
        usable = []
        for r in parsed:
            f = r["facts"]
            rev = f.get("RevenueFromOperations")
            mat = f.get("CostOfMaterialsConsumed")
            if not rev or mat is None:
                continue
            pur = f.get("PurchasesOfStockInTrade", 0.0) or 0.0
            chg = f.get("ChangesInInventoriesOfFinishedGoods"
                        "WorkInProgressAndStockInTrade", 0.0) or 0.0
            tot = f.get("Expenses")
            cogs = mat + pur + chg
            usable.append({
                "end": pd.Timestamp(r["end"]),
                "rev": rev, "mat": mat, "cogs": cogs,
                "gm": 1.0 - cogs / rev,
                "m": mat / rev,
                "k": (tot / rev) if tot else np.nan,
            })
        df = pd.DataFrame(usable).sort_values("end")
        print(f"  quarters listed by NSE (this basis) : {listed}")
        print(f"  XBRL parsed with the target context : {len(parsed)}")
        print(f"  usable (revenue + materials present): {len(df)}")
        if df.empty:
            print("  NOTHING USABLE -- stop.\n")
            continue
        print(f"  span: {df['end'].min().date()} .. {df['end'].max().date()}")

        df["q"] = df["end"].dt.to_period("Q")
        df["brent"] = df["q"].map(brent)
        df = df.dropna(subset=["brent"])
        df["lnb"] = np.log(df["brent"].astype(float))
        print(f"  matched to a Brent quarter          : {len(df)}")

        m_bar = float(df["m"].mean())
        k_bar = float(df["k"].mean(skipna=True))
        print(f"  mean materials/revenue m = {m_bar:.3f}   "
              f"mean total cost/revenue k = {k_bar:.3f}   "
              f"mean gross margin = {df['gm'].mean():.3f}")

        y = df["gm"].to_numpy(float)
        one = np.ones(len(df))

        print("\n  SPEC A - contemporaneous only:  gm ~ const + ln(Brent)")
        fitA = ols(y, np.column_stack([one, df["lnb"]]), ["const", "lnBrent"])
        show(fitA, "A")
        beta = fitA["beta"][1]
        for nm, b in (("point", beta), ("CI lo", fitA["lo"][1]),
                      ("CI hi", fitA["hi"][1])):
            denom = share * m_bar
            phi = (1 + b / denom) / k_bar if denom and k_bar else float("nan")
            print(f"    implied pass-through at {nm:<6} beta={b:+.5f} -> "
                  f"phi = {phi:+.3f}")

        d = df.copy()
        d["lnb1"] = d["lnb"].shift(1)
        d["lnb2"] = d["lnb"].shift(2)
        d = d.dropna(subset=["lnb1", "lnb2"])
        if len(d) > 6:
            print("\n  SPEC B - distributed lag: gm ~ const + lnB + lnB(-1) "
                  "+ lnB(-2)   (this is what a CURVE would come from)")
            fitB = ols(d["gm"].to_numpy(float),
                       np.column_stack([np.ones(len(d)), d["lnb"], d["lnb1"],
                                        d["lnb2"]]),
                       ["const", "lnB(t)", "lnB(t-1)", "lnB(t-2)"])
            show(fitB, "B")
            cum = fitB["beta"][1:].sum()
            print(f"    cumulative 3-quarter beta = {cum:+.5f}")

        print("\n  SPEC C - control for revenue growth (the crudest volume/mix"
              " control)")
        d2 = df.copy()
        d2["gsales"] = np.log(d2["rev"]).diff(4)
        d2 = d2.dropna(subset=["gsales"])
        if len(d2) > 6:
            fitC = ols(d2["gm"].to_numpy(float),
                       np.column_stack([np.ones(len(d2)), d2["lnb"],
                                        d2["gsales"]]),
                       ["const", "lnBrent", "yoy ln rev"])
            show(fitC, "C")
        print()


if __name__ == "__main__":
    main()
