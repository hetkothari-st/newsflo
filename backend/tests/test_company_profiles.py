from datetime import date

from app.companies.descriptions import extract, loader
from app.models import Company, CompanyProfile

AS_OF = date(2026, 8, 10)

FULL_EXTRACT = """Lead paragraph about the company, not returned by sections().

== History ==
The company was founded in 1975 as a small trading house.

=== 2020s ===
In 2022 the company commissioned its first green hydrogen plant. The project doubled capacity.

In 2024 it acquired a rival's retail arm for a large sum.

== Products ==
Widgets and services.

== Recent developments ==
In 2025 the company announced a new battery factory expected to open in fiscal 2027.

== References ==
Reflist.
"""


def _page(extract_text: str = FULL_EXTRACT) -> dict:
    return {"title": "Test Company", "revid": 123, "extract": extract_text}


def _company(db_session) -> Company:
    company = Company(ticker="TEST.NS", name="Test Company", sector="other", index_tier="OTHER")
    db_session.add(company)
    db_session.commit()
    return company


def test_sections_split_folds_subsections_into_parent():
    section_map = extract.sections(FULL_EXTRACT)
    assert "history" in section_map
    assert "2022" in section_map["history"]  # === 2020s === folded in
    assert "recent developments" in section_map
    assert "battery factory" in section_map["recent developments"]


def test_recent_paragraphs_drops_old_and_yearless_text():
    paragraphs = extract.recent_paragraphs(
        extract.sections(FULL_EXTRACT)["history"], cutoff_year=2021, max_year=2027,
    )
    joined = " ".join(paragraphs)
    assert "1975" not in joined  # founded-in paragraph is not "recent"
    assert "2022" in joined and "2024" in joined


def test_bounded_text_keeps_the_most_recent_when_over_budget():
    old = "In 2021 an old thing happened. " * 10
    new = "In 2026 the newest thing happened."
    out = extract.bounded_text([old.strip(), new], max_chars=80, hard_chars=120)
    assert out is not None
    assert "2026" in out


def test_apply_profile_writes_both_fields_with_shared_source(db_session):
    company = _company(db_session)
    outcome = loader.apply_profile(db_session, company, _page(), as_of=AS_OF)
    assert outcome == "written"
    profile = db_session.query(CompanyProfile).one()
    assert "2022" in profile.history_text and "1975" not in profile.history_text
    assert "battery factory" in profile.developments_text
    assert profile.source_url.startswith("https://en.wikipedia.org/wiki/")
    assert profile.source_revision_id == 123


def test_apply_profile_never_clobbers_on_empty_rerun(db_session):
    company = _company(db_session)
    loader.apply_profile(db_session, company, _page(), as_of=AS_OF)
    outcome = loader.apply_profile(
        db_session, company, _page("== References ==\nNothing here."), as_of=AS_OF,
    )
    assert outcome == "empty"
    profile = db_session.query(CompanyProfile).one()
    assert profile.history_text is not None  # previous text intact


def test_apply_profile_writes_no_row_when_nothing_qualifies(db_session):
    company = _company(db_session)
    outcome = loader.apply_profile(
        db_session, company, _page("== History ==\nFounded long ago, no year given."), as_of=AS_OF,
    )
    assert outcome == "empty"
    assert db_session.query(CompanyProfile).count() == 0


def test_dossier_endpoint_serves_profile_fields(db_session):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routers.articles import get_db

    company = Company(
        ticker="PRO.NS", name="Profiled Ltd", sector="other", index_tier="OTHER",
        market="INDIA", market_cap=10.0,
    )
    db_session.add(company)
    db_session.commit()
    loader.apply_profile(db_session, company, _page(), as_of=AS_OF)

    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    client = TestClient(app)
    body = client.get("/api/companies/by-ticker/PRO.NS/dossier").json()
    app.dependency_overrides.clear()

    assert "2022" in body["history_text"]
    assert body["history_source_url"].startswith("https://en.wikipedia.org/")
    assert "battery factory" in body["developments_text"]
