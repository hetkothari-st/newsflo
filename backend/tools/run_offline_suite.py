"""The safe offline command set (corrective-v4 Task 21, spec §62).

One sequential runner for everything that can be verified WITHOUT a live
model, a network connection, or the real database:

    1. schema        -- `alembic upgrade head` on a throwaway DB, then a
                        model-vs-migrated-schema comparison (validate_schema)
    2. unit          -- the full pytest suite
    3. invariants    -- tests/test_v4_invariants.py
    4. bypasses      -- tests/test_audit_bypasses.py
    5. regression    -- tools/offline_benchmark.py over the labeled corpus
    6. audit_report  -- tools/generate_audit_report.py against a seeded
                        throwaway alert

Each step prints PASS or FAIL with its duration; the runner exits non-zero
if ANY step failed. Steps 3 and 4 also run inside step 2 -- they are listed
separately because the spec's command set names them separately and because
a failure there deserves its own line rather than being buried in a
1,500-test summary.

Safety contract, enforced structurally rather than by convention:

* every subprocess gets ``DATABASE_URL`` pointed at a file inside a
  temporary directory, so ``backend/newsflo.db`` is never opened;
* ``IMPACT_ENGINE_V4_STRICT`` is never exported -- the benchmark flips the
  setting in-process for its own shadow evaluation and restores it, and
  nothing here enables strict mode for any deployed surface;
* no step makes an LLM call or a network request.

Usage::

    python tools/run_offline_suite.py
    python tools/run_offline_suite.py --skip unit        # iterate faster
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

STEPS = ("schema", "unit", "invariants", "bypasses", "regression", "audit_report")


def _run(command: list[str], env: dict, timeout: int = 3600) -> tuple[bool, str]:
    result = subprocess.run(command, cwd=_BACKEND_DIR, env=env,
                            capture_output=True, text=True, timeout=timeout)
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output


def _child_env(database_url: str) -> dict:
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    # Belt and braces: a child process must not inherit a strict-mode flag
    # from an operator's shell and silently change what the suite measures.
    env.pop("IMPACT_ENGINE_V4_STRICT", None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def validate_schema(database_url: str, db_path: Path) -> tuple[bool, str]:
    """`alembic upgrade head` on an empty DB, then assert the migrated
    schema actually carries every table and column the ORM declares.

    The upgrade returning 0 is NOT the same claim: a migration that forgot
    a column upgrades cleanly and then explodes at the first INSERT in
    production. Extra columns in the DB are fine (a dropped model field is
    not a runtime failure); missing ones are the defect this catches.
    """
    ok, output = _run([sys.executable, "-m", "alembic", "upgrade", "head"],
                      _child_env(database_url), timeout=600)
    if not ok:
        return False, f"alembic upgrade head failed:\n{output}"

    from sqlalchemy import create_engine, inspect

    from app import models  # noqa: F401  register every model on Base
    from app.db import Base

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        present = set(inspector.get_table_names())
        problems = [f"missing table: {name}"
                    for name in sorted(Base.metadata.tables) if name not in present]
        for name, table in Base.metadata.tables.items():
            if name not in present:
                continue
            columns = {column["name"] for column in inspector.get_columns(name)}
            problems += [f"missing column: {name}.{column.name}"
                         for column in table.columns if column.name not in columns]
    finally:
        engine.dispose()
    if problems:
        return False, "migrated schema does not match the models:\n  " + "\n  ".join(problems)
    return True, (f"alembic upgrade head OK; {len(Base.metadata.tables)} tables and every "
                  f"declared column present")


def audit_report_smoke(database_url: str) -> tuple[bool, str]:
    """Seed a throwaway DB with one alert carrying two decision records --
    one published, one rejected -- then run the audit report against it and
    assert both appear. Read-only tool, no LLM, no network."""
    seed = (
        "import os, json\n"
        "from app.db import init_db, SessionLocal\n"
        "from app.models import Alert, Article, CompanyDecisionRecord\n"
        "init_db()\n"
        "s = SessionLocal()\n"
        "a = Article(source='s', provider='offline_suite', url='https://ex.local/a',\n"
        "            title='t', content='c', status='ANALYZED')\n"
        "s.add(a); s.commit()\n"
        "alert = Alert(article_id=a.id, category='other', event_type='regulation')\n"
        "s.add(alert); s.commit()\n"
        "s.add(CompanyDecisionRecord(alert_id=alert.id, ticker='SHOWN.NS',\n"
        "    final_state='DISPLAY_ELIGIBLE', display_tier='primary',\n"
        "    gate_inputs_json=json.dumps({'ticker': 'SHOWN.NS'})))\n"
        "s.add(CompanyDecisionRecord(alert_id=alert.id, ticker='HIDDEN.NS',\n"
        "    final_state='REJECT_LOW_MATERIALITY', display_tier='excluded',\n"
        "    rejection_reason='REJECT_LOW_MATERIALITY'))\n"
        "s.commit(); print(alert.id)\n"
    )
    env = _child_env(database_url)
    ok, output = _run([sys.executable, "-c", seed], env, timeout=300)
    if not ok:
        return False, f"seeding the throwaway alert failed:\n{output}"
    alert_id = output.strip().splitlines()[-1].strip()

    ok, report = _run([sys.executable, "tools/generate_audit_report.py", alert_id],
                      env, timeout=300)
    if not ok:
        return False, f"generate_audit_report.py failed:\n{report}"
    for needle in ("SHOWN.NS", "HIDDEN.NS", "REJECT_LOW_MATERIALITY"):
        if needle not in report:
            return False, f"audit report is missing {needle!r}:\n{report}"
    return True, f"audit report rendered both decisions for alert {alert_id}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip", action="append", default=[], choices=STEPS,
                        help="skip a step (repeatable); for iteration only")
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="newsflo-offline-suite-"))
    schema_db = workdir / "schema.db"
    audit_db = workdir / "audit.db"
    # Every child that does not need a DB still gets one it cannot damage.
    scratch_url = f"sqlite:///{workdir / 'scratch.db'}"

    results: list[tuple[str, bool, str, float]] = []
    try:
        def step(name: str, runner) -> None:
            if name in args.skip:
                print(f"SKIP {name}")
                return
            started = time.monotonic()
            ok, output = runner()
            elapsed = time.monotonic() - started
            print(f"{'PASS' if ok else 'FAIL'} {name} ({elapsed:.1f}s)")
            results.append((name, ok, output, elapsed))

        step("schema", lambda: validate_schema(f"sqlite:///{schema_db}", schema_db))
        step("unit", lambda: _run([sys.executable, "-m", "pytest", "-q"],
                                  _child_env(scratch_url)))
        step("invariants", lambda: _run(
            [sys.executable, "-m", "pytest", "tests/test_v4_invariants.py", "-q"],
            _child_env(scratch_url)))
        step("bypasses", lambda: _run(
            [sys.executable, "-m", "pytest", "tests/test_audit_bypasses.py", "-q"],
            _child_env(scratch_url)))
        step("regression", lambda: _run(
            [sys.executable, "tools/offline_benchmark.py"], _child_env(scratch_url)))
        step("audit_report", lambda: audit_report_smoke(f"sqlite:///{audit_db}"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    failed = [entry for entry in results if not entry[1]]
    print("\n" + "=" * 60)
    for name, ok, _output, elapsed in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<14} {elapsed:6.1f}s")
    print("=" * 60)
    if failed:
        for name, _ok, output, _elapsed in failed:
            print(f"\n----- {name} output (tail) -----")
            print("\n".join(output.strip().splitlines()[-40:]))
        print(f"\n{len(failed)} step(s) FAILED")
        return 1
    print("offline suite: every step PASSED (no live model, no network, "
          "no writes to newsflo.db)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
