"""V5 Phase 4 policy modifiers + horizon vector: policy_modifier, policy_state

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-17 05:00:00.000000

WHAT THIS DOES

Creates the two V5 Phase 4 tables (docs/v5/05_PHASE_4_policy_horizon.md Task
4.1, spec §9) and NOTHING else. No existing table is altered and no column is
added to one.

  policy_modifier   a regulatory/contractual transfer function, with an owner
  policy_state      a tracked regime variable, with a freshness window

BOTH SHIP EMPTY, and `tests/phase4/test_no_fixture_data_reaches_production.py`
asserts it after a full `upgrade head`.

THAT IS A DECISION, NOT AN OMISSION -- and it is the one this migration exists
to make explicit. `config/policy_modifiers.yaml` scaffolds the minimum India
registry the phase file names (SAED windfall levy on crude and product
exports, APM gas pricing, the retail fuel revision state, fuel excise and
state VAT, export duties on steel / rice / sugar, import duties, PLI, MSP,
sugar export quotas, telecom AGR, banking risk weights) with STRUCTURE ONLY:

  * every parameter VALUE is null, with a `_required` key naming what is
    missing;
  * every `owner` is the placeholder `OWNER-REQUIRED`;
  * `review_interval_days` and `last_reviewed_at` are null.

`app/analysis/policy/registry.load_registry` loads each such entry with status
SCAFFOLD, `active_for` never returns one, and `materialise` skips it. So the
scaffold is NOT MATERIALISED: the YAML is the parking place for structure and
the table is the parking place for policy somebody owns, and the two are not
the same thing.

  WHY NOT MATERIALISE THE SCAFFOLD WITH A FLAG? Because this table's contract
  is "these modifiers are in force". A row with a null threshold and a
  placeholder owner would be a modifier every reader of the table had to
  remember to distrust, and the first consumer to forget would apply a levy
  with no rate. A missing row cannot be misread.

Contrast with 0013, which DOES write `valid_exposure_tag`: a tag name is a
WORD the system may use. A levy threshold is a NUMBER about the world. The
first is vocabulary, the second is data, and only the second is covered by
the fabrication guard.

TYPE MAPPING (spec is Postgres, this deployment is SQLite):
  jsonb -> TEXT (JSON)   date -> DATE   text -> TEXT

    -- On Postgres the two parameter columns are real jsonb and the
    -- port is a transcription rather than a redesign:
    ALTER TABLE policy_modifier ALTER COLUMN parameters TYPE jsonb
      USING parameters::jsonb;
    ALTER TABLE policy_state ALTER COLUMN state_value TYPE jsonb
      USING state_value::jsonb;
"""
import sqlalchemy as sa
from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if 'policy_modifier' not in existing:
        op.create_table(
            'policy_modifier',
            sa.Column('modifier_id', sa.String(), nullable=False),
            sa.Column('applies_to_tag', sa.String(), nullable=False),
            sa.Column('jurisdiction', sa.String(), nullable=False),
            sa.Column('modifier_type', sa.String(), nullable=False),
            sa.Column('parameters', sa.Text(), nullable=False),
            sa.Column('effective_from', sa.Date(), nullable=False),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('source_url', sa.String(), nullable=False),
            # A NAMED HUMAN. NOT NULL for the same reason
            # company_exposure.reviewed_by is: a policy parameter is a claim
            # about today, and a claim about today needs somebody who keeps
            # it true.
            sa.Column('owner', sa.String(), nullable=False),
            sa.Column('review_interval_days', sa.Integer(), nullable=False),
            sa.Column('last_reviewed_at', sa.Date(), nullable=False),
            sa.PrimaryKeyConstraint('modifier_id'),
        )
        op.create_index('ix_policy_modifier_tag', 'policy_modifier',
                        ['applies_to_tag'], unique=False)

    if 'policy_state' not in existing:
        op.create_table(
            'policy_state',
            sa.Column('state_key', sa.String(), nullable=False),
            sa.Column('state_value', sa.Text(), nullable=False),
            sa.Column('as_of', sa.Date(), nullable=False),
            sa.Column('freshness_days', sa.Integer(), nullable=False),
            sa.Column('source_url', sa.String(), nullable=False),
            sa.Column('owner', sa.String(), nullable=False),
            sa.PrimaryKeyConstraint('state_key'),
        )

    # NOT ONE ROW IS WRITTEN HERE. See the module docstring.


def downgrade() -> None:
    """Downgrade schema.

    Drops the registry and the tracked regime states. An owner-signed
    modifier is a maintained reading of a live regulation and is NOT
    reproducible by re-running anything -- `config/policy_modifiers.yaml`
    holds the structure, never the values. Take a backup before running this.

    FIX ROUND 1 (M-4): SYMMETRIC WITH `upgrade`. `upgrade` creates each object
    only if it is absent, so a database where one of them already existed
    (this repo also builds schemas with `Base.metadata.create_all`) can reach
    this function with the other one missing. An unconditional drop would then
    raise halfway through and leave the schema in a state neither version
    describes. Each drop is now conditional on the object actually being
    there.
    """
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if 'policy_modifier' in existing:
        indexes = {index['name']
                   for index in sa.inspect(bind).get_indexes('policy_modifier')}
        if 'ix_policy_modifier_tag' in indexes:
            op.drop_index('ix_policy_modifier_tag', table_name='policy_modifier')
    for table in ('policy_state', 'policy_modifier'):
        if table in existing:
            op.drop_table(table)
