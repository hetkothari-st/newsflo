"""Back-test runner. SCRATCH ONLY -- writes nothing anywhere.

Runs the probe at both sample depths so the difference is visible:
  STRICT    only quarters whose XBRL declares the context its facts point at
  RELAXED   plus quarters where the facts reference an UNDECLARED context id
            ("OneD"), read under the naming convention observed in the newer
            files. An assumption about the document, not a statement in it.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backtest_probe import (  # noqa: E402
    brent_quarterly, nse_session, ols, parse_xbrl, quarters_for, show,
)

TARGETS = [
    ("CEATLTD", "Non-Consolidated", 0.3100,
     "CEAT -- filed share 0.3100 of materials (a FLOOR: carbon black + "
     "chemicals + fabrics; the 53% 'Rubber' line is excluded because it "
     "merges natural with synthetic)"),
    ("SOTL", "Non-Consolidated", 0.8608,
     "Savita Oil STANDALONE -- filed share 0.8608 of materials (base oils). "
     "NOTE: the ledger row is CONSOLIDATED; standalone is used here only "
     "because it has more history"),
    ("SOTL", "Consolidated", 0.8608,
     "Savita Oil CONSOLIDATED -- the basis the ledger row actually uses"),
]


def collect(s, symbol, basis, brent, allow_convention):
    picked = quarters_for(s, symbol, basis)
    rows = []
    for k in sorted(picked, key=lambda kv: pd.to_datetime(kv[1])):
        try:
            x = s.get(picked[k]["xbrl"],
                      headers={"Referer": "https://www.nseindia.com/"},
                      timeout=45)
        except Exception:
            continue
        if x.status_code != 200:
            continue
        st = pd.to_datetime(k[0]).strftime("%Y-%m-%d")
        en = pd.to_datetime(k[1]).strftime("%Y-%m-%d")
        f = parse_xbrl(x.text, st, en, allow_convention=allow_convention)
        rev = f.get("RevenueFromOperations")
        mat = f.get("CostOfMaterialsConsumed")
        if not rev or mat is None:
            continue
        pur = f.get("PurchasesOfStockInTrade", 0.0) or 0.0
        chg = f.get("ChangesInInventoriesOfFinishedGoodsWorkInProgress"
                    "AndStockInTrade", 0.0) or 0.0
        tot = f.get("Expenses")
        cogs = mat + pur + chg
        rows.append({"end": pd.Timestamp(en), "rev": rev, "mat": mat,
                     "cogs": cogs, "gm": 1.0 - cogs / rev, "m": mat / rev,
                     "k": (tot / rev) if tot else np.nan,
                     "assumed": bool(f.get("_context_assumed"))})
    df = pd.DataFrame(rows).sort_values("end").drop_duplicates("end")
    if df.empty:
        return df
    df["q"] = df["end"].dt.to_period("Q")
    df["brent"] = df["q"].map(brent)
    df = df.dropna(subset=["brent"])
    df["lnb"] = np.log(df["brent"].astype(float))
    return df


def implied_phi(beta, share, m_bar, k_bar):
    denom = share * m_bar
    if not denom or not k_bar or np.isnan(k_bar):
        return float("nan")
    return (1 + beta / denom) / k_bar


def run(df, share, label):
    if len(df) < 6:
        print(f"    too few quarters to fit ({len(df)}) -- not fitted")
        return
    m_bar = float(df["m"].mean())
    k_bar = float(df["k"].mean(skipna=True))
    print(f"    n={len(df)}  span {df['end'].min().date()} .. "
          f"{df['end'].max().date()}  "
          f"({int(df['assumed'].sum())} of them context-assumed)")
    print(f"    mean materials/revenue m={m_bar:.3f}  "
          f"total cost/revenue k={k_bar:.3f}  mean GM={df['gm'].mean():.3f}  "
          f"GM sd={df['gm'].std():.3f}")
    y = df["gm"].to_numpy(float)
    one = np.ones(len(df))

    print("\n    SPEC A  gm ~ const + ln(Brent)")
    A = ols(y, np.column_stack([one, df["lnb"]]), ["const", "lnBrent"])
    show(A, "A")
    b, lo, hi = A["beta"][1], A["lo"][1], A["hi"][1]
    print(f"      implied pass-through phi: point={implied_phi(b, share, m_bar, k_bar):+.3f}"
          f"  CIlo={implied_phi(lo, share, m_bar, k_bar):+.3f}"
          f"  CIhi={implied_phi(hi, share, m_bar, k_bar):+.3f}")
    print(f"      beta implied by the FILED share at phi=0: "
          f"{-share * m_bar:+.5f}   (observed {b:+.5f})")

    d = df.copy()
    d["lnb1"] = d["lnb"].shift(1)
    d["lnb2"] = d["lnb"].shift(2)
    d = d.dropna(subset=["lnb1", "lnb2"])
    if len(d) >= 10:
        print("\n    SPEC B  distributed lag (this is what a CURVE would "
              "come from)")
        B = ols(d["gm"].to_numpy(float),
                np.column_stack([np.ones(len(d)), d["lnb"], d["lnb1"],
                                 d["lnb2"]]),
                ["const", "lnB(t)", "lnB(t-1)", "lnB(t-2)"])
        show(B, "B")
        print(f"      cumulative 3-quarter beta = {B['beta'][1:].sum():+.5f}")

    d2 = df.copy()
    d2["gsales"] = np.log(d2["rev"]).diff(4)
    d2 = d2.dropna(subset=["gsales"])
    if len(d2) >= 10:
        print("\n    SPEC C  + yoy log revenue (crudest volume/mix control)")
        C = ols(d2["gm"].to_numpy(float),
                np.column_stack([np.ones(len(d2)), d2["lnb"], d2["gsales"]]),
                ["const", "lnBrent", "yoy ln rev"])
        show(C, "C")

    d3 = df.copy()
    d3["dgm"] = d3["gm"].diff()
    d3["dlnb"] = d3["lnb"].diff()
    d3 = d3.dropna(subset=["dgm", "dlnb"])
    if len(d3) >= 10:
        print("\n    SPEC D  first differences (kills the level trend / "
              "spurious-regression risk)")
        D = ols(d3["dgm"].to_numpy(float),
                np.column_stack([np.ones(len(d3)), d3["dlnb"]]),
                ["const", "d lnBrent"])
        show(D, "D")
        bd = D["beta"][1]
        print(f"      implied phi from the differenced beta: "
              f"{implied_phi(bd, share, m_bar, k_bar):+.3f}")


def main():
    brent = brent_quarterly()
    print(f"Brent (BZ=F monthly closes -> quarterly mean): {len(brent)} "
          f"quarters, {brent.index[0]} .. {brent.index[-1]}")
    s = nse_session()
    for symbol, basis, share, label in TARGETS:
        print("\n" + "=" * 78)
        print(label)
        for mode in (False, True):
            name = "RELAXED (convention-assumed contexts included)" if mode \
                else "STRICT (declared contexts only)"
            df = collect(s, symbol, basis, brent, mode)
            print(f"\n  -- {name}: {len(df)} usable quarters")
            if not df.empty:
                run(df, share, label)


if __name__ == "__main__":
    main()
