"""TASK 5.1 -- the event-study transmission matrix (spec §10.1).

The causal graph asserts "crude up => this refiner's margin down". Nothing in
Phases 0-4 ever asks whether that has EVER been true. This module is the
falsifier: for each (company, shock variable, shock sign, horizon) it says how
the name actually behaved across comparable historical shocks, and the answer
is allowed to CONTRADICT the fundamental read.

It is a CROSS-CHECK, never a source of direction. A `median_car` never becomes
a direction, a materiality, or a number a user reads as a forecast. The only
things the answer may do are cap a tier, raise an objection, queue a review and
supply a sentence of context (`check.py`, `divergence.py`, `presentation.py`).

ZERO NETWORK, BY CONSTRUCTION. This module NEVER fetches a price. It computes
over a `ReturnHistory` the caller hands it, exactly like `gap_finder.py`. The
repo's own price access is yfinance-based and therefore a live socket; wiring
it in here would make every test and every scheduler tick a network call
waiting to happen. An ast scan in `tests/phase5/test_event_study.py` refuses
any import that could open one, and a second scan refuses a clock read -- a
transmission matrix that changes when you rerun it is not evidence.

THE ESTIMATOR IS DOCUMENTED BEFORE IT IS TRUSTED.
`.superpowers/sdd/2026-08-17-v5-session0/phase5-estimator-design.md` carries
the model, every window, every edge-case rule and the hand-computed arithmetic
of the fixture -- under a PENDING-OWNER-VERIFICATION header, because not one
of these choices has been validated against Indian market data.

WHAT DOES NOT EXIST YET. Eight-plus years of daily returns for the listed
universe, the sector benchmark series, and a dated list of shock instances per
variable. All three are acquisition work and all three are the owner's
(DATA_GAPS §9). Until they exist this module runs only on histories a test
wrote, `transmission_empirical` stays EMPTY, and every company's empirical
status is the literal truth: NO_DATA.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Protocol, Sequence

from sqlalchemy import text

from app.analysis.empirical.config import EmpiricalPolicy, load_empirical_config
from app.analysis.empirical.gap_finder import summarise

# The estimator's IDENTITY. It is written onto every persisted row and is part
# of `transmission_empirical`'s primary key, so two estimators can coexist and
# be compared instead of one silently replacing the other. CHANGE THIS STRING
# whenever the model, the windows or an edge-case rule changes -- a row whose
# version no longer describes how it was computed is worse than no row.
CAR_ESTIMATOR_VERSION = "sector_beta_v1"

SIGN_UP = "UP"
SIGN_DOWN = "DOWN"

# Why a CAR could not be computed. Every one of them yields None. NOT ONE of
# them yields 0.0: a zero is a claim that the company did not move.
ABSTAIN_NO_BENCHMARK = "NO_BENCHMARK"
ABSTAIN_ESTIMATION = "INSUFFICIENT_ESTIMATION_WINDOW"
ABSTAIN_THIN_EVENT_WINDOW = "THIN_EVENT_WINDOW"
ABSTAIN_MISSING_RETURN = "MISSING_RETURN_IN_EVENT_WINDOW"


class ShockSeriesTooShort(ValueError):
    """A variable series shorter than the deployed minimum span.

    Refused rather than computed on: a sigma measured over two years is a
    different threshold wearing the same name, and the events it selects are
    not comparable to the ones an eight-year sigma selects.
    """


# --- the input contract -----------------------------------------------------

@dataclass(frozen=True)
class DailyObservation:
    """One trading day for one series.

    `return_pct` is a SIMPLE return, ALREADY adjusted for corporate actions.
    `None` means MISSING and is never zero-filled. A supplier that cannot
    adjust a split must return None for that day rather than the raw -50%
    print, and say so in `corporate_action`.
    """
    day: date
    offset: int                       # trading days from the event day
    return_pct: float | None = None
    traded: bool = True
    circuit: str | None = None        # None | "UPPER" | "LOWER"
    corporate_action: str | None = None


class ReturnHistory(Protocol):
    """Everything the estimator needs from the market, and nothing more.

    Indexed by TRADING-DAY OFFSET rather than by calendar range, because only
    the supplier knows the exchange calendar -- and a study that has to infer
    one would silently miscount every holiday.

    Deliberately defined HERE, in `app/analysis/empirical/`, and not in
    `app/market/*`: Task 5.5 forbids every V5 package from importing the market
    layer, and an interface that lived there would make that ban unsatisfiable.
    """

    def window(self, company_id: int, event_day: date, from_offset: int,
               to_offset: int) -> Sequence[DailyObservation]:
        ...

    def benchmark_window(self, benchmark_id: str, event_day: date,
                         from_offset: int, to_offset: int
                         ) -> Sequence[DailyObservation]:
        ...

    def benchmark_for(self, company_id: int) -> str | None:
        ...


class PriceHistoryLike(Protocol):
    """`gap_finder.PriceHistory` -- the CONSUMER side, which hands back a
    finished CAR. `CarPriceHistory` below adapts a `ReturnHistory` to it, so
    Task 3.5's reverse study and this forward one compute a CAR the same way
    instead of drifting apart."""

    def cumulative_abnormal_return(self, company_id: int, event_date: date,
                                   window_days: int) -> float | None:
        ...


@dataclass(frozen=True)
class MarketModel:
    alpha: float
    beta: float
    n_days: int
    benchmark_id: str


@dataclass(frozen=True)
class CarResult:
    company_id: int
    event_day: date
    horizon: str
    window_days: int
    car: float | None
    abstain_reason: str | None
    censored_days: int = 0
    had_corporate_action: bool = False
    benchmark_id: str | None = None
    model: MarketModel | None = None
    estimator_version: str = CAR_ESTIMATOR_VERSION


@dataclass(frozen=True)
class ShockInstance:
    variable: str
    day: date
    move: float
    sign: str


@dataclass(frozen=True)
class TransmissionRow:
    company_id: int
    shock_variable: str
    shock_sign: str
    horizon: str
    n_events: int
    median_car: float
    iqr_lo: float
    iqr_hi: float
    p_value: float
    sign_consistency: float
    estimator_version: str = CAR_ESTIMATOR_VERSION


# --- shock detection (spec §10.1 steps 1-2) ---------------------------------

def daily_moves(series: Sequence[tuple[date, float]]
                ) -> tuple[tuple[date, float], ...]:
    """Simple returns of the LEVEL over consecutive observations.

    Simple rather than log on purpose: the sigma threshold and the reported
    move should be the unit an analyst quotes ("crude fell 4% that day").
    A non-positive previous level yields no move rather than a division.
    """
    out: list[tuple[date, float]] = []
    for (_, previous), (day, level) in zip(series, series[1:]):
        if previous is None or level is None or previous == 0:
            continue
        out.append((day, float(level) / float(previous) - 1.0))
    return tuple(out)


def sigma_of(values: Sequence[float]) -> float:
    """Population standard deviation about the sample mean (ddof = 0).

    FULL-SAMPLE, not rolling. A rolling sigma makes "is this a shock" depend
    on when you ask, so the same day enters and leaves the event set as the
    window slides and `n_events` stops being reproducible. The known cost is
    recorded in the estimator design doc: a full-sample sigma is inflated by
    the crises that generate most shocks, so the threshold is conservative.
    """
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5


def detect_shocks(variable: str, series: Sequence[tuple[date, float]], *,
                  policy: EmpiricalPolicy | None = None
                  ) -> tuple[ShockInstance, ...]:
    """`|move| > sigma_multiple x sigma`, deduplicated to one per window."""
    policy = policy or load_empirical_config()
    if len(series) < policy.min_series_days:
        raise ShockSeriesTooShort(
            f"{variable}: {len(series)} observations, the deployed policy "
            f"requires at least {policy.min_series_days} (spec §10.1 asks for "
            f">= 8 years). A shorter series is refused, not computed on.")

    moves = daily_moves(series)
    threshold = policy.shock_sigma_multiple * sigma_of([m for _, m in moves])
    if threshold <= 0:
        return ()

    candidates = sorted((entry for entry in moves if abs(entry[1]) > threshold),
                        key=lambda entry: (-abs(entry[1]), entry[0]))
    kept: list[tuple[date, float]] = []
    for day, move in candidates:
        # Sign is NOT part of the dedupe key: a +4% day followed two days later
        # by a -5% day is ONE episode (the -5%), not one of each. Counting both
        # would double-count the same information.
        if any(abs((day - other).days) < policy.shock_dedupe_days
               for other, _ in kept):
            continue
        kept.append((day, move))
    return tuple(ShockInstance(
        variable=variable, day=day, move=move,
        sign=(SIGN_UP if move > 0 else SIGN_DOWN))
        for day, move in sorted(kept))


# --- the estimator ----------------------------------------------------------

def _by_offset(observations: Sequence[DailyObservation]
               ) -> dict[int, DailyObservation]:
    return {int(o.offset): o for o in observations}


def fit_market_model(history: ReturnHistory, *, company_id: int,
                     event_day: date, policy: EmpiricalPolicy | None = None
                     ) -> MarketModel | None:
    """OLS of the company's return on its benchmark's, over the estimation
    window. `None` means NOT ESTIMABLE -- never a beta shrunk toward 1.0,
    which would be a number nobody measured.

    A usable pair is a day where BOTH series have a return AND the company
    actually traded. A day carrying a corporate action is dropped: a split
    print is a -50% return that never happened.
    """
    policy = policy or load_empirical_config()
    benchmark_id = history.benchmark_for(company_id)
    if not benchmark_id:
        return None

    start, end = policy.estimation_start_offset, policy.estimation_end_offset
    company = _by_offset(history.window(company_id, event_day, start, end))
    benchmark = _by_offset(
        history.benchmark_window(benchmark_id, event_day, start, end))

    xs: list[float] = []
    ys: list[float] = []
    for offset, observation in sorted(company.items()):
        other = benchmark.get(offset)
        if other is None or other.return_pct is None:
            continue
        if observation.return_pct is None or not observation.traded:
            continue
        if observation.corporate_action:
            continue
        xs.append(float(other.return_pct))
        ys.append(float(observation.return_pct))

    if len(xs) < policy.min_estimation_days:
        return None

    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance == 0:
        # A benchmark that never moved carries no information about beta.
        return None
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    beta = covariance / variance
    return MarketModel(alpha=mean_y - beta * mean_x, beta=beta,
                       n_days=len(xs), benchmark_id=benchmark_id)


def estimate_car(history: ReturnHistory, *, company_id: int, event_day: date,
                 policy: EmpiricalPolicy | None = None,
                 horizons: Sequence[str] | None = None
                 ) -> Mapping[str, CarResult]:
    """`{horizon: CarResult}` for one company and one shock day.

    The abnormal return is the residual of the market model; the CAR is its
    sum over trading days `[0, h]` INCLUSIVE of the event day -- the shock is
    measured on day 0, and excluding it would systematically measure the drift
    after the reaction and call it the reaction.
    """
    policy = policy or load_empirical_config()
    labels = tuple(horizons) if horizons else tuple(policy.car_horizons)

    def refuse(reason: str, benchmark_id: str | None = None,
               model: MarketModel | None = None) -> Mapping[str, CarResult]:
        return {label: CarResult(
            company_id=company_id, event_day=event_day, horizon=label,
            window_days=policy.window_days(label), car=None,
            abstain_reason=reason, benchmark_id=benchmark_id, model=model)
            for label in labels}

    benchmark_id = history.benchmark_for(company_id)
    if not benchmark_id:
        return refuse(ABSTAIN_NO_BENCHMARK)

    model = fit_market_model(history, company_id=company_id,
                             event_day=event_day, policy=policy)
    if model is None:
        return refuse(ABSTAIN_ESTIMATION, benchmark_id)

    longest = max(policy.window_days(label) for label in labels)
    company = _by_offset(history.window(company_id, event_day, 0, longest))
    benchmark = _by_offset(
        history.benchmark_window(benchmark_id, event_day, 0, longest))

    results: dict[str, CarResult] = {}
    for label in labels:
        window = policy.window_days(label)
        offsets = range(0, window + 1)
        traded = sum(1 for offset in offsets
                     if (company.get(offset) is not None
                         and company[offset].traded
                         and company[offset].return_pct is not None))
        if traded < policy.min_event_window_traded_fraction * (window + 1):
            results[label] = CarResult(
                company_id=company_id, event_day=event_day, horizon=label,
                window_days=window, car=None,
                abstain_reason=ABSTAIN_THIN_EVENT_WINDOW,
                benchmark_id=benchmark_id, model=model)
            continue

        total = 0.0
        censored = 0
        corporate_action = False
        missing = False
        for offset in offsets:
            observation = company.get(offset)
            other = benchmark.get(offset)
            if (observation is None or other is None
                    or observation.return_pct is None
                    or other.return_pct is None):
                missing = True
                if observation is not None and observation.corporate_action:
                    corporate_action = True
                break
            if observation.circuit:
                # The move is real, merely truncated: the true reaction is AT
                # LEAST this large. Dropping the day understates it; pretending
                # it is complete misstates it. It is kept and FLAGGED, so a
                # reviewer can discount it.
                censored += 1
            if observation.corporate_action:
                corporate_action = True
            total += float(observation.return_pct) - (
                model.alpha + model.beta * float(other.return_pct))

        results[label] = CarResult(
            company_id=company_id, event_day=event_day, horizon=label,
            window_days=window, car=(None if missing else total),
            abstain_reason=(ABSTAIN_MISSING_RETURN if missing else None),
            censored_days=censored, had_corporate_action=corporate_action,
            benchmark_id=benchmark_id, model=model)
    return results


class CarPriceHistory:
    """A `ReturnHistory` seen through `gap_finder.PriceHistory`'s one method.

    Task 3.5's reverse study (which industries moved?) and Task 5.1's forward
    study (did THIS name move?) must compute a CAR the same way, or the
    blind-spot detector and the cross-check disagree about what history said.
    """

    def __init__(self, history: ReturnHistory, *,
                 policy: EmpiricalPolicy | None = None):
        self._history = history
        self._policy = policy or load_empirical_config()

    def cumulative_abnormal_return(self, company_id: int, event_date: date,
                                   window_days: int) -> float | None:
        label = next((name for name, days in self._policy.car_horizons.items()
                      if int(days) == int(window_days)), None)
        if label is None:
            return None
        return estimate_car(self._history, company_id=company_id,
                            event_day=event_date, policy=self._policy,
                            horizons=(label,))[label].car


# --- aggregation ------------------------------------------------------------

def summarise_cars(values: Sequence[float]
                   ) -> tuple[float, float, float, float, float] | None:
    """(median, iqr_lo, iqr_hi, sign_consistency, p_value), or None on an
    empty set.

    Delegates to `gap_finder.summarise` so the reverse study and this one
    cannot disagree about what a median, an IQR or a p-value is. The p-value
    is a two-sided exact binomial sign test: abnormal returns are fat-tailed
    and a handful of crisis observations would dominate a mean.
    """
    if not values:
        return None
    return summarise(list(values))


def build_transmission_rows(history: PriceHistoryLike, *,
                            company_ids: Sequence[int], variable: str,
                            shock_days: Sequence[date], shock_sign: str,
                            policy: EmpiricalPolicy | None = None,
                            horizons: Sequence[str] | None = None
                            ) -> tuple[TransmissionRow, ...]:
    """One row per (company, horizon) over all shock days that produced a CAR.

    `n_events` counts the events that produced a USABLE CAR, not the events
    detected. The two differ exactly when a company was thin, unlisted or
    mid-corporate-action, and conflating them would report a sample that never
    existed.
    """
    policy = policy or load_empirical_config()
    labels = tuple(horizons) if horizons else tuple(policy.car_horizons)

    rows: list[TransmissionRow] = []
    for company_id in company_ids:
        for label in labels:
            window = policy.window_days(label)
            cars = []
            for day in shock_days:
                car = history.cumulative_abnormal_return(company_id, day, window)
                if car is None:
                    # No history is no observation. It is NEVER a zero.
                    continue
                cars.append(float(car))
            summary = summarise_cars(cars)
            if summary is None:
                continue
            median, low, high, consistency, p_value = summary
            rows.append(TransmissionRow(
                company_id=company_id, shock_variable=variable,
                shock_sign=shock_sign, horizon=label, n_events=len(cars),
                median_car=median, iqr_lo=low, iqr_hi=high, p_value=p_value,
                sign_consistency=consistency))
    return tuple(rows)


# --- persistence ------------------------------------------------------------

def persist_transmission_rows(session, rows: Sequence[TransmissionRow], *,
                              computed_at: datetime) -> int:
    """Upsert on the spec's primary key. Rebuilding the matrix REFRESHES the
    statistics rather than growing a log, and `computed_at` is supplied by the
    caller so a rebuild is replayable."""
    written = 0
    for row in rows:
        session.execute(text(
            "INSERT INTO transmission_empirical (company_id, shock_variable, "
            "shock_sign, horizon, n_events, median_car, iqr_lo, iqr_hi, "
            "p_value, sign_consistency, estimator_version, computed_at) VALUES "
            "(:company_id, :shock_variable, :shock_sign, :horizon, :n_events, "
            ":median_car, :iqr_lo, :iqr_hi, :p_value, :sign_consistency, "
            ":estimator_version, :computed_at) "
            "ON CONFLICT (company_id, shock_variable, shock_sign, horizon, "
            "estimator_version) DO UPDATE SET "
            " n_events = excluded.n_events, median_car = excluded.median_car, "
            " iqr_lo = excluded.iqr_lo, iqr_hi = excluded.iqr_hi, "
            " p_value = excluded.p_value, "
            " sign_consistency = excluded.sign_consistency, "
            " computed_at = excluded.computed_at"), {
                "company_id": row.company_id,
                "shock_variable": row.shock_variable,
                "shock_sign": row.shock_sign, "horizon": row.horizon,
                "n_events": row.n_events, "median_car": row.median_car,
                "iqr_lo": row.iqr_lo, "iqr_hi": row.iqr_hi,
                "p_value": row.p_value,
                "sign_consistency": row.sign_consistency,
                "estimator_version": row.estimator_version,
                "computed_at": computed_at.isoformat()})
        written += 1
    return written


def transmission_row_for(session, *, company_id: int, shock_variable: str,
                         shock_sign: str, horizon: str,
                         estimator_version: str = CAR_ESTIMATOR_VERSION
                         ) -> TransmissionRow | None:
    """The stored row the cross-check reads, or None. In the deployed state
    this returns None for every company, because the table is empty."""
    row: Any = session.execute(text(
        "SELECT company_id, shock_variable, shock_sign, horizon, n_events, "
        "median_car, iqr_lo, iqr_hi, p_value, sign_consistency, "
        "estimator_version FROM transmission_empirical WHERE "
        "company_id = :company_id AND shock_variable = :shock_variable AND "
        "shock_sign = :shock_sign AND horizon = :horizon AND "
        "estimator_version = :estimator_version"), {
            "company_id": company_id, "shock_variable": shock_variable,
            "shock_sign": shock_sign, "horizon": horizon,
            "estimator_version": estimator_version}).mappings().first()
    if row is None:
        return None
    return TransmissionRow(
        company_id=int(row["company_id"]),
        shock_variable=str(row["shock_variable"]),
        shock_sign=str(row["shock_sign"]), horizon=str(row["horizon"]),
        n_events=int(row["n_events"]), median_car=float(row["median_car"]),
        iqr_lo=float(row["iqr_lo"]), iqr_hi=float(row["iqr_hi"]),
        p_value=float(row["p_value"]),
        sign_consistency=float(row["sign_consistency"]),
        estimator_version=str(row["estimator_version"]))
