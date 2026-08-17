"""V5 vocabulary extension: re-sync valid_exposure_tag from
config/exposure_tags.yaml (adds input:base_oil, input:bought_in_freight,
input:intermediated_air_capacity)

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-17 00:00:00.000000

WHAT THIS DOES

Nothing but re-read `config/exposure_tags.yaml` and INSERT any tag the
`valid_exposure_tag` table does not already carry. It creates no table,
alters no column, and writes no company fact.

WHY IT EXISTS

Migration 0013 populates the vocabulary table from the YAML, so in principle
adding a leaf to the YAML is enough. In practice it is not: alembic will not
re-run 0013 on a database already at head, so a leaf added to the file after
0013 has run is present in the config and ABSENT from the table -- and the
0013 trigger `company_exposure_valid_tag_insert` refuses any tag that is not
in the table. The file would say the tag is legal and the database would
refuse it. This migration closes that gap and will keep closing it: it is a
full re-sync, so a later leaf needs only a `0017` with the same three lines.

WHAT IS BEING ADDED, AND WHY IT IS A VOCABULARY CHANGE AND NOT DATA

  input:base_oil
      Lubricant base stock. The lubricants ripple family has no other
      material input worth naming, and the crude bootstrap found one company
      (Savita Oil) whose note 18 itemises "Base oils" as a line in cost of
      materials consumed -- the best-disclosed exposure in that entire run,
      and unrepresentable in the vocabulary as it stood.

  input:bought_in_freight
      Bought-in road/rail transport capacity, as distinct from
      `input:freight_diesel`, which is a company burning diesel it purchased.
      An asset-light 3PL never buys the diesel; it buys capacity from an
      operator whose bill also contains wages, tolls, tyres and margin. The
      two transmit a crude shock at different speeds and different
      magnitudes, so they are two tags. Merging them would let a freight bill
      be read as a fuel cost.

  input:intermediated_air_capacity
      Chartered aircraft and purchased commercial airlift, whose price
      carries an ATF component through fuel surcharges. Distinct from
      `input:atf` (an airline buying the fuel itself) for the same reason.

Each of these is a WORD the schema may use. None of them asserts that any
company carries the exposure; that claim still lives in `company_exposure`
and still requires a reviewed proposal with a verbatim excerpt.

REVERSIBILITY. `downgrade` removes the three tags IF NO LEDGER ROW OR
MECHANISM EDGE USES THEM, and raises otherwise. Silently deleting a tag that
rows depend on would leave those rows unverifiable against the vocabulary
while the trigger still passed them (the trigger fires on write, not on
read) -- a quiet inconsistency is worse than a failed downgrade.
"""
from pathlib import Path
from typing import Sequence, Union

import yaml

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TAGS_YAML = Path(__file__).resolve().parents[2] / "config" / "exposure_tags.yaml"

# Named so the downgrade knows exactly what this revision introduced. Kept in
# sync with the YAML by test_migration_0016.
ADDED_TAGS = (
    "input:base_oil",
    "input:bought_in_freight",
    "input:intermediated_air_capacity",
)


def _vocabulary_tags() -> list[str]:
    """Flatten config/exposure_tags.yaml to `family:leaf` wire form.

    Byte-identical in behaviour to 0013's function of the same name; a leaf
    is a key with nothing under it, and intermediate grouping keys do not
    appear in the tag.
    """
    raw = yaml.safe_load(_TAGS_YAML.read_text(encoding="utf-8"))
    tags: list[str] = []

    def walk(node, trail):
        if node is None:
            return
        for key, value in node.items():
            if value is None:
                tags.append(f"{trail[0]}:{key}")
            else:
                walk(value, trail + (str(key),))

    for family, subtree in (raw.get("families") or {}).items():
        walk(subtree, (str(family),))
    return tags


def upgrade() -> None:
    """Re-sync the closed vocabulary table from the config file."""
    bind = op.get_bind()
    if 'valid_exposure_tag' not in set(sa.inspect(bind).get_table_names()):
        # 0013 has not run (a database built by create_all, say). Nothing to
        # re-sync; 0013's own loader will populate it.
        return

    statement = (
        sa.text("INSERT OR IGNORE INTO valid_exposure_tag "
                "(exposure_tag, source) VALUES (:tag, :source)")
        if bind.dialect.name == "sqlite" else
        sa.text("INSERT INTO valid_exposure_tag (exposure_tag, source) "
                "VALUES (:tag, :source) ON CONFLICT DO NOTHING"))
    for tag in _vocabulary_tags():
        bind.execute(statement, {"tag": tag,
                                 "source": "config/exposure_tags.yaml"})


def downgrade() -> None:
    """Remove this revision's tags, unless something depends on them."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if 'valid_exposure_tag' not in tables:
        return

    for table in ('company_exposure', 'mechanism_edge'):
        if table not in tables:
            continue
        used = bind.execute(
            sa.text(f"SELECT DISTINCT exposure_tag FROM {table} "
                    "WHERE exposure_tag IN :tags").bindparams(
                        sa.bindparam("tags", expanding=True)),
            {"tags": list(ADDED_TAGS)}).scalars().all()
        if used:
            raise RuntimeError(
                f"cannot downgrade 0016: {table} still carries "
                f"{sorted(used)}. Remove or re-tag those rows first -- "
                "dropping the vocabulary entry underneath them would leave "
                "claims the vocabulary no longer admits.")

    bind.execute(
        sa.text("DELETE FROM valid_exposure_tag WHERE exposure_tag IN :tags")
        .bindparams(sa.bindparam("tags", expanding=True)),
        {"tags": list(ADDED_TAGS)})
