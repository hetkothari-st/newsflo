"""Proves the structural network guard added in conftest.py (provider-
migration Task 7, full-offline-verification).

conftest.py's autouse `_no_real_anthropic_client` fixture replaces
`anthropic.Anthropic` with a raising stub for the whole test session. This
file proves both directions named in the Task 3 review pointer:

1. the legitimate path -- a test that correctly injects a fake `client=` --
   is completely unaffected by the guard;
2. the path the guard exists to catch -- a test that (by mistake) lets
   ClaudeJSONClient build its own SDK client -- fails immediately and
   loudly, at construction time, instead of attempting a real HTTPS call.
"""
import pytest

from app.analysis.impact_graph.claude_json import ClaudeJSONClient


class _Usage:
    input_tokens = 1
    output_tokens = 1
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _ToolUse:
    type = "tool_use"
    name = "emit"
    input = {"ok": True}


class _Response:
    stop_reason = "tool_use"
    content = [_ToolUse()]
    usage = _Usage()
    model = "claude-opus-5"


class _FakeMessages:
    def create(self, **kwargs):
        return _Response()


class _FakeClient:
    messages = _FakeMessages()


def test_injected_fake_client_is_unaffected_by_the_guard():
    """The guard must never fire for the legitimate, already-established
    pattern used by every other test in this suite: injecting a fake
    `client=` at construction so `_sdk()` never touches `anthropic.Anthropic`
    at all."""
    client = ClaudeJSONClient("test-key", client=_FakeClient())
    out = client.generate(model="claude-opus-5", schema={"type": "object"},
                          static_prefix="RULES", dynamic_suffix="FACTS",
                          stage="map_companies")
    assert out == {"ok": True}


def test_missing_fake_client_fails_closed_instead_of_reaching_the_network():
    """The exact mistake the guard defends against: a test constructs
    ClaudeJSONClient with no `client=` kwarg, so a real call would build a
    real `anthropic.Anthropic()` inside `_sdk()`. The guard must intercept
    that construction and raise immediately -- proving no test in this
    repo can ever reach api.anthropic.com even if it forgets to mock."""
    client = ClaudeJSONClient("test-key")  # no `client=` -- the bug this guards against
    with pytest.raises(AssertionError, match="anthropic.Anthropic"):
        client.generate(model="claude-opus-5", schema={"type": "object"},
                        static_prefix="RULES", dynamic_suffix="FACTS",
                        stage="map_companies")


# --- spec section 16 case 20: live scheduler remains disabled ------------
#
# The guard above proves no TEST reaches Anthropic. These prove the other
# half: the migration did not quietly turn on the unattended path that would
# spend real money on real articles. Two independent gates carry that, and
# both must keep holding -- ENABLE_SCHEDULER (nothing runs at all) and
# ANALYSIS_PAUSED (jobs run, the analysis cycle does not).

def test_scheduler_start_is_guarded_by_enable_scheduler():
    """`start_scheduler()` in app/main.py must be reachable only under
    `if settings.enable_scheduler:`. An unconditional call -- the exact
    "somebody enabled live mode" regression -- fails here."""
    import ast
    import pathlib

    import app.main as main_module

    source = pathlib.Path(main_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    def _is_enable_scheduler_test(node):
        return (isinstance(node, ast.Attribute) and node.attr == "enable_scheduler"
                and isinstance(node.value, ast.Name) and node.value.id == "settings")

    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_enable_scheduler_test(node.test):
            for inner in ast.walk(node):
                guarded.add(id(inner))

    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "start_scheduler"]
    assert calls, "start_scheduler() call not found in app/main.py -- test is stale"
    for call in calls:
        assert id(call) in guarded, "start_scheduler() is called outside the ENABLE_SCHEDULER guard"


def test_analysis_cycle_is_skipped_while_analysis_paused(monkeypatch):
    """ANALYSIS_PAUSED must short-circuit BEFORE any provider client is
    built -- with the flag on, not one Claude call can leave the scheduler."""
    from app import scheduler
    from app.config import settings

    def _boom(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("analysis ran while ANALYSIS_PAUSED was set")

    monkeypatch.setattr(settings, "analysis_paused", True)
    monkeypatch.setattr(scheduler, "build_client", _boom)
    monkeypatch.setattr(scheduler, "process_new_articles", _boom)
    monkeypatch.setattr(scheduler, "SessionLocal", _boom)

    scheduler._run_ingestion_and_analysis()  # returns cleanly: gate consulted
    scheduler._run_analysis_retry()          # the second enforcement point


def test_the_pause_gate_is_what_stops_it(monkeypatch):
    """Positive control, so the test above cannot pass vacuously: with the
    flag OFF the very same call DOES reach the pipeline. If someone deletes
    the `if settings.analysis_paused` check, the paused test starts failing
    -- it is not merely asserting that a no-op does nothing."""
    from app import scheduler
    from app.config import settings

    reached = []

    monkeypatch.setattr(settings, "analysis_paused", False)
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: type(
        "_S", (), {"close": lambda self: None})())
    monkeypatch.setattr(scheduler, "build_client", lambda *a, **kw: object())
    monkeypatch.setattr(scheduler, "process_new_articles",
                        lambda *a, **kw: reached.append(True) or 0)

    scheduler._run_ingestion_and_analysis()
    assert reached == [True]
