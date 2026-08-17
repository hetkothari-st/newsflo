"""Loading hand-authored `mechanism_edge` candidates from
`config/mechanism_edges_authored.yaml`.

SAME DISCIPLINE AS `io_bootstrap/load.py`, and for the same reason: this
module is NEVER CALLED IN PRODUCTION TODAY. It exists so that when the owner
extends the exposure vocabulary, loading the edges that were blocked on it is
a transcription rather than a design.

WHAT IT REFUSES, and each refusal is the guarantee rather than a validation
nicety:

  * an entry carrying `reviewed_by` -- a loader may not approve. Approval is
    `app/ledger/edge_review.approve_edge`, which records who did it;
  * an entry carrying `pending_tag` -- the exposure vocabulary does not have
    the leaf this edge needs. Writing it with a nearby tag would state a
    different exposure than the mechanism carries, and the database trigger
    would refuse it anyway;
  * an entry with a null `confidence` -- `mechanism_edge.confidence` is NOT
    NULL and a confidence is a judgement. The loader will not invent one;
  * a `from_node` that is not a modelled shock variable -- discovery would
    report it `unmodelled` and never walk the edge, so writing it would
    create a row that looks live and is not.

It writes `reviewed_by = NULL` and `review_status = 'PENDING'` always, and it
carries each entry's own `derivation` through untouched.

WHAT LOADING DOES AND DOES NOT DO. A loaded row is **inert and queued**: not
walkable by discovery (`traverse.usable` requires APPROVED with a named
reviewer, for every derivation) and visible in `edge_review.pending_edges`
(which keys on `review_status`, not on derivation). **Running this loader is
NOT the approval act** -- approving is `edge_review.approve_edge`, one row at
a time, with a name recorded on each.

That is a correction, and it is worth stating rather than quietly rewriting.
This module's header used to say the opposite: that AUTHORED edges were absent
from the queue, that `traverse.usable()` walked an AUTHORED edge while it was
still PENDING, and that therefore *"running this loader IS the approval act"*.
All three were true of the code as deployed, and together they were defect D10
(`docs/v5/defects/DEFECTS-002-mechanism-edge-review-authority.md`): a loader
could authorise its own writes by choosing a string. None of the three is true
now.
"""
from pathlib import Path
from typing import Iterable, Mapping

import yaml
from sqlalchemy import text

# backend/config/mechanism_edges_authored.yaml
AUTHORED_EDGES_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "mechanism_edges_authored.yaml")

# Provenance an entry may declare. MODEL_PROPOSED is the default: this file
# holds candidates, and the honest label for a mechanism a model suggested and
# a person transcribed is not AUTHORED. Neither value changes what the loader
# writes or what the walk does -- see the module header.
DEFAULT_DERIVATION = "MODEL_PROPOSED"
PERMITTED_DERIVATIONS = ("MODEL_PROPOSED", "AUTHORED")
REVIEW_STATUS_PENDING = "PENDING"


class AuthoredEdgeError(ValueError):
    """A candidate edge that may not be written as it stands."""


def load_candidates(path: Path | None = None) -> tuple[dict, ...]:
    """The candidate entries as written. No validation, no filtering -- this
    is what the file says, including the blocked ones."""
    raw = yaml.safe_load((path or AUTHORED_EDGES_PATH).read_text(encoding="utf-8"))
    return tuple(dict(entry) for entry in (raw.get("edges") or []))


def modelled_shock_variables(path: Path | None = None) -> tuple[str, ...]:
    """The shock variables `config/discovery.yaml` says this system models.
    Read through the deployed loader so the two cannot drift."""
    from app.discovery.config import load_discovery_config

    return tuple(load_discovery_config().modelled_shock_variables)


