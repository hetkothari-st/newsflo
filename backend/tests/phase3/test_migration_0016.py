"""Migration 0016 -- the reviewed vocabulary extension.

Migration 0013 loads `valid_exposure_tag` from config/exposure_tags.yaml, but
alembic will not re-run 0013 on a database already at head. A leaf added to
the YAML afterwards is therefore legal according to the file and REFUSED by
the 0013 trigger, which reads the table. 0016 closes that gap by re-syncing.

These tests assert the closure, not the intention.
"""
import os
import subprocess
import sys
from pathlib import Path

import yaml
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[2]
TAGS_YAML = BACKEND / "config" / "exposure_tags.yaml"
ADDED = ("input:base_oil", "input:bought_in_freight",
         "input:intermediated_air_capacity")


def _alembic(db_url: str, *args: str):
    env = dict(os.environ, DATABASE_URL=db_url)
    return subprocess.run([sys.executable, "-m", "alembic", *args],
                          cwd=BACKEND, env=env, capture_output=True, text=True)


def _upgrade(tmp_path):
    url = f"sqlite:///{tmp_path / 'vocab.db'}"
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    return url


def _vocabulary_from_yaml() -> set[str]:
    raw = yaml.safe_load(TAGS_YAML.read_text(encoding="utf-8"))
    tags = set()

    def walk(node, family):
        for key, value in (node or {}).items():
            if value is None:
                tags.add(f"{family}:{key}")
            else:
                walk(value, family)

    for family, subtree in (raw.get("families") or {}).items():
        walk(subtree, str(family))
    return tags


def test_head_carries_every_tag_the_config_declares(tmp_path):
    """The whole point: file and table agree after a full upgrade."""
    engine = create_engine(_upgrade(tmp_path))
    with engine.connect() as conn:
        in_db = set(conn.execute(
            text("SELECT exposure_tag FROM valid_exposure_tag")).scalars())
    assert _vocabulary_from_yaml() == in_db


def test_the_three_reviewed_leaves_are_registered(tmp_path):
    engine = create_engine(_upgrade(tmp_path))
    with engine.connect() as conn:
        in_db = set(conn.execute(
            text("SELECT exposure_tag FROM valid_exposure_tag")).scalars())
    assert set(ADDED) <= in_db


def test_the_trigger_now_accepts_the_new_tags_and_still_refuses_junk(tmp_path):
    """A tag in the table is insertable; one that is not is still refused.
    Both halves matter -- an extension that quietly opened the vocabulary
    would be worse than one that never landed."""
    engine = create_engine(_upgrade(tmp_path))
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO companies (id, ticker, name, sector, index_tier, "
            "market, tradeability) VALUES (1, 'T.NS', 'T', 'S', 'OTHER', "
            "'INDIA', 'NORMAL')"))

        def insert(tag):
            conn.execute(text("CREATE TEMP TABLE IF NOT EXISTS "
                              "_newsflo_ledger_review_session (x INT)"))
            try:
                conn.execute(text(
                    "INSERT INTO company_exposure (exposure_id, company_id, "
                    "exposure_kind, exposure_tag, share_of_base, base_kind, "
                    "base_value_inr, measurement, source_type, source_url, "
                    "as_of_date, freshness_days, confidence, created_by) "
                    "VALUES (:id, 1, 'INPUT_COST', :tag, 0.1, 'COGS', 1, "
                    "'ESTIMATED', 'ANNUAL_REPORT', 'http://x', '2026-03-31', "
                    "400, 0.5, 'test')"), {"id": tag, "tag": tag})
            finally:
                conn.execute(text("DROP TABLE IF EXISTS "
                                  "temp._newsflo_ledger_review_session"))

        for tag in ADDED:
            insert(tag)          # must not raise

        try:
            insert("input:not_a_real_leaf")
        except Exception:
            pass
        else:
            raise AssertionError(
                "the vocabulary trigger accepted a tag that is not in "
                "config/exposure_tags.yaml -- the set is no longer closed")


def test_downgrade_refuses_while_a_ledger_row_uses_a_new_tag(tmp_path):
    """Dropping a vocabulary entry underneath live rows would leave claims
    the vocabulary no longer admits. The downgrade must fail loudly."""
    url = _upgrade(tmp_path)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO companies (id, ticker, name, sector, index_tier, "
            "market, tradeability) VALUES (2, 'U.NS', 'U', 'S', 'OTHER', "
            "'INDIA', 'NORMAL')"))
        conn.execute(text("CREATE TEMP TABLE IF NOT EXISTS "
                          "_newsflo_ledger_review_session (x INT)"))
        conn.execute(text(
            "INSERT INTO company_exposure (exposure_id, company_id, "
            "exposure_kind, exposure_tag, share_of_base, base_kind, "
            "base_value_inr, measurement, source_type, source_url, "
            "as_of_date, freshness_days, confidence, created_by) "
            "VALUES ('keep', 2, 'INPUT_COST', 'input:base_oil', 0.8, 'COGS', "
            "1, 'ESTIMATED', 'ANNUAL_REPORT', 'http://x', '2026-03-31', 400, "
            "0.5, 'test')"))
        conn.execute(text("DROP TABLE IF EXISTS "
                          "temp._newsflo_ledger_review_session"))

    result = _alembic(url, "downgrade", "0015")
    assert result.returncode != 0
    assert "cannot downgrade 0016" in (result.stderr + result.stdout)
