"""TASK 5.3 -- the fitted-model registry, and the three locks on activation.

    "Until the corpus exists, ship with calibration disabled and
     calibrated_p = null... Do not ship a fitted-looking model trained on
     synthetic labels."

THE LOCKS, in the order they fire:

  1. `record_model(..., fixture_labels=True)` is REFUSED. The only labels that
     exist in this repo are `_fixture` ones written by tests to prove the
     arithmetic; a model fitted on them may exist in memory for the length of
     a test and may never be written down.
  2. `record_model(..., is_active=True)` is REFUSED in code, and the DATABASE
     refuses it too -- `calibration_model.is_active` carries a CHECK
     constraint pinning it to 0 (migration 0015). Activation therefore takes a
     migration, which is a reviewed act rather than a flag somebody flips.
  3. `can_activate` requires a labeled corpus of at least
     `config/calibration.yaml`'s `min_corpus_size`, and `load_labeled_corpus`
     raises because there is no corpus at all (DATA_GAPS §1).

All three, not any one of them. A single guard is a guard somebody removes in
a hurry.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

import json

from sqlalchemy import text

from app.analysis.calibration.config import CalibrationConfig, load_calibration_config


class CalibrationActivationRefused(RuntimeError):
    """An attempt to write, or switch on, a model that must not exist yet."""


class NoLabeledCorpus(RuntimeError):
    """There is no expert-judged corpus to fit or score against."""


@dataclass(frozen=True)
class CalibrationModelRow:
    model_version: str
    method: str
    corpus_size: int
    ece: float | None
    brier: float | None
    is_active: bool


def can_activate(*, corpus_size: int,
                 config: CalibrationConfig | None = None) -> bool:
    """Whether the corpus is big enough for a fit to mean anything. Necessary,
    never sufficient -- see the module docstring."""
    config = config or load_calibration_config()
    return bool(config.enabled) and int(corpus_size) >= config.min_corpus_size


def active_model(session) -> CalibrationModelRow | None:
    """The model in force, or None. Returns None in every deployment: the
    table cannot hold an active row."""
    row: Any = session.execute(text(
        "SELECT model_version, method, corpus_size, ece, brier, is_active "
        "FROM calibration_model WHERE is_active = 1 "
        "ORDER BY model_version ASC")).mappings().first()
    if row is None:
        return None
    return CalibrationModelRow(                        # pragma: no cover
        model_version=str(row["model_version"]), method=str(row["method"]),
        corpus_size=int(row["corpus_size"]),
        ece=(None if row["ece"] is None else float(row["ece"])),
        brier=(None if row["brier"] is None else float(row["brier"])),
        is_active=bool(row["is_active"]))


def record_model(session, *, model_version: str, method: str, corpus_size: int,
                 fitted_at: datetime | None, is_active: bool = False,
                 fixture_labels: bool = False,
                 feature_names: Sequence[str] | None = None,
                 ece: float | None = None, brier: float | None = None,
                 notes: str | None = None,
                 config: CalibrationConfig | None = None) -> str:
    """Write a fitted model into the registry. Refuses the two cases that
    would put a fake calibration in front of a user."""
    config = config or load_calibration_config()
    if fixture_labels:
        raise CalibrationActivationRefused(
            "this model was fitted on _fixture labels. The arithmetic may be "
            "exercised on them; the RESULT may not be recorded -- 'do not ship "
            "a fitted-looking model trained on synthetic labels'.")
    if is_active:
        raise CalibrationActivationRefused(
            "no calibration model may be ACTIVE. Activation requires a labeled "
            f"corpus of at least {config.min_corpus_size} expert-judged calls "
            "(none exists, DATA_GAPS §1) and a migration dropping "
            "ck_calibration_model_never_active. Until then calibrated_p is "
            "null and the UI shows evidence grade and band instead.")
    if corpus_size < config.min_corpus_size:
        raise CalibrationActivationRefused(
            f"corpus_size {corpus_size} is below the configured minimum "
            f"{config.min_corpus_size}: an isotonic fit on that many labels is "
            "a memorised sample, not a calibration.")

    session.execute(text(
        "INSERT INTO calibration_model (model_version, method, fitted_at, "
        "corpus_size, feature_names_json, ece, brier, is_active, notes, "
        "created_at) VALUES (:model_version, :method, :fitted_at, "
        ":corpus_size, :feature_names_json, :ece, :brier, 0, :notes, "
        ":created_at)"), {
            "model_version": model_version, "method": method,
            "fitted_at": (None if fitted_at is None else fitted_at.isoformat()),
            "corpus_size": corpus_size,
            "feature_names_json": (None if feature_names is None
                                   else json.dumps(list(feature_names))),
            "ece": ece, "brier": brier, "notes": notes,
            "created_at": datetime.now(timezone.utc).isoformat()})
    return model_version


def load_labeled_corpus():
    """The expert-judged corpus §13.2 fits on (Phase 7 builds it).

    Raises, always, today. It is a function rather than an absence so the
    ship-gate test can name what it is waiting for instead of being silently
    absent from the suite.
    """
    raise NoLabeledCorpus(
        "there is no labeled corpus in this repo (DATA_GAPS §1). Calibration "
        "ships disabled and calibrated_p is null; fitting on self-generated "
        "labels is forbidden by the phase file's own DO NOT.")
