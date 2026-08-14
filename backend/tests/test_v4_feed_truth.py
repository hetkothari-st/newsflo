"""Phase 8 (spec §37/§38/§49, INV-012/015): the API serializes fundamental
impact and market reaction as separate truths, and a valid fundamental
analysis is never hidden just because the price feed failed. Legacy mode
keeps the measured-only feed byte-identical."""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_engine
from app.main import app
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow
from app.routers.articles import get_db


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


@pytest.fixture()
def legacy_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", False)


def _seed(db, *, move_status="ok", excess=-2.5, display_tier="primary", gate_state="DISPLAY_ELIGIBLE",
          confidence_band=None, edge_relation=None, causal_directness=None):
    article = Article(source="s", provider="finnhub", url="https://ex.com/a",
                      title="Crude oil spikes on supply shock", content="c",
                      status="ALERTED")
    company = Company(name="MRF", ticker="MRF.NS", sector="auto", index_tier="NIFTY50")
    db.add_all([article, company])
    db.commit()
    alert = Alert(article_id=article.id, category="commodity", event_type="crude_oil")
    db.add(alert)
    db.commit()
    db.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=3.0, rationale="thesis",
        basis="direct_mention", economic_effect="negative",
        display_tier=display_tier, gate_state=gate_state,
        causal_parent_type="economic_node", causal_parent_id="crude_price",
        causal_distance=1, materiality=0.7, mechanism="crude-linked input costs",
        confidence_band=confidence_band, edge_relation=edge_relation,
        causal_directness=causal_directness,
    ))
    db.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        measurement_status=move_status,
        excess_move_pct=excess if move_status == "ok" else None,
        raw_move_pct=excess if move_status == "ok" else None,
        sector_move_pct=0.0 if move_status == "ok" else None,
        measured_at=utcnow(), category="commodity", bar_complete=1,
    ))
    db.commit()
    return alert


def test_strict_unmeasured_alert_still_served_in_list(client, db_session, strict_mode):
    """INV-015 / spec §49: market-data failure must not erase valid
    fundamental analysis."""
    alert = _seed(db_session, move_status="no_data")

    rows = client.get("/api/feed-v2").json()

    assert [r["id"] for r in rows] == [alert.id]
    row = rows[0]
    assert row["excess_move_pct"] is None
    assert row["market_reaction"]["status"] == "unavailable"
    assert row["market_reaction"]["direction"] == "unknown"


@pytest.mark.parametrize("tier", ["secondary_deep_dive", "secondary"])
def test_strict_deep_dive_only_alert_listed_as_indirect_only(client, db_session, strict_mode, tier):
    """Owner decision 2026-08-14 (supersedes the Task 16 hide-the-rest rule
    for the no-primary case): a secondary/deep-dive-only gated alert IS
    served in the main list, labeled exposure="indirect_only" -- here with
    the unavailable-measurement placeholder since nothing measured. Both
    the current tier string and the legacy "secondary" spelling are
    covered (Task 4)."""
    alert = _seed(db_session, move_status="no_data", display_tier=tier)

    rows = client.get("/api/feed-v2").json()

    assert [r["id"] for r in rows] == [alert.id]
    assert rows[0]["exposure"] == "indirect_only"
    assert rows[0]["market_reaction"]["status"] == "unavailable"


def test_strict_excluded_only_alert_is_not_served(client, db_session, strict_mode):
    """Nothing the gate authorized -> nothing to show."""
    _seed(db_session, move_status="no_data", display_tier="excluded")

    assert client.get("/api/feed-v2").json() == []


