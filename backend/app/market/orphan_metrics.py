"""How much of a rendered card back is an UNLABELLED mechanism.

WHY THIS EXISTS. `ripple_layers._label_for` resolves a persisted
`causal_parent_id` through the mechanism registry, then this module's legacy
taxonomy table, then falls through to `OTHER_LABEL` -- and that last step was
SILENT. Measured 2026-08-17 on the runtime corpus: 45 of 58 stored node ids
resolve to no `knowledge.MECHANISMS` entry and 100% of alerts carry at least
one. A reader of such a section sees "other verified mechanisms" with no
section note, and two distinct mechanisms merge into one heading.

THIS MODULE CHANGES NOTHING. It counts what already happened and emits one
structured record per alert. The V4 fall-through, the merge, and every
rendered label are untouched -- the fix for all of that is the V5 section
engine, which keys sections on `mechanism_id` and labels an unknown loudly
(`UNCLASSIFIED MECHANISM (<id>)`) instead of reassuringly. See DATA_GAPS.md's
V5 SERVING CUTOVER CHECKLIST item 6.

WHAT IT IS FOR: the BEFORE number. While V4 serves, this says how bad serving
is; at cutover it says whether the change helped.

NO SPAM. One record per alert, and only when the alert actually has an
orphan. A clean alert logs nothing.

DELIBERATELY IMPURE and deliberately not imported by anything that computes a
label: logging is a side effect, `orphan_report` is pure, and the split is
the same one `app/core/gate_warnings.py` has against `gates.py`.
"""
import logging
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

logger = logging.getLogger("newsflo.ripple")

#: Where the reader is sent. A numbered checklist item, not a paragraph.
CUTOVER_REFERENCE = "V5 SERVING CUTOVER CHECKLIST item 6 (DATA_GAPS.md)"


@dataclass(frozen=True)
class OrphanReport:
    """One alert's unlabelled-mechanism footprint.

    `orphan_parent_ids` are the DISTINCT persisted `causal_parent_id` values
    that rendered as `OTHER_LABEL`. `orphan_row_count` is how many company
    rows sat under them -- the two differ, and both matter: five rows under
    one unknown id is a naming gap, five rows under five ids is also a
    MERGE (V4 renders them as one section).
    """
    alert_id: int | None
    orphan_parent_ids: tuple[str, ...]
    orphan_row_count: int
    other_label_section_count: int
    section_count: int

    @property
    def orphan_parent_count(self) -> int:
        return len(self.orphan_parent_ids)

    @property
    def clean(self) -> bool:
        return not self.orphan_parent_ids and not self.other_label_section_count

    def as_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "orphan_parent_ids": ",".join(self.orphan_parent_ids),
            "orphan_parent_count": self.orphan_parent_count,
            "orphan_row_count": self.orphan_row_count,
            "other_label_section_count": self.other_label_section_count,
            "section_count": self.section_count,
        }


def orphan_report(*, alert_id: int | None, alert_companies: Sequence,
                  sections: Sequence[Mapping],
                  label_for: Callable[[object], str],
                  other_label: str) -> OrphanReport:
    """Count the alert's unlabelled mechanisms. PURE -- no logging, no DB.

    `label_for` is the SAME resolver the renderer used, passed in rather than
    reimplemented: a second copy of the resolution order would eventually
    disagree with the one that produced the sections, and then this metric
    would be measuring a rendering that never shipped.
    """
    orphan_ids: list[str] = []
    orphan_rows = 0
    for alert_company in alert_companies:
        try:
            label = label_for(alert_company)
        except Exception:                                # pragma: no cover
            # A metric must never be able to break a render. An alert whose
            # label cannot be resolved is not counted rather than raising.
            continue
        if label != other_label:
            continue
        orphan_rows += 1
        parent_id = str(getattr(alert_company, "causal_parent_id", None) or "event")
        if parent_id not in orphan_ids:
            orphan_ids.append(parent_id)

    other_label_sections = sum(
        1 for section in sections
        if other_label in str(section.get("title") or ""))

    return OrphanReport(
        alert_id=alert_id,
        orphan_parent_ids=tuple(sorted(orphan_ids)),
        orphan_row_count=orphan_rows,
        other_label_section_count=other_label_sections,
        section_count=len(sections))


def log_orphan_report(report: OrphanReport) -> OrphanReport:
    """Emit ONE structured INFO per alert that has an orphan, and return the
    report unchanged so a caller can assert on it without reading the log.

    INFO, not WARNING: this is the expected steady state of V4 today, and a
    warning on every alert would train people to ignore warnings. It becomes
    interesting as a TREND and at cutover, which is what a metric is for.
    """
    if report.clean:
        return report
    logger.info(
        "ripple sections: %d company row(s) under %d unlabelled mechanism(s) "
        "rendered as the OTHER_LABEL bucket, across %d of %d section(s). The "
        "mechanism registry does not name these ids, so those rows carry no "
        "section label and distinct mechanisms merge into one heading -- see "
        "%s. ids=%s",
        report.orphan_row_count, report.orphan_parent_count,
        report.other_label_section_count, report.section_count,
        CUTOVER_REFERENCE, ",".join(report.orphan_parent_ids),
        extra=report.as_dict())
    return report
