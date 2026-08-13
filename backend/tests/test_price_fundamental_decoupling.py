"""Task 3 (docs/superpowers/sdd/2026-08-13-newsflo-corrective-v4/
task-3-brief.md): market/price data must never influence fundamental
confidence, company persistence, or magnitude.

Specifically:
- compute_confidence (app.reasoning.confidence) takes no price-derived
  input at all -- not calibration hit-rate, not a reasoning/price
  contradiction flag.
- get_calibrated_magnitude (app.calibration.blender) no longer overrides a
  persisted AlertCompany's magnitude_low/high with realized-outcome stats.
- CONFIDENCE_FLOOR (app.pipeline) is no longer applied to a v3/gated entry
  -- the executable publication gate is that entry's sole persistence
  authority. It still applies to legacy (ungated) entries.
- contradiction_note/price_at_analysis/return_1m/return_3m keep being
  computed and persisted as observational market facts on the row; they
  just can no longer change the score, the persistence decision, or the
  magnitude.
"""
import pytest

from app.models import AlertCompany, Article, CalibrationSample, Company
from app.pipeline import CONFIDENCE_FLOOR, _persist_alert
from tests.test_v4_strict_gate_wiring import strict_mode  # noqa: F401  -- reused as a fixture


def test_confidence_engine_has_no_price_inputs():
    import inspect

    from app.reasoning import confidence
    src = inspect.getsource(confidence)
    for banned in ("return_1m", "calibration_hit_rate", "excess_move", "price"):
        assert banned not in src, banned


def test_price_contradiction_cannot_drop_company(db_session, monkeypatch):
    """A company 10+ points over the floor loses ZERO points from a -20%
    1-month return; the row persists, and the score is bit-identical to the
    same evidence with no market snapshot at all."""
    import app.pipeline as pipeline_module
    from app.models import utcnow

    company = Company(ticker="X.NS", name="X Ltd.", sector="other", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    # Pinned so both persists below compute an identical article_age_hours
    # -- the freshness component must not be the thing that makes the
    # scores differ.
    fixed_time = utcnow()

    def _entry():
        return {
            "company_id": company.id, "direction": "bullish",
            "magnitude_low": 1.0, "magnitude_high": 2.0, "rationale": "r",
            "key_points": [], "basis": "direct_mention", "time_horizon": "Short-Term",
            "impact_level": "direct", "reasons": ["Crude spike lifts margins."],
            "evidence_refs": ["RULE_CRUDE_OIL_UP"],
        }

    article_clean = Article(
        source="test", url="https://example.com/no-contradiction", title="t", content="c",
        published_at=fixed_time,
    )
    db_session.add(article_clean)
    db_session.commit()
    monkeypatch.setattr(pipeline_module, "get_or_fetch_financial_snapshot", lambda session, ticker: None)
    baseline_alert = _persist_alert(db_session, article_clean, "other", [_entry()])

    assert len(baseline_alert.companies) == 1
    baseline_ac = baseline_alert.companies[0]
    assert baseline_ac.contradiction_note is None
    # Comfortably clear of the floor, so a real loss (not just floor-vs-not)
    # would be visible below.
    assert baseline_ac.confidence_score >= CONFIDENCE_FLOOR + 10

    article_contradicted = Article(
        source="test", url="https://example.com/contradiction", title="t", content="c",
        published_at=fixed_time,
    )
    db_session.add(article_contradicted)
    db_session.commit()
    monkeypatch.setattr(
        pipeline_module, "get_or_fetch_financial_snapshot",
        lambda session, ticker: {"price": 100.0, "return_1m": -20.0, "return_3m": -25.0},
    )
    contradicted_alert = _persist_alert(db_session, article_contradicted, "other", [_entry()])

    assert len(contradicted_alert.companies) == 1
    contradicted_ac = contradicted_alert.companies[0]
    # The observation IS recorded...
    assert contradicted_ac.contradiction_note is not None
    assert "bullish" in contradicted_ac.contradiction_note.lower()
    assert contradicted_ac.return_1m == -20.0
    # ...but costs the row nothing: same score, same persistence outcome.
    assert contradicted_ac.confidence_score == baseline_ac.confidence_score


def test_calibration_never_overwrites_magnitude(db_session):
    """5+ CalibrationSamples for (category, company) exist -- enough to have
    triggered app.calibration.blender.get_calibrated_magnitude's blend under
    the old, now-removed path -- but the persisted magnitude must still
    equal the deterministic impact_strength formula, not the sample stats."""
    company = Company(ticker="Y.NS", name="Y Ltd.", sector="other", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    # 5 samples of a constant 10.0 -> mean=10.0, pstdev=0 -> blend (10.0, 10.0)
    # under the removed path. Constant (not spread) so any accidental
    # blending is unambiguous in the assertion below, not hidden in a range.
    for i in range(5):
        db_session.add(CalibrationSample(
            alert_company_id=i + 1, category="other", company_id=company.id,
            direction="bullish", magnitude_actual=10.0, horizon_days=1,
        ))
    db_session.commit()

    article = Article(source="test", url="https://example.com/calib-magnitude", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    impact_strength = 0.6
    magnitude_high = round(0.5 + 4.5 * impact_strength, 1)
    magnitude_low = round(max(0.1, magnitude_high / 3), 1)

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": magnitude_low, "magnitude_high": magnitude_high,
        "rationale": "r", "key_points": [], "basis": "direct_mention",
        "time_horizon": "Short-Term", "impact_level": "direct",
        "impact_strength": impact_strength,
    }])

    assert len(alert.companies) == 1
    ac = alert.companies[0]
    assert ac.magnitude_low == pytest.approx(magnitude_low)
    assert ac.magnitude_high == pytest.approx(magnitude_high)
    # Not the calibration blend's (10.0, 10.0).
    assert ac.magnitude_low != pytest.approx(10.0)
    assert ac.magnitude_high != pytest.approx(10.0)


def test_gate_output_is_sole_persistence_authority(db_session, strict_mode, monkeypatch):
    """A DISPLAY_ELIGIBLE v3 entry persists even with a rock-bottom
    fundamental confidence_score -- CONFIDENCE_FLOOR must not be re-applied
    on top of a gate decision that already ruled the company in."""
    import app.pipeline as pipeline_module
    from app.reasoning.confidence import ConfidenceResult
    from tests.test_v4_strict_gate_wiring import _company_row, _graph_company, _persist, _result

    _company_row(db_session, verified_node="crude_price")

    monkeypatch.setattr(
        pipeline_module, "compute_confidence",
        lambda **kwargs: ConfidenceResult(score=0, band="LOW"),
    )

    alert = _persist(db_session, _result([_graph_company()]))

    rows = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert len(rows) == 1
    # A bare CompanyNodeExposure row is a Tier-D prior (corrective-v4 Task
    # 5), not primary-authorizing evidence -- secondary_deep_dive is the
    # gate's honest tier here. The point of this test is that it persisted
    # AT ALL (rows[0].confidence_score below) despite a zero score, not
    # which tier it landed on.
    assert rows[0].display_tier == "secondary_deep_dive"
    assert rows[0].gate_state == "DISPLAY_ELIGIBLE"
    # confidence_score is 0 -- well under CONFIDENCE_FLOOR -- and the row
    # still persisted: proof the gate, not the floor, decided this.
    assert rows[0].confidence_score == 0
    assert rows[0].confidence_score < CONFIDENCE_FLOOR
