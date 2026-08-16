"""TASK 3.7 -- the coverage audit harness (addendum A6).

    ripple_recall  ~  V x M x C x G

      V  shock-variable coverage   do we model the variable this event moves?
      M  mechanism-edge coverage   does a path exist from it to an exposure tag?
      C  company-tagging coverage  are companies tagged with that exposure?
      G  gate survival             do the candidates survive publication?

The recall number is not the deliverable. THE PER-AXIS DIAGNOSTIC IS. A
single aggregate figure hides which of the four is broken, and they have
four different owners and four different fixes -- if M is 55%, nothing done
to C or to a prompt changes anything. So every missing family is attributed
to the FIRST axis that failed, and rendered in the A6.2 format:

    MISSING: tyres
      V shock variable modelled ............ PASS
      M mechanism edge exists .............. FAIL  no usable edge reaches ...
      C companies tagged ................... PASS  4 tagged
      G would pass gates ................... n/a
      ROOT CAUSE: mechanism gap (M).  Owner: graph.  4 listed names.

That turns "the system misses ripples" into an assignable ticket.

WHAT THIS HARNESS SCORES. The SECONDARY_RIPPLE walk. It passes NO
`directness` at all, and it must not: directness is a structural property of
the causal path and discovery does not produce one, so deriving it from
`graph_distance` would be exactly the field-fusion invariant 4 forbids -- and
a test in this package greps this file to make sure it never appears.
Consequently a family that would in reality reach PRIMARY is scored here as
surfaced, not as primary. That is a deliberate limitation of the harness, not
of the gate.

WHAT THE NUMBERS MEAN. Whatever universe it is pointed at. Pointed at this
repo's production database it would report a recall of zero, because the
exposure ledger is empty. The tests point it at a synthetic universe to prove
its arithmetic. Real coverage is DATA_GAPS §7.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Mapping, Sequence

from sqlalchemy import text

from app.analysis.sensitivity.channels import Shock
from app.analysis.sensitivity.engine import analyse_company
from app.core.config_loader import load_gate_config
from app.core.gates import ImpactDraft, evaluate_secondary
from app.discovery.config import load_discovery_config
from app.discovery.engine import DiscoveryEvent, DiscoveryShock, discover
from app.graph.traverse import traverse

# The axis labels, in the order A6.2 prints them.
AXES = (
    ("V", "shock variable modelled"),
    ("M", "mechanism edge exists"),
    ("C", "companies tagged"),
    ("G", "would pass gates"),
)

ROOT_CAUSE_NAMES = {
    "V": ("variable gap (V)", "shock modelling"),
    "M": ("mechanism gap (M)", "graph"),
    "C": ("tagging gap (C)", "ledger"),
    "G": ("gate gap (G)", "gates"),
}

# Fixture inputs the harness supplies because the stages that produce them
# are not part of Phase 3. They are stated here rather than buried: the
# harness measures V, M, C and the RIPPLE GATE, and it is not a substitute
# for the evidence classifier or the verifier.
HARNESS_EVIDENCE_GRADE = "C"        # a ledger-filed exposure with no company-named claim
HARNESS_EVENT_STATUS = "CONFIRMED"
HARNESS_SHOCK_CONFIDENCE = 1.0

# The audit reads no clock: a coverage number that moves because the day
# changed is not a coverage number.
AUDIT_INSTANT = datetime(2000, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class AxisResult:
    axis: str
    label: str
    status: str          # PASS | FAIL | n/a
    detail: str = ""


@dataclass(frozen=True)
class FamilyDiagnostic:
    family: str
    axes: tuple[AxisResult, ...]
    root_cause: str | None
    owner: str | None
    listed_names: int

    def axis(self, letter: str) -> AxisResult:
        for result in self.axes:
            if result.axis == letter:
                return result
        raise KeyError(letter)

    def render(self) -> str:
        lines = [f"MISSING: {self.family}"]
        for result in self.axes:
            head = f"  {result.axis} {result.label} "
            lines.append(f"{head}{'.' * max(2, 40 - len(head))} {result.status}"
                         + (f"  {result.detail}" if result.detail else ""))
        if self.root_cause:
            name, owner = ROOT_CAUSE_NAMES[self.root_cause]
            lines.append(f"  ROOT CAUSE: {name}.  Owner: {owner}.  "
                         f"{self.listed_names} listed names.")
        return "\n".join(lines)


@dataclass(frozen=True)
class PublishedCompany:
    company_id: int
    ticker: str | None
    family: str | None
    mechanism_id: str | None
    graph_distance: int | None
    discovery_source: str
    delta_ebitda_pct_abs: float


@dataclass(frozen=True)
class CoverageReport:
    variable: str
    sign: str
    surfaced_ripple: tuple[str, ...]
    missing: tuple[FamilyDiagnostic, ...]
    ripple_denominator: int
    ripple_recall: float | None
    secondary_precision: float | None
    precision_numerator: int
    precision_denominator: int
    published: tuple[PublishedCompany, ...]
    # Family slugs, plus a ("UNKNOWN_FAMILY", ticker) pair for any published
    # company we could not place in an industry at all (review round 1, M8).
    false_positive_families: tuple
    absent_violations: tuple[str, ...]
    marginal_seen: tuple[str, ...]

    def render(self) -> str:
        head = (f"{self.variable} {self.sign}: ripple recall "
                f"{self.ripple_recall} over {self.ripple_denominator} families, "
                f"SECONDARY precision {self.secondary_precision}")
        return "\n".join([head] + [d.render() for d in self.missing])


# --- the universe under audit ----------------------------------------------

def _family_of_company(session) -> Mapping[int, str | None]:
    """company_id -> industry slug, or None when the company carries no
    usable industry at all. A blank string is NOT a family: treating it as
    one would invent an industry called "" and quietly park companies in it.
    """
    out: dict[int, str | None] = {}
    for row in session.execute(text(
            "SELECT id, COALESCE(sub_sector, sector) FROM companies")):
        industry = (row[1] or "").strip()
        out[int(row[0])] = industry or None
    return out


def _ticker_of_company(session) -> Mapping[int, str]:
    return {int(row[0]): str(row[1]) for row in session.execute(text(
        "SELECT id, ticker FROM companies"))}


def _tagged_companies(session, tags: Sequence[str], family: str) -> list[int]:
    """Companies IN this family that carry one of its tags in the index."""
    if not tags:
        return []
    placeholders = ", ".join(f":t{i}" for i in range(len(tags)))
    parameters = {f"t{i}": tag for i, tag in enumerate(tags)}
    parameters["family"] = family
    return [int(row[0]) for row in session.execute(text(
        "SELECT DISTINCT e.company_id FROM exposure_index e "
        "JOIN companies c ON c.id = e.company_id "
        f"WHERE e.exposure_tag IN ({placeholders}) "
        "  AND COALESCE(c.sub_sector, c.sector) = :family "
        "ORDER BY e.company_id"), parameters)]


def _listed_names(session, family: str) -> int:
    return int(session.execute(text(
        "SELECT count(*) FROM companies "
        "WHERE COALESCE(sub_sector, sector) = :family"),
        {"family": family}).scalar() or 0)


# --- the gate probe ---------------------------------------------------------

def _publishable(session, candidate, *, variable_delta: float, as_of: date,
                 horizon_days: int) -> PublishedCompany | None:
    """Run the real Phase 2 sensitivity engine and the real Phase 0 gate.

    Returns the published row, or None with no explanation -- the harness
    reports G at the FAMILY level, and a per-company reason belongs in the
    review console, not in a recall number.
    """
    if not candidate.via_tag:
        return None
    shock = Shock(shock_id=f"audit:{candidate.via_tag}",
                  exposure_tag=candidate.via_tag, delta_pct=variable_delta,
                  horizon_days=horizon_days, mechanism_id=candidate.mechanism_id)
    run = analyse_company(session, company_id=candidate.company_id,
                          shocks=(shock,), as_of=as_of,
                          event_id=f"audit:{candidate.via_tag}",
                          analysis_version="audit", created_at=AUDIT_INSTANT)
    if run.materiality is None:
        return None

    p50 = float(run.materiality.delta_ebitda_pct.p50)
    proxy = any(source == "SECTOR_PROXY"
                for channel in run.channels
                for source in channel.param_sources.values())

    draft = ImpactDraft(
        entity_status="ACTIVE", entity_ambiguous=False,
        exposure_stale=run.exposure_stale,
        materiality_bucket=run.materiality.bucket,
        graph_distance=candidate.graph_distance,
        # NOT SUPPLIED. See the module docstring: discovery does not produce
        # a directness and this harness will not invent one.
        directness=None,
        evidence_grade=HARNESS_EVIDENCE_GRADE, weakest_link=None,
        sign_consistency=float(run.materiality.sign_consistency),
        empirical_status=None, objections=(), unbound_claim_ids=(),
        verifier_status=None, adv_20d_inr=None,
        event_status=HARNESS_EVENT_STATUS,
        shock_magnitude_confidence=HARNESS_SHOCK_CONFIDENCE,
        mechanism_id=candidate.mechanism_id,
        net_effect=("NEGATIVE" if p50 < 0 else "POSITIVE" if p50 > 0
                    else "UNCERTAIN"),
        delta_ebitda_pct_abs=abs(p50), uses_sector_proxy=proxy)

    if evaluate_secondary(draft, load_gate_config()).tier is None:
        return None
    return PublishedCompany(
        company_id=candidate.company_id, ticker=None, family=None,
        mechanism_id=candidate.mechanism_id,
        graph_distance=candidate.graph_distance,
        discovery_source=candidate.discovery_source,
        delta_ebitda_pct_abs=abs(p50))


# --- the audit --------------------------------------------------------------

def audit_shock(session, entry: Mapping, *, as_of: date,
                horizon_days: int = 90) -> CoverageReport:
    """Audit one entry of the expected-ripple map."""
    shock_spec = entry["shock"]
    variable = str(shock_spec["variable"])
    sign = str(shock_spec["sign"])
    magnitude = float(shock_spec.get("magnitude_pct") or 0) / 100.0
    delta = magnitude if sign == "UP" else -magnitude

    from tests.coverage.conftest import load_expected_map

    family_tags = load_expected_map()["family_tags"]
    config = load_discovery_config()

    expected_ripple = tuple(entry["expected_ripple"])
    expected_primary = tuple(entry["expected_primary"])
    marginal = set(entry["expected_marginal"])
    absent = set(entry["expected_absent"])

    # --- run the real pipeline ---------------------------------------------
    event = DiscoveryEvent(
        event_id=f"audit:{variable}:{sign}", mentions=(),
        shocks=(DiscoveryShock(shock_id=f"audit:{variable}", variable=variable,
                               sign=sign,
                               magnitude_pct=shock_spec.get("magnitude_pct")),))
    pool = discover(session, event, as_of=as_of)
    families = _family_of_company(session)
    tickers = _ticker_of_company(session)

    published: list[PublishedCompany] = []
    for candidate in pool.candidates:
        row = _publishable(session, candidate, variable_delta=delta,
                           as_of=as_of, horizon_days=horizon_days)
        if row is not None:
            published.append(PublishedCompany(
                company_id=row.company_id,
                ticker=tickers.get(row.company_id),
                family=families.get(row.company_id),
                mechanism_id=row.mechanism_id,
                graph_distance=row.graph_distance,
                discovery_source=row.discovery_source,
                delta_ebitda_pct_abs=row.delta_ebitda_pct_abs))

    surfaced = {row.family for row in published if row.family}

    # --- recall over the RIPPLE families, marginal excluded ----------------
    scored = tuple(f for f in expected_ripple if f not in marginal)
    hit = tuple(f for f in scored if f in surfaced)
    recall = (len(hit) / len(scored)) if scored else None

    # --- precision over the published COMPANIES ----------------------------
    # A published company is correct when its family is one a competent
    # analyst would expect (primary or ripple). Marginal families are
    # excluded from both sides (A6.1): scoring cement on crude as a false
    # positive would push the thresholds up, exactly as scoring it as a
    # required hit would push them down.
    #
    # A row we could NOT place in an industry counts against precision and is
    # named with its ticker (review round 1, M8). Dropping it would let an
    # unclassified company improve the score by existing, which is the one
    # direction an error must never point.
    expected_any = set(expected_primary) | set(expected_ripple)
    judged = [row for row in published
              if row.family is None or row.family not in marginal]
    correct = [row for row in judged
               if row.family is not None and row.family in expected_any]
    precision = (len(correct) / len(judged)) if judged else None

    false_positives = tuple(sorted(
        {row.family for row in judged
         if row.family and row.family not in expected_any})) + tuple(
        sorted(("UNKNOWN_FAMILY", row.ticker or str(row.company_id))
               for row in judged if row.family is None))
    absent_violations = tuple(sorted(
        {row.family for row in published if row.family in absent}))
    marginal_seen = tuple(sorted(
        {row.family for row in published if row.family in marginal}))

    # --- the diagnostics ---------------------------------------------------
    edges = (traverse(session, variable, as_of=as_of, max_depth=config.max_depth)
             if config.models(variable) else ())
    reachable = {edge.exposure_tag for edge in edges}

    missing = tuple(
        _diagnose(session, family, family_tags.get(family, ()),
                  modelled=config.models(variable), reachable=reachable,
                  surfaced=family in surfaced, published=published,
                  families=families)
        for family in expected_primary + expected_ripple
        if family not in surfaced and family not in marginal)

    return CoverageReport(
        variable=variable, sign=sign,
        surfaced_ripple=tuple(sorted(surfaced & set(expected_ripple))),
        missing=missing, ripple_denominator=len(scored), ripple_recall=recall,
        secondary_precision=precision, precision_numerator=len(correct),
        precision_denominator=len(judged), published=tuple(published),
        false_positive_families=false_positives,
        absent_violations=absent_violations, marginal_seen=marginal_seen)


def _diagnose(session, family: str, tags, *, modelled: bool, reachable,
              surfaced: bool, published, families) -> FamilyDiagnostic:
    listed = _listed_names(session, family)

    if not modelled:
        axes = (
            AxisResult("V", AXES[0][1], "FAIL", "not in modelled_shock_variables"),
            AxisResult("M", AXES[1][1], "n/a"),
            AxisResult("C", AXES[2][1], "n/a"),
            AxisResult("G", AXES[3][1], "n/a"))
        return FamilyDiagnostic(family, axes, "V", ROOT_CAUSE_NAMES["V"][1],
                                listed)

    reached = tuple(tag for tag in tags if tag in reachable)
    if not reached:
        axes = (
            AxisResult("V", AXES[0][1], "PASS"),
            AxisResult("M", AXES[1][1], "FAIL",
                       f"no usable edge reaches {list(tags)}"),
            AxisResult("C", AXES[2][1],
                       "PASS" if _tagged_companies(session, tags, family)
                       else "FAIL",
                       f"{len(_tagged_companies(session, tags, family))} tagged"),
            AxisResult("G", AXES[3][1], "n/a"))
        return FamilyDiagnostic(family, axes, "M", ROOT_CAUSE_NAMES["M"][1],
                                listed)

    tagged = _tagged_companies(session, reached, family)
    if not tagged:
        axes = (
            AxisResult("V", AXES[0][1], "PASS"),
            AxisResult("M", AXES[1][1], "PASS", f"via {list(reached)}"),
            AxisResult("C", AXES[2][1], "FAIL", f"0/{listed} tagged"),
            AxisResult("G", AXES[3][1], "n/a"))
        return FamilyDiagnostic(family, axes, "C", ROOT_CAUSE_NAMES["C"][1],
                                listed)

    axes = (
        AxisResult("V", AXES[0][1], "PASS"),
        AxisResult("M", AXES[1][1], "PASS", f"via {list(reached)}"),
        AxisResult("C", AXES[2][1], "PASS", f"{len(tagged)}/{listed} tagged"),
        AxisResult("G", AXES[3][1], "FAIL",
                   "candidates were found and none cleared the ripple gate"))
    return FamilyDiagnostic(family, axes, "G", ROOT_CAUSE_NAMES["G"][1], listed)