def test_legacy_mode_gated_unmeasured_alert_still_served(client, db_session, legacy_mode):
    """Corrective-v4 Task 16 (owner ruling): once gate output is persisted
    on a row it is authoritative REGARDLESS of impact_engine_v4_strict --
    same "structural, not modal" discipline Task 12 already applies to
    section rendering. This seed has ALWAYS carried gate_state=
    "DISPLAY_ELIGIBLE" + display_tier="primary" (i.e. gated with a primary
    company), so the pre-Task-16 "stays hidden with the flag off" pin was
    testing "flag off despite gate data present" -- the owner's Task 16
    ruling deliberately INVERTS that combination, same shape as Task 12's
    inversion of section rendering. See
    test_legacy_mode_truly_ungated_alert_stays_hidden below for the actual
    "flag off, no gate data at all" case this test's old name claimed to
    cover."""
    alert = _seed(db_session, move_status="no_data")

    assert [r["id"] for r in client.get("/api/feed-v2").json()] == [alert.id]


def test_legacy_mode_truly_ungated_alert_stays_hidden(client, db_session, legacy_mode):
    """The real "flag off" scenario: an alert with NO gate data at all
    (gate_state AND display_tier both NULL, i.e. is_gated() is False)
    stays hidden when unmeasured -- legacy behavior is untouched by
    Task 16."""
    _seed(db_session, move_status="no_data", display_tier=None, gate_state=None)

    assert client.get("/api/feed-v2").json() == []


def test_strict_detail_serves_unmeasured_alert_with_layers(client, db_session, strict_mode):
    alert = _seed(db_session, move_status="no_data")

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["market_reaction"]["status"] == "unavailable"
    assert len(detail["layers"]) == 1
    assert detail["layers"][0]["icon"] == "lose"  # from economic_effect


def test_legacy_mode_gated_detail_serves_unmeasured_alert(client, db_session, legacy_mode):
    """Same Task 16 inversion as test_legacy_mode_gated_unmeasured_alert_
    still_served above, for the detail route."""
    alert = _seed(db_session, move_status="no_data")

    assert client.get(f"/api/feed-v2/{alert.id}").status_code == 200


def test_legacy_mode_truly_ungated_detail_404s_unmeasured_alert(client, db_session, legacy_mode):
    alert = _seed(db_session, move_status="no_data", display_tier=None, gate_state=None)

    assert client.get(f"/api/feed-v2/{alert.id}").status_code == 404


def test_measured_alert_reaction_object_uses_dead_zone(client, db_session, strict_mode):
    """+0.05% excess is FLAT, not a winner (spec §22)."""
    alert = _seed(db_session, move_status="ok", excess=0.05)

    row = client.get("/api/feed-v2").json()[0]

    assert row["market_reaction"]["status"] == "ok"
    assert row["market_reaction"]["direction"] == "flat"
    assert row["excess_move_pct"] == 0.05  # exact value untouched


def test_strict_rows_carry_fundamental_and_reaction_separately(client, db_session, strict_mode):
    """Apollo case end-to-end: negative fundamental + positive reaction,
    both serialized, neither overwriting the other."""
    alert = _seed(db_session, move_status="ok", excess=+2.1)

    detail = client.get(f"/api/feed-v2/{alert.id}").json()
    row = detail["layers"][0]["rows"][0]

    assert row["economic_effect"] == "negative"
    assert row["display_tier"] == "primary"
    assert row["reaction_direction"] == "positive"
    assert row["excess_move_pct"] == 2.1


# ===========================================================================
# Task 6 -- the five-dimension wire contract (§3/§22/§28, rulings R1/R4)
# ===========================================================================

def test_rows_serve_the_five_dimensions_in_the_new_vocabulary(client, db_session, strict_mode):
    """Every gated ripple-layer row carries the five SEPARATE dimensions the
    blueprint splits apart -- effect, materiality grade, causal directness,
    publication tier and confidence band -- plus the §21 edge relation.
    `causal_directness` is DERIVED by the gate's own resolver here (the row
    carries none), which at d1 with a non-registry parent is DIRECT."""
    alert = _seed(db_session, edge_relation="INPUT_COST", confidence_band="MODERATE")

    row = client.get(f"/api/feed-v2/{alert.id}").json()["layers"][0]["rows"][0]

    assert row["publication_tier"] == "primary"
    assert row["causal_directness"] == "DIRECT"
    assert row["edge_relation"] == "INPUT_COST"
    # Legacy Confidence-Engine vocabulary (LOW|MODERATE|HIGH|VERY_HIGH) is
    # normalized on the way out -- the wire only ever speaks §18's bands.
    assert row["confidence_band"] == "MEDIUM"
    assert row["materiality_grade"] == "HIGH"


