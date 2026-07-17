"""One-off backfill: remap every Alert/Article/CalibrationSample row whose
`category` is not one of app.analysis.schemas.CATEGORIES onto the fixed
taxonomy -- both the renamed legacy short tags (oil_energy -> oil_gas,
auto_ev -> auto, tech -> it) from before CATEGORIES existed, and any
genuinely free-text value the LLM emitted back when `category` had no
enum/tool-schema constraint (e.g. a full sentence used as a "category",
which broke the feed card's badge layout -- see the fix in
app/analysis/claude_client.py's RECORD_ANALYSIS_TOOL).

CalibrationSample.category is remapped too, not just cosmetic: it's an
exact-match lookup key in app.calibration.blender (get_calibrated_magnitude/
get_calibration_health), so leaving old samples on the old taxonomy would
silently orphan them from every future alert's calibration lookup, once
new alerts start using the new category names.

The old->new mapping is a best-effort keyword heuristic for genuinely
free-text values -- good enough for one-time legacy cleanup, not something
new alerts will ever need again now that `category` is enum-constrained at
generation time.

Not part of the test suite and not imported by the app. Safe to re-run --
only touches rows whose category isn't already a valid CATEGORIES value.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python backfill_categories.py
"""
from app.analysis.schemas import CATEGORIES
from app.db import SessionLocal, init_db
from app.models import Alert, Article, CalibrationSample

# Exact renames for the short tags used before CATEGORIES existed --
# checked before the keyword heuristic so these never get re-guessed.
EXACT_RENAMES = {
    "oil_energy": "oil_gas",
    "auto_ev": "auto",
    "tech": "it",
}

# (new_category, keywords) -- first match wins, checked in this order, so
# more specific buckets are listed before generic ones like market_commentary.
KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("oil_gas", ["oil", "crude", "petroleum", "energy", " gas "]),
    ("banking", ["bank", "nbfc", "credit", "loan", "lender"]),
    ("auto", ["auto", " ev ", "vehicle", "two-wheeler"]),
    ("it", [" it ", "tech", "software", "outsourc"]),
    ("pharma", ["pharma", "drug", "healthcare", "hospital"]),
    ("fmcg", ["fmcg", "consumer goods", "staples"]),
    ("metals", ["metal", "mining", "steel", "aluminium", "aluminum"]),
    ("telecom", ["telecom", "spectrum", "5g"]),
    ("infra", ["infra", "construction", "real estate", "realty"]),
    ("macro_policy", ["rbi", "repo rate", "inflation", "rupee", "currency", "fiscal", "budget", "treasury", "interest rate"]),
    ("geopolitics", ["geopolit", "war", "sanction", "tariff", "election"]),
    ("corporate_event", ["ipo", "merger", "acquisition", "stake", "buyback", "listing", "results", "earnings", "q1", "q2", "q3", "q4", "profit", "quarterly"]),
    ("market_commentary", ["market", "nifty", "sensex", "stocks to watch", "ahead of"]),
]


def _reclassify(old: str) -> str:
    if old in CATEGORIES:
        return old
    if old in EXACT_RENAMES:
        return EXACT_RENAMES[old]
    lowered = f" {old.lower()} "
    for new_category, keywords in KEYWORD_RULES:
        if any(keyword in lowered for keyword in keywords):
            return new_category
    return "other"


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        old_categories = {
            row[0] for row in session.query(Alert.category).distinct().all()
            if row[0] not in CATEGORIES
        }
        if not old_categories:
            print("Nothing to backfill -- every Alert.category is already in CATEGORIES.")
            return

        for old in sorted(old_categories):
            new = _reclassify(old)
            alerts_updated = session.query(Alert).filter(Alert.category == old).update({"category": new})
            articles_updated = session.query(Article).filter(Article.category == old).update({"category": new})
            samples_updated = (
                session.query(CalibrationSample)
                .filter(CalibrationSample.category == old)
                .update({"category": new})
            )
            session.commit()
            print(
                f"{old!r} -> {new!r}: {alerts_updated} alert(s), {articles_updated} article(s), "
                f"{samples_updated} calibration sample(s)"
            )
    finally:
        session.close()

    print("Backfill complete.")


if __name__ == "__main__":
    main()
