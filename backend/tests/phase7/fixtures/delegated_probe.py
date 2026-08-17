"""A pass and a fail, for testing the DELEGATED-SUITE RUNNER itself.

NOT COLLECTED BY THE SUITE. The filename does not match pytest's
`python_files` pattern (`test_*.py`), so a normal run never sees it; the
delegated-runner tests invoke these two node ids explicitly by path, which
is exactly how the runner invokes a real delegated suite.

WHY A DELIBERATELY FAILING TEST EXISTS IN THIS REPO. `reducer_determinism`
and `market_fundamental_isolation` are shipping gates answered by running a
Phase 0 suite. A runner that could only ever report "the suite passed" is
not a check, it is a formality -- and the Phase 0 suites pass, so nothing in
the real world can currently exercise the failure path. This file is that
path, and `test_a_delegated_gate_fails_when_its_suite_fails` is what proves
the gate can go red.
"""


def test_the_probe_passes():
    assert True


def test_the_probe_fails():
    raise AssertionError(
        "this failure is deliberate: it is the fixture the delegated-suite "
        "runner is pointed at to prove a delegated gate can go red")