def blockers(entry: Mapping, *, modelled: Iterable[str]) -> tuple[str, ...]:
    """Every reason this entry cannot be written, named. Returns an empty
    tuple when it is loadable.

    ALL blockers are reported, not the first one: an owner clearing a
    vocabulary gap should see in one pass that the same edge is also waiting
    on a shock variable, rather than discovering it on the next run.
    """
    out: list[str] = []
    edge_id = str(entry.get("edge_id") or "<unnamed>")

    if entry.get("reviewed_by"):
        out.append(
            f"{edge_id}: candidate edges are written UNREVIEWED. Approving one "
            f"is app/ledger/edge_review.approve_edge, which records who did it.")
    if entry.get("pending_tag"):
        out.append(
            f"{edge_id}: needs the exposure leaf {entry['pending_tag']!r}, which "
            f"config/exposure_tags.yaml does not have. Extending the vocabulary "
            f"is a review of THAT file plus a loader re-run -- never a side "
            f"effect of loading an edge.")
    elif not entry.get("exposure_tag"):
        out.append(f"{edge_id}: no exposure_tag and no pending_tag naming what "
                   f"it would need")
    parameters = entry.get("parameters") or {}
    if parameters.get("confidence") is None:
        out.append(
            f"{edge_id}: confidence is null. mechanism_edge.confidence is NOT "
            f"NULL and a confidence is a judgement; this loader does not "
            f"invent one. Owner: {entry.get('owner')}")
    from_node = str(entry.get("from_node") or "")
    if from_node and from_node not in set(modelled):
        out.append(
            f"{edge_id}: from_node {from_node!r} is not in "
            f"config/discovery.yaml::modelled_shock_variables, so discovery "
            f"would report it unmodelled and never walk this edge.")
    derivation = entry.get("derivation", DEFAULT_DERIVATION)
    if derivation not in PERMITTED_DERIVATIONS:
        out.append(
            f"{edge_id}: derivation {derivation!r} is not one this file may "
            f"declare {PERMITTED_DERIVATIONS}. IO_TABLE and EMPIRICAL rows are "
            f"written by their own bootstraps, which record where the "
            f"coefficient or the study came from; a hand-maintained YAML "
            f"cannot substantiate either claim.")
    return tuple(out)


def loadable(path: Path | None = None) -> tuple[tuple[dict, ...], dict]:
    """`(loadable_entries, {edge_id: blockers})` for the whole file."""
    modelled = modelled_shock_variables()
    ready, blocked = [], {}
    for entry in load_candidates(path):
        reasons = blockers(entry, modelled=modelled)
        if reasons:
            blocked[str(entry.get("edge_id"))] = reasons
        else:
            ready.append(entry)
    return tuple(ready), blocked


def load_authored_edges(session, path: Path | None = None, *,
                        strict: bool = True) -> int:
    """Insert every loadable candidate. Idempotent on `edge_id`.

    `strict=True` (the default) RAISES when any entry is blocked, so a run
    that silently wrote three of five is not a possible outcome. Pass
    `strict=False` only to load a cleared subset deliberately, having read
    the blockers.

    An edge already present is NOT overwritten -- a re-run must never quietly
    un-review a decision a person made.
    """
    ready, blocked = loadable(path)
    if blocked and strict:
        raise AuthoredEdgeError(
            "%d of %d authored edges cannot be written:\n%s"
            % (len(blocked), len(blocked) + len(ready),
               "\n".join(reason for reasons in blocked.values()
                         for reason in reasons)))

    written = 0
    for entry in ready:
        existing = session.execute(text(
            "SELECT reviewed_by FROM mechanism_edge WHERE edge_id = :edge_id"),
            {"edge_id": entry["edge_id"]}).first()
        if existing is not None:
            continue
        session.execute(text(
            "INSERT INTO mechanism_edge (edge_id, from_node, to_node, "
            "exposure_tag, relationship_type, distance, io_total_coeff, "
            "derivation, reviewed_by, review_status, confidence, source_url, "
            "effective_from, effective_to) "
            "VALUES (:edge_id, :from_node, :to_node, :exposure_tag, "
            ":relationship_type, :distance, NULL, :derivation, NULL, "
            ":review_status, :confidence, :source_url, :effective_from, "
            ":effective_to)"), {
                "edge_id": str(entry["edge_id"]),
                "from_node": str(entry["from_node"]),
                "to_node": str(entry["to_node"]),
                "exposure_tag": str(entry["exposure_tag"]),
                "relationship_type": str(entry["relationship_type"]),
                "distance": int(entry["distance"]),
                "derivation": str(entry.get("derivation", DEFAULT_DERIVATION)),
                "review_status": REVIEW_STATUS_PENDING,
                "confidence": float(entry["parameters"]["confidence"]),
                "source_url": entry.get("source_url"),
                # Effective dating is carried because without it a loaded edge
                # is valid at every `as_of`, which is BROADER than what the
                # file said. A loader that silently widens an edge's validity
                # is not a transcription. `review_note` is deliberately NOT
                # carried: it is the reviewer's field, and the mechanism's
                # rationale belongs in the entry's own `mechanism:` text.
                "effective_from": entry.get("effective_from"),
                "effective_to": entry.get("effective_to")})
        written += 1
    return written
