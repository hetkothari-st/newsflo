"""Regression coverage for backend/reanalyze_cascade.py's grounding.

Task 8 made grounding (candidate list + ticker enum) inside analyze_article
conditional on a `session` argument, and this script was deliberately left
alone at the time. As originally written it called
`analyze_article(client, title, content)` with no session -- reanalyzing
completely UNGROUNDED, reproducing the exact pre-fix hallucination behavior
this whole precision effort exists to remove. A test that only checks the
script runs without erroring would not catch that regression (it ran fine
either way) -- this asserts the actual session object reaches
analyze_article's call site.
"""
import reanalyze_cascade
from app.analysis.schemas import AnalysisOutput
from app.models import Alert, Article


def test_main_passes_a_real_session_to_analyze_article(db_session, monkeypatch):
    article = Article(source="test", url="https://example.com/reanalyze-cascade", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    captured = {}

    def fake_analyze_article(client, title, content, session=None):
        captured["session"] = session
        return AnalysisOutput(category="test", companies=[], edges=[], gaps=[])

    # Route the script's module-level singletons at the test's in-memory
    # session/engine instead of a real SessionLocal()/build_client() --
    # main() is not written to accept a session, so it's monkeypatched at
    # the names reanalyze_cascade imported them under.
    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(reanalyze_cascade, "analyze_article", fake_analyze_article)

    reanalyze_cascade.main(limit=5, days=None, force=False)

    assert "session" in captured, "analyze_article was never called"
    assert captured["session"] is not None
    assert captured["session"] is db_session


def test_main_builds_anchor_sub_sectors_before_resolving(db_session, monkeypatch):
    # Guards against a second, hand-rolled copy of the anchor_sub_sectors
    # loop drifting from app.pipeline.build_anchor_sub_sectors -- the exact
    # failure mode called out in the task brief. Asserts the script actually
    # calls the shared helper rather than reimplementing the loop.
    article = Article(source="test", url="https://example.com/reanalyze-cascade-2", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    calls = []
    real_helper = reanalyze_cascade.build_anchor_sub_sectors

    def spy_helper(session, companies):
        calls.append((session, companies))
        return real_helper(session, companies)

    def fake_analyze_article(client, title, content, session=None):
        return AnalysisOutput(category="test", companies=[], edges=[], gaps=[])

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(reanalyze_cascade, "analyze_article", fake_analyze_article)
    monkeypatch.setattr(reanalyze_cascade, "build_anchor_sub_sectors", spy_helper)

    reanalyze_cascade.main(limit=5, days=None, force=False)

    assert len(calls) == 1
    assert calls[0][0] is db_session