def test_explicit_causal_directness_column_wins_over_distance(client, db_session, strict_mode):
    """§11: DIRECT/INDIRECT/REMOTE is NOT a synonym for d1/d2. A row that
    classified its own directness is served verbatim, distance be damned."""
    alert = _seed(db_session, causal_directness="REMOTE")

    row = client.get(f"/api/feed-v2/{alert.id}").json()["layers"][0]["rows"][0]

    assert row["causal_directness"] == "REMOTE"
    assert row["impact_type"] == "direct"          # causal_distance == 1, unchanged


@pytest.mark.parametrize("band,expected", [
    ("VERY_HIGH", "HIGH"), ("HIGH", "HIGH"), ("MODERATE", "MEDIUM"),
    ("MEDIUM", "MEDIUM"), ("LOW", "LOW"), ("UNKNOWN", "UNKNOWN"),
    (None, "UNKNOWN"),
])
def test_confidence_band_vocabulary_is_normalized_on_the_wire(
        client, db_session, strict_mode, band, expected):
    """Ruling R4 + §18: gated rows written by the V4 gate already speak
    HIGH/MEDIUM/LOW/UNKNOWN; rows written before it carry the old engine's
    band. Both leave through one vocabulary, and an absent band is the
    honest UNKNOWN rather than a guess at LOW."""
    alert = _seed(db_session, confidence_band=band)

    row = client.get(f"/api/feed-v2/{alert.id}").json()["layers"][0]["rows"][0]

    assert row["confidence_band"] == expected


@pytest.mark.parametrize("tier", ["secondary_ripple", "secondary_deep_dive", "secondary"])
def test_publication_tier_normalizes_legacy_ripple_spellings(
        client, db_session, strict_mode, tier):
    """T9's binding wire contract: the frontend reads ONE ripple spelling.
    A row persisted under either dead name still serves display_tier
    verbatim (raw truth) but publication_tier canonical."""
    alert = _seed(db_session, display_tier=tier)

    row = client.get(f"/api/feed-v2/{alert.id}").json()["layers"][0]["rows"][0]

    assert row["display_tier"] == tier
    assert row["publication_tier"] == "secondary_ripple"


def test_no_numeric_confidence_score_on_any_feed_v2_payload(client, db_session, strict_mode):
    """Ruling R4: the band is the ONLY confidence this surface shows -- no
    49-for-everyone numeric score anywhere in the list row, the detail
    payload or a deep-dive row (the legacy /api/alerts keeps it for the old
    UI)."""
    alert = _seed(db_session)

    listed = client.get("/api/feed-v2").json()[0]
    detail = client.get(f"/api/feed-v2/{alert.id}").json()
    deep_dive = client.get(f"/api/feed-v2/{alert.id}/deep-dive").json()

    assert "confidence_score" not in listed
    for payload in (detail, deep_dive):
        for key in ("primary", "secondary", "macro", "layers"):
            for layer in payload.get(key) or []:
                for row in layer["rows"]:
                    assert "confidence_score" not in row


def test_ungated_legacy_rows_gain_no_tier_fields(client, db_session, legacy_mode):
    """A legacy row has no tier, no directness and no edge relation; the
    serializer must not invent any of them (its dict stays byte-identical
    to its pre-Task-6 shape)."""
    alert = _seed(db_session, display_tier=None, gate_state=None)

    row = client.get(f"/api/feed-v2/{alert.id}").json()["layers"][0]["rows"][0]

    for key in ("publication_tier", "causal_directness", "edge_relation", "confidence_band"):
        assert key not in row
