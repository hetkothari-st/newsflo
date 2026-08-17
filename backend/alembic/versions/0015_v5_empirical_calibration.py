"""V5 Phase 5 empirical cross-check + calibration: transmission_empirical,
divergence_review, regime_change, calibration_model

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-17 06:00:00.000000

WHAT THIS DOES

Creates the four V5 Phase 5 tables (docs/v5/06_PHASE_5_empirical_calibration.md
Tasks 5.1-5.5, spec §10 / §13) and NOTHING else. No existing table is altered
and no column is added to one.

  transmission_empirical  how a company actually behaved across historical
                          shocks, per (variable, sign, horizon, estimator)
  divergence_review       the queue a conflict is ROUTED to -- never rejected
  regime_change           a human's REGIME_CHANGED annotation, with an expiry
  calibration_model       the fitted-model registry

ALL FOUR SHIP EMPTY, and `tests/phase5/test_no_fixture_data_reaches_production.py`
asserts it after a full `upgrade head`.

THAT IS A DECISION, NOT AN OMISSION, and it is different for each table.

  * `transmission_empirical` is empty because THE PRICE DATA DOES NOT EXIST.
    Eight-plus years of adjusted daily returns for the listed universe, the
    sector benchmark series and the dated shock instances per variable are all
    acquisition work and all the owner's (DATA_GAPS §9). The machinery is
    complete and runs on any `ReturnHistory` a caller supplies; producing rows
    from a model's memory of how ONGC trades would be exactly the fabrication
    the master context forbids, and a wrong CAR would be INVISIBLE -- it would
    make the output look validated.

  * `calibration_model` is empty because THE LABELED CORPUS DOES NOT EXIST,
    and the phase file's own DO NOT is explicit: "do not fit calibration on
    synthetic or self-generated labels. Disabled beats fake." So the column
    `is_active` carries a CHECK CONSTRAINT pinning it to 0. Activation is not
    merely unconfigured, it is STRUCTURALLY IMPOSSIBLE: switching calibration
    on requires (a) a labeled corpus above `config/calibration.yaml`'s minimum,
    (b) a fitted model recorded here, and (c) a MIGRATION that drops this
    constraint -- a deliberate, reviewed act rather than a flag somebody flips.

  * `divergence_review` and `regime_change` are empty because nothing has been
    reviewed yet. They are workflow tables and fill up by being used.

`regime_change.expires_on` is NOT NULL on purpose. A regime claim nobody
re-affirms is a regime claim nobody is maintaining -- the same rule Phase 4
applied to `policy_state`, and the reason §10.3 says the annotation is
"recorded with an expiry date".

TYPE MAPPING (spec is Postgres, this deployment is SQLite):
  uuid -> INTEGER (this repo keys companies by integer id, as every V5 table
                   since 0011 does)   numeric -> NUMERIC   timestamptz -> DATETIME

    -- On Postgres the JSON column is real jsonb and the port is a
    -- transcription rather than a redesign:
    ALTER TABLE calibration_model ALTER COLUMN feature_names_json TYPE jsonb
      USING feature_names_json::jsonb;
"""
import sqlalchemy as sa
from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if 'transmission_empirical' not in existing:
        op.create_table(
            'transmission_empirical',
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('shock_variable', sa.String(), nullable=False),
            sa.Column('shock_sign', sa.String(), nullable=False),
            sa.Column('horizon', sa.String(), nullable=False),
            sa.Column('n_events', sa.Integer(), nullable=False),
            sa.Column('median_car', sa.Numeric(), nullable=False),
            sa.Column('iqr_lo', sa.Numeric(), nullable=True),
            sa.Column('iqr_hi', sa.Numeric(), nullable=True),
            sa.Column('p_value', sa.Numeric(), nullable=False),
            sa.Column('sign_consistency', sa.Numeric(), nullable=False),
            # In the PRIMARY KEY, per spec §10.1: two estimators may coexist
            # and be compared, instead of one silently replacing the other.
            sa.Column('estimator_version', sa.String(), nullable=False),
            sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('company_id', 'shock_variable', 'shock_sign',
                                    'horizon', 'estimator_version'),
        )
        op.create_index('ix_transmission_empirical_company',
                        'transmission_empirical', ['company_id'], unique=False)

    if 'divergence_review' not in existing:
        op.create_table(
            'divergence_review',
            # CONTENT-ADDRESSED: re-running the same analysis re-queues the
            # same review instead of growing the queue by one per run.
            sa.Column('review_id', sa.String(), nullable=False),
            sa.Column('kind', sa.String(), nullable=False),
            sa.Column('event_id', sa.String(), nullable=True),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('shock_variable', sa.String(), nullable=True),
            sa.Column('shock_sign', sa.String(), nullable=True),
            sa.Column('horizon', sa.String(), nullable=True),
            sa.Column('fundamental_direction', sa.String(), nullable=True),
            sa.Column('empirical_status', sa.String(), nullable=True),
            sa.Column('n_events', sa.Integer(), nullable=True),
            sa.Column('median_car', sa.Numeric(), nullable=True),
            sa.Column('p_value', sa.Numeric(), nullable=True),
            sa.Column('excess_move_pct', sa.Numeric(), nullable=True),
            sa.Column('threshold_pct', sa.Numeric(), nullable=True),
            sa.Column('status', sa.String(), nullable=False,
                      server_default='OPEN'),
            sa.Column('resolution', sa.String(), nullable=True),
            sa.Column('reason', sa.Text(), nullable=True),
            sa.Column('reviewed_by', sa.String(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('review_id'),
        )
        op.create_index('ix_divergence_review_status', 'divergence_review',
                        ['status'], unique=False)

    if 'regime_change' not in existing:
        op.create_table(
            'regime_change',
            sa.Column('annotation_id', sa.String(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            # "<variable>:<sign>" -- the (company, shock_class) pair §10.3
            # names as the scope of the annotation.
            sa.Column('shock_class', sa.String(), nullable=False),
            sa.Column('reason', sa.Text(), nullable=False),
            # A NAMED HUMAN. This annotation is what lets a company make a
            # PRIMARY call against its own history; it needs an author.
            sa.Column('reviewed_by', sa.String(), nullable=False),
            sa.Column('effective_from', sa.Date(), nullable=False),
            # NOT NULL: see the module docstring. There is no "permanent".
            sa.Column('expires_on', sa.Date(), nullable=False),
            sa.Column('review_id', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('annotation_id'),
        )
        op.create_index('ix_regime_change_company_class', 'regime_change',
                        ['company_id', 'shock_class'], unique=False)

    if 'calibration_model' not in existing:
        op.create_table(
            'calibration_model',
            sa.Column('model_version', sa.String(), nullable=False),
            sa.Column('method', sa.String(), nullable=False),
            sa.Column('fitted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('corpus_size', sa.Integer(), nullable=False),
            sa.Column('feature_names_json', sa.Text(), nullable=True),
            sa.Column('ece', sa.Numeric(), nullable=True),
            sa.Column('brier', sa.Numeric(), nullable=True),
            sa.Column('is_active', sa.Integer(), nullable=False,
                      server_default='0'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint('is_active = 0',
                               name='ck_calibration_model_never_active'),
            sa.PrimaryKeyConstraint('model_version'),
        )

    # NOT ONE ROW IS WRITTEN HERE. See the module docstring.


def downgrade() -> None:
    """Downgrade schema.

    Drops the transmission matrix, the review queue, the regime annotations
    and the model registry. A `regime_change` row is a HUMAN JUDGEMENT and is
    not reproducible by re-running anything; a `transmission_empirical` row is
    reproducible only if the price history that produced it still exists. Take
    a backup before running this.
    """
    op.drop_index('ix_regime_change_company_class', table_name='regime_change')
    op.drop_index('ix_divergence_review_status', table_name='divergence_review')
    op.drop_index('ix_transmission_empirical_company',
                  table_name='transmission_empirical')
    for table in ('calibration_model', 'regime_change', 'divergence_review',
                  'transmission_empirical'):
        op.drop_table(table)
