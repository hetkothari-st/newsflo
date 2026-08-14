"""Task 7 (final blueprint §26): gated V4 AlertCompany rows must be immune
to every refinement/legacy writer, and a boot-time schema-version check
must refuse to start the scheduler against a database CONFIRMED behind the
running code's alembic head.

Regression coverage for the real incident this closes: alert 20 (OIL.NS)
-- a stale pre-V4 worker's refinement sweep mutated an already-gated row
after persist, flipping `direction` and nulling `rationale`. A DB trigger
backstop (separate task) is belt; this file is suspenders at the code
layer -- app.analysis.refinement.refine_alert (per-company `why`) and the
boot check that keeps a stale binary from ever running the scheduler loop
that calls it.
"""
import json

from app.analysis.refinement import refine_alert
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow


def _company(ticker="OIL.NS"):
    return Company(ticker=ticker, name=f"Company {ticker}", sector="oil_gas",
                   index_tier="NIFTY50", market_cap=1.0)


def _article(db_session, title="Oil prices surge on supply disruption"):
    article = Article(source="test", url=f"https://example.com/{title}",
                       title=title, content="crude oil markets react")
    db_session.add(article)
    db_session.commit()
    return article


def _snapshot(ac: AlertCompany) -> dict:
    """Every column on the row, read generically off the mapped table --
    so this test keeps protecting every field even if a future migration
    adds another one, rather than only the ones named in the brief."""
    return {c.name: getattr(ac, c.name) for c in AlertCompany.__table__.columns}


def _raise_if_called(name):
    def _inner(*args, **kwargs):
        raise AssertionError(
            f"legacy {name} must never run for a gated alert (blueprint "
            "§26: gated V4 rows cannot be mutated by legacy refinement)"
        )
    return _inner


# --- refine_alert: gated-row immunity -------------------------------------

def test_refine_alert_leaves_a_gated_row_byte_identical(db_session, monkeypatch):
    """The exact shape of the real incident: a company row already decided
    by the V4 publication gate (gate_state IS NOT NULL) must come out of
    refine_alert with EVERY field byte-identical -- direction, rationale,
    basis, key_points_json, and every confidence field included. Also
    proves the legacy per-company `why` generator and the legacy
    ripple-section generator are never even invoked for a gated alert."""
    import app.analysis.refinement as refinement_module

    monkeypatch.setattr(refinement_module, "generate_impact_whys",
                         _raise_if_called("generate_impact_whys"))
    monkeypatch.setattr(refinement_module, "generate_ripple_layers",
                         _raise_if_called("generate_ripple_layers"))

    company = _company()
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=3.0, rationale="Gate-authored rationale",
        key_points_json=json.dumps(["Gate point"]), basis="direct_mention",
        confidence_score=72, confidence_band="HIGH", why="Prior gate-authored why",
        gate_state="DISPLAY_ELIGIBLE", display_tier=None,  # gate_state ALONE must be enough
        mechanism=None,  # nothing legitimate left for refine_alert to (re)populate
    )
    db_session.add(ac)
    move = MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-3.1, measurement_status="ok", measured_at=utcnow(),
    )
    db_session.add(move)
    db_session.commit()

    before = _snapshot(ac)

    refine_alert(object(), db_session, alert, article, [ac], [move])

    after = _snapshot(ac)
    assert after == before, "refine_alert mutated a gated AlertCompany row"


def test_refine_alert_populates_why_from_a_gated_rows_own_vetted_mechanism(db_session):
    """Positive control for the test above: the guard must distinguish
    LEGACY market-move rationalization (blocked) from the V4-native
    population of `why` from a row's own gate-vetted mechanism (still
    authorized, spec §32/INV-014) -- otherwise the byte-identical test
    would pass vacuously because refine_alert never writes anything to a
    gated row at all."""
    company = _company()
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=3.0, rationale=None, basis="direct_mention",
        gate_state="DISPLAY_ELIGIBLE", display_tier="primary",
        mechanism="Falling crude narrows refining margins for this company.",
    )
    db_session.add(ac)
    move = MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-3.1, measurement_status="ok", measured_at=utcnow(),
    )
    db_session.add(move)
    db_session.commit()

    refine_alert(object(), db_session, alert, article, [ac], [move])

    assert ac.why == "Falling crude narrows refining margins for this company."


def test_refine_alert_still_refines_an_ungated_legacy_row(db_session, monkeypatch):
    """The guard must not accidentally freeze OUT legitimate refinement of
    an ungated (pre-V4 / flag-off) row -- gate_state/display_tier NULL is
    the historical shape every pre-v4 alert has, and it must keep getting
    its `why` computed via the legacy path."""
    import app.analysis.refinement as refinement_module

    monkeypatch.setattr(
        refinement_module, "generate_impact_whys",
        lambda client, title, facts, companies: {c["ticker"]: "Legacy mechanism text" for c in companies},
    )

    company = _company()
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=3.0, rationale="r", basis="direct_mention",
        gate_state=None, display_tier=None,
    )
    db_session.add(ac)
    move = MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    )
    db_session.add(move)
    db_session.commit()

    refine_alert(object(), db_session, alert, article, [ac], [move])

    assert ac.why == "Legacy mechanism text"


# --- boot-time schema-version fail-fast -----------------------------------

def _real_alembic_heads():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    import app.main as main_module

    backend_dir = Path(main_module.__file__).resolve().parents[1]
    script = ScriptDirectory.from_config(Config(str(backend_dir / "alembic.ini")))
    return set(script.get_heads())


def test_schema_version_status_true_when_db_is_at_head(monkeypatch):
    from sqlalchemy import create_engine, text

    import app.main as main_module

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        for head in _real_alembic_heads():
            conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": head})
    monkeypatch.setattr("app.db.engine", engine)

    assert main_module._schema_version_status() is True


def test_schema_version_status_false_when_db_is_behind(monkeypatch):
    """The exact stale-binary shape: alembic_version exists but names a
    revision that is not the code's head -- a DEFINITE mismatch."""
    from sqlalchemy import create_engine, text

    import app.main as main_module

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0001_baseline')"))
    monkeypatch.setattr("app.db.engine", engine)

    assert main_module._schema_version_status() is False


def test_schema_version_status_none_when_undeterminable(monkeypatch):
    """No alembic_version table at all (a bare pre-Alembic dev DB) must
    read as unknown, not as "behind" -- it must never by itself block
    anything (see _maybe_start_scheduler)."""
    from sqlalchemy import create_engine

    import app.main as main_module

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    monkeypatch.setattr("app.db.engine", engine)

    assert main_module._schema_version_status() is None


def test_maybe_start_scheduler_refuses_when_schema_is_confirmed_behind(monkeypatch, caplog):
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings, "enable_scheduler", True)
    monkeypatch.setattr(main_module, "_schema_version_status", lambda: False)
    calls = []
    monkeypatch.setattr(main_module, "start_scheduler", lambda: calls.append(True))

    with caplog.at_level("CRITICAL"):
        main_module._maybe_start_scheduler()

    assert calls == [], "scheduler must not start against a schema confirmed behind head"
    assert "REFUSING to start scheduler" in caplog.text


def test_maybe_start_scheduler_starts_when_schema_is_at_head(monkeypatch):
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings, "enable_scheduler", True)
    monkeypatch.setattr(main_module, "_schema_version_status", lambda: True)
    calls = []
    monkeypatch.setattr(main_module, "start_scheduler", lambda: calls.append(True))

    main_module._maybe_start_scheduler()

    assert calls == [True]


def test_maybe_start_scheduler_starts_when_schema_status_is_undeterminable(monkeypatch):
    """None ("could not verify") must not block startup -- only a
    CONFIRMED mismatch does; an undeterminable check must never itself be
    the reason the scheduler cannot start."""
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings, "enable_scheduler", True)
    monkeypatch.setattr(main_module, "_schema_version_status", lambda: None)
    calls = []
    monkeypatch.setattr(main_module, "start_scheduler", lambda: calls.append(True))

    main_module._maybe_start_scheduler()

    assert calls == [True]


def test_maybe_start_scheduler_noop_when_scheduler_disabled(monkeypatch):
    """The schema check must never itself flip ENABLE_SCHEDULER on --
    it can only veto, never authorize."""
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings, "enable_scheduler", False)
    monkeypatch.setattr(main_module, "_schema_version_status", lambda: False)
    calls = []
    monkeypatch.setattr(main_module, "start_scheduler", lambda: calls.append(True))

    main_module._maybe_start_scheduler()

    assert calls == []
