"""TASK 7.2 tests -- the metric suite, one arithmetic proof per metric.

Every metric here is a PURE function over (labels, V5 outputs). The corpus is
empty, so what is tested is the ARITHMETIC: hand-counted fixture pairs whose
expected numerator and denominator are written into the test, not read off
the implementation.

TWO RULES THE WHOLE FILE ENFORCES:

  * a rate with a zero denominator is `None`. Not 0.0, not 1.0. "We measured
    nothing" and "we measured perfectly" are different sentences and a
    harness that confuses them is worse than no harness;
  * every metric is reported PER STRATUM and PER SECTOR as well as in
    aggregate (Task 7.2's last line: an aggregate number hides that you are
    excellent on crude and useless on policy). The grouping is tested, not
    assumed.
"""
import pytest


def pair(**kwargs):
    from eval.metrics import ScoredPair

    base = dict(
        event_id="fx-1", stratum="commodity", sector="fixture_energy",
        company_ref="FIXA", expected_tier="ABSENT", published_tier="ABSENT",
        expected_direction=None, published_direction=None,
        expected_mechanism=None, published_mechanism=None,
        expected_materiality=None, published_materiality=None,
        expected_section=None, published_section=None,
        expected_directness=None, published_directness=None,
        expected_distance=None, published_distance=None,
        expected_evidence=None, published_evidence=None,
        cross_model=None)
    base.update(kwargs)
    return ScoredPair(**base)


# ---------------------------------------------------------------------------
# the rate primitive
# ---------------------------------------------------------------------------

def test_a_rate_with_no_denominator_is_none_not_zero_and_not_one():
    from eval.metrics import Rate

    empty = Rate(0, 0)
    assert empty.value is None
    assert empty.value != 0.0
    assert Rate(3, 4).value == 0.75


def test_a_rate_renders_its_own_denominator():
    from eval.metrics import Rate

    assert "0" in Rate(0, 0).describe()
    assert Rate(0, 0).describe().lower().count("no") >= 1


# ---------------------------------------------------------------------------
# tier precision / recall
# ---------------------------------------------------------------------------

def test_primary_precision_and_recall_are_hand_counted():
    from eval.metrics import tier_precision_recall

    pairs = [
        pair(company_ref="A", expected_tier="PRIMARY", published_tier="PRIMARY"),
        pair(company_ref="B", expected_tier="PRIMARY", published_tier="PRIMARY"),
        pair(company_ref="C", expected_tier="PRIMARY", published_tier="PRIMARY"),
        pair(company_ref="D", expected_tier="ABSENT", published_tier="PRIMARY"),
        pair(company_ref="E", expected_tier="PRIMARY", published_tier="ABSENT"),
        pair(company_ref="F", expected_tier="PRIMARY",
             published_tier="SECONDARY_RIPPLE"),
    ]
    result = tier_precision_recall(pairs, "PRIMARY")
    assert (result.tp, result.fp, result.fn) == (3, 1, 2)
    assert result.precision.value == 0.75
    assert result.recall.value == 0.6


def test_secondary_ripple_precision_and_recall_are_separate_from_primary():
    from eval.metrics import tier_precision_recall

    pairs = [
        pair(company_ref="A", expected_tier="SECONDARY_RIPPLE",
             published_tier="SECONDARY_RIPPLE"),
        pair(company_ref="B", expected_tier="SECONDARY_RIPPLE",
             published_tier="ABSENT"),
        pair(company_ref="C", expected_tier="PRIMARY",
             published_tier="SECONDARY_RIPPLE"),
    ]
    result = tier_precision_recall(pairs, "SECONDARY_RIPPLE")
    assert (result.tp, result.fp, result.fn) == (1, 1, 1)
    assert result.precision.value == 0.5
    assert result.recall.value == 0.5


def test_an_excluded_pair_is_in_no_denominator():
    """DISPUTED / unresolved -> expected_tier None -> the pair is dropped."""
    from eval.metrics import tier_precision_recall

    pairs = [
        pair(company_ref="A", expected_tier="PRIMARY", published_tier="PRIMARY"),
        pair(company_ref="B", expected_tier=None, published_tier="PRIMARY"),
    ]
    result = tier_precision_recall(pairs, "PRIMARY")
    assert (result.tp, result.fp, result.fn) == (1, 0, 0)
    assert result.excluded == 1
    assert result.precision.value == 1.0


def test_precision_over_nothing_published_is_none():
    from eval.metrics import tier_precision_recall

    result = tier_precision_recall([pair(expected_tier="ABSENT")], "PRIMARY")
    assert result.precision.value is None
    assert result.recall.value is None


# ---------------------------------------------------------------------------
# direction, effect, and the rest of the accuracy family
# ---------------------------------------------------------------------------

def test_wrong_direction_rate_counts_only_opposed_directional_claims():
    from eval.metrics import wrong_direction_rate

    pairs = [
        # counted, wrong
        pair(company_ref="A", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_direction="bearish", published_direction="POSITIVE"),
        # counted, right
        pair(company_ref="B", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_direction="bearish", published_direction="NEGATIVE"),
        # NOT counted: the label states no direction
        pair(company_ref="C", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_direction=None, published_direction="NEGATIVE"),
        # NOT counted: the system published MIXED, which is not a direction
        # and must never be scored as one (invariant 9)
        pair(company_ref="D", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_direction="bearish", published_direction="MIXED"),
        # NOT counted: not published PRIMARY
        pair(company_ref="E", expected_tier="PRIMARY", published_tier="ABSENT",
             expected_direction="bearish", published_direction="POSITIVE"),
    ]
    rate = wrong_direction_rate(pairs, tier="PRIMARY")
    assert (rate.numerator, rate.denominator) == (1, 2)
    assert rate.value == 0.5


def test_a_mixed_expectation_never_scores_as_a_wrong_direction():
    from eval.metrics import wrong_direction_rate

    pairs = [pair(company_ref="A", expected_tier="PRIMARY", published_tier="PRIMARY",
                  expected_direction="mixed", published_direction="NEGATIVE")]
    rate = wrong_direction_rate(pairs, tier="PRIMARY")
    assert rate.denominator == 0
    assert rate.value is None


def test_economic_effect_accuracy_maps_the_label_vocabulary():
    from eval.metrics import economic_effect_accuracy

    pairs = [
        pair(company_ref="A", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_direction="bullish", published_direction="POSITIVE"),
        pair(company_ref="B", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_direction="mixed", published_direction="MIXED"),
        pair(company_ref="C", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_direction="bearish", published_direction="POSITIVE"),
    ]
    rate = economic_effect_accuracy(pairs)
    assert (rate.numerator, rate.denominator) == (2, 3)


@pytest.mark.parametrize("metric_name,expected_field,published_field", [
    ("mechanism_accuracy", "expected_mechanism", "published_mechanism"),
    ("materiality_accuracy", "expected_materiality", "published_materiality"),
    ("directness_accuracy", "expected_directness", "published_directness"),
    ("distance_accuracy", "expected_distance", "published_distance"),
    ("evidence_accuracy", "expected_evidence", "published_evidence"),
    ("section_accuracy", "expected_section", "published_section"),
])
def test_each_accuracy_metric_counts_only_pairs_the_label_states(
        metric_name, expected_field, published_field):
    import eval.metrics as metrics

    metric = getattr(metrics, metric_name)
    pairs = [
        pair(company_ref="A", expected_tier="PRIMARY", published_tier="PRIMARY",
             **{expected_field: "X", published_field: "X"}),
        pair(company_ref="B", expected_tier="PRIMARY", published_tier="PRIMARY",
             **{expected_field: "X", published_field: "Y"}),
        # the label says nothing -> not a miss, not a hit, not in the
        # denominator. The corpus schema carries no expected directness,
        # distance, evidence or section, so in the deployed harness this is
        # EVERY pair and the metric is None.
        pair(company_ref="C", expected_tier="PRIMARY", published_tier="PRIMARY",
             **{expected_field: None, published_field: "Y"}),
    ]
    rate = metric(pairs)
    assert (rate.numerator, rate.denominator) == (1, 2)
    assert metric([pair()]).value is None


# ---------------------------------------------------------------------------
# the null slice
# ---------------------------------------------------------------------------

def test_abstention_precision_over_null_events():
    from eval.metrics import abstention_precision

    events = [
        {"stratum": "null_event", "primary_count": 0},
        {"stratum": "null_event", "primary_count": 0},
        {"stratum": "null_event", "primary_count": 1},
        {"stratum": "commodity", "primary_count": 3},
    ]
    rate = abstention_precision(events)
    assert (rate.numerator, rate.denominator) == (2, 3)


def test_abstention_precision_with_no_null_events_is_none():
    from eval.metrics import abstention_precision

    assert abstention_precision([{"stratum": "commodity", "primary_count": 1}]).value is None


def test_primary_false_positives_on_null_events_is_a_count_not_a_rate():
    """The hard-zero gate reads a COUNT. One is one, whatever the corpus
    size, and dividing it by 300 would make it look small."""
    from eval.metrics import null_event_primary_false_positives

    events = [
        {"stratum": "null_event", "primary_count": 0},
        {"stratum": "null_event", "primary_count": 2},
        {"stratum": "commodity", "primary_count": 5},
    ]
    assert null_event_primary_false_positives(events) == 2


# ---------------------------------------------------------------------------
# ripple families
# ---------------------------------------------------------------------------

def test_ripple_family_recall_is_measured_against_the_expected_map():
    from eval.metrics import ripple_family_recall

    rate = ripple_family_recall(
        [{"event_id": "fx-1", "expected": ("refining", "paints", "tyres"),
          "published": ("refining", "paints")}])
    assert (rate.numerator, rate.denominator) == (2, 3)


def test_ripple_family_recall_with_no_expectation_is_none():
    from eval.metrics import ripple_family_recall

    assert ripple_family_recall([{"event_id": "fx", "expected": (),
                                  "published": ("refining",)}]).value is None


# ---------------------------------------------------------------------------
# integrity metrics
# ---------------------------------------------------------------------------

def test_firewall_deletion_rate_is_per_sentence_on_the_named_tier():
    from eval.metrics import firewall_deletion_rate

    outputs = [
        {"publication_tier": "PRIMARY", "sentences_total": 4, "deletions": 0},
        {"publication_tier": "PRIMARY", "sentences_total": 6, "deletions": 1},
        {"publication_tier": "SECONDARY_RIPPLE", "sentences_total": 5, "deletions": 5},
    ]
    rate = firewall_deletion_rate(outputs, tier="PRIMARY")
    assert (rate.numerator, rate.denominator) == (1, 10)


def test_fabricated_numeral_rate_uses_set_membership_not_substrings():
    """37 does NOT appear in 1370. Session 0 fixed this once; the harness
    must not reintroduce it, because it feeds a hard-zero gate."""
    from eval.metrics import fabricated_numeral_rate, fabricated_numerals

    assert fabricated_numerals("margin fell 37 bps", ("1370",)) == ["37"]
    assert fabricated_numerals("share of 28 percent", ("28", "1370")) == []
    rate = fabricated_numeral_rate([
        {"prose": "share of 28 percent", "record_numerals": ("28",)},
        {"prose": "margin fell 37 bps", "record_numerals": ("1370",)},
    ])
    assert (rate.numerator, rate.denominator) == (1, 2)


def test_a_rounded_numeral_is_not_fabricated():
    from eval.metrics import fabricated_numerals

    assert fabricated_numerals("a 3.50 point move", ("3.5",)) == []
    assert fabricated_numerals("1,370 crore", ("1370",)) == []


def test_internal_contradiction_rate_counts_records_not_contradictions():
    from eval.metrics import internal_contradiction_rate

    records = [
        {"publication_tier": "PRIMARY", "net_effect": "NEGATIVE",
         "sign_consistency": 0.9, "rejection_reason": None,
         "direction_by_horizon": {"NEAR_TERM": {"direction": "NEGATIVE"}}},
        # two contradictions in one record, still ONE contradicting record
        {"publication_tier": "PRIMARY", "net_effect": "NEGATIVE",
         "sign_consistency": 0.2, "rejection_reason": "SOMETHING",
         "direction_by_horizon": {"NEAR_TERM": {"direction": "POSITIVE"}}},
    ]
    rate = internal_contradiction_rate(records)
    assert (rate.numerator, rate.denominator) == (1, 2)


@pytest.mark.parametrize("record,expected", [
    ({"publication_tier": "PRIMARY", "net_effect": "NEGATIVE",
      "sign_consistency": 0.2, "rejection_reason": None,
      "direction_by_horizon": {}}, "DIRECTIONAL_CLAIM_BELOW_SIGN_CONSISTENCY"),
    ({"publication_tier": "PRIMARY", "net_effect": "NEGATIVE",
      "sign_consistency": 0.9, "rejection_reason": "NO_MATERIAL_IMPACT",
      "direction_by_horizon": {}}, "PUBLISHED_WITH_A_REJECTION_REASON"),
    ({"publication_tier": "REJECTED", "net_effect": "NEGATIVE",
      "sign_consistency": 0.9, "rejection_reason": None,
      "direction_by_horizon": {}}, "REJECTED_WITHOUT_A_REASON"),
    ({"publication_tier": "PRIMARY", "net_effect": "NEGATIVE",
      "sign_consistency": 0.9, "rejection_reason": None,
      "direction_by_horizon": {"NEAR_TERM": {"direction": "POSITIVE"}}},
     "HEADLINE_CONTRADICTS_ITS_HORIZONS"),
])
def test_each_contradiction_is_named(record, expected):
    from eval.metrics import internal_contradictions

    assert expected in internal_contradictions(record)


def test_a_consistent_record_has_no_contradictions():
    from eval.metrics import internal_contradictions

    assert internal_contradictions({
        "publication_tier": "PRIMARY", "net_effect": "MIXED",
        "sign_consistency": 0.5, "rejection_reason": None,
        "direction_by_horizon": {"NEAR_TERM": {"direction": "MIXED"}}}) == ()


# ---------------------------------------------------------------------------
# calibration -- machinery only, calibration is disabled
# ---------------------------------------------------------------------------

def test_calibration_delegates_to_the_phase_five_implementation():
    import eval.metrics as metrics
    from app.analysis.calibration import metrics as calibration

    assert metrics.calibration_ece.__wrapped_metric__ is \
        calibration.expected_calibration_error
    assert metrics.calibration_brier.__wrapped_metric__ is calibration.brier_score


def test_calibration_over_no_probabilities_is_none_not_zero():
    from eval.metrics import calibration_brier, calibration_ece

    assert calibration_ece([]) is None
    assert calibration_brier([]) is None


def test_calibration_arithmetic_on_fixture_pairs():
    from eval.metrics import calibration_brier

    # ((0.0-0)^2 + (1.0-1)^2) / 2 == 0.0
    assert calibration_brier([(0.0, 0), (1.0, 1)]) == 0.0
    # ((0.5-0)^2 + (0.5-1)^2) / 2 == 0.25
    assert calibration_brier([(0.5, 0), (0.5, 1)]) == 0.25


# ---------------------------------------------------------------------------
# same-model vs cross-model (section 12.4, the fields Phase 6 records)
# ---------------------------------------------------------------------------

def test_verification_precision_splits_by_cross_model():
    from eval.metrics import verification_precision_split

    pairs = [
        pair(company_ref="A", expected_tier="PRIMARY", published_tier="PRIMARY",
             cross_model=True),
        pair(company_ref="B", expected_tier="ABSENT", published_tier="PRIMARY",
             cross_model=True),
        pair(company_ref="C", expected_tier="PRIMARY", published_tier="PRIMARY",
             cross_model=False),
        pair(company_ref="D", expected_tier="PRIMARY", published_tier="PRIMARY",
             cross_model=None),
    ]
    split = verification_precision_split(pairs, "PRIMARY")
    assert split["CROSS_MODEL"].precision.value == 0.5
    assert split["SAME_MODEL"].precision.value == 1.0
    assert split["UNVERIFIED"].precision.value == 1.0


def test_the_split_reports_none_for_a_class_with_no_verification():
    from eval.metrics import verification_precision_split

    split = verification_precision_split(
        [pair(expected_tier="PRIMARY", published_tier="PRIMARY", cross_model=False)],
        "PRIMARY")
    assert split["CROSS_MODEL"].precision.value is None


# ---------------------------------------------------------------------------
# per-stratum and per-sector reporting (Task 7.2's last line)
# ---------------------------------------------------------------------------

def test_metrics_are_reported_per_stratum_and_per_sector():
    from eval.metrics import group_by, tier_precision_recall

    pairs = [
        pair(company_ref="A", stratum="commodity", sector="fixture_energy",
             expected_tier="PRIMARY", published_tier="PRIMARY"),
        pair(company_ref="B", stratum="policy_regulatory", sector="fixture_energy",
             expected_tier="ABSENT", published_tier="PRIMARY"),
        pair(company_ref="C", stratum="policy_regulatory", sector="fixture_banks",
             expected_tier="ABSENT", published_tier="PRIMARY"),
    ]
    by_stratum = group_by(pairs, "stratum",
                          lambda group: tier_precision_recall(group, "PRIMARY"))
    assert by_stratum["commodity"].precision.value == 1.0
    assert by_stratum["policy_regulatory"].precision.value == 0.0

    by_sector = group_by(pairs, "sector",
                         lambda group: tier_precision_recall(group, "PRIMARY"))
    assert by_sector["fixture_energy"].precision.value == 0.5
    assert by_sector["fixture_banks"].precision.value == 0.0


def test_an_aggregate_only_report_is_impossible():
    """The report object cannot be built without its per-stratum and
    per-sector breakdowns -- Task 7.2's DO NOT, structurally."""
    from eval.metrics import MetricReport

    fields = set(MetricReport.__dataclass_fields__)
    assert "per_stratum" in fields and "per_sector" in fields
    with pytest.raises(TypeError):
        MetricReport(aggregate={})


# ---------------------------------------------------------------------------
# mechanism_accuracy compares NODE IDS, so it normalizes like the writer does
# ---------------------------------------------------------------------------

def test_mechanism_accuracy_scores_a_label_written_in_the_REGISTRY_dialect():
    """`expected_mechanism` is what a human labeler typed -- and a labeler
    reads `knowledge.MECHANISMS`, so they type "paints_input_cost".
    `published_mechanism` is `company_impact.mechanism_id`, a normalized node
    id: "paint_input_cost". An upper-cased exact compare scored that as a
    MISS, on 9 of the 42 mechanisms, in a metric that feeds
    `eval/shipping_gates.py`."""
    from eval.metrics import mechanism_accuracy

    rate = mechanism_accuracy([
        pair(company_ref="A", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_mechanism="paints_input_cost",
             published_mechanism="paint_input_cost"),
        pair(company_ref="B", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_mechanism="capital_goods_orders",
             published_mechanism="capital_good_order"),
        pair(company_ref="C", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_mechanism="freight_rate_spike",
             published_mechanism="freight_rate_up"),
    ])
    assert (rate.numerator, rate.denominator) == (3, 3)


def test_mechanism_accuracy_still_scores_two_different_mechanisms_as_a_miss():
    """The anti-vacuity half: normalizing both sides must not make every
    comparison succeed."""
    from eval.metrics import mechanism_accuracy

    rate = mechanism_accuracy([
        pair(company_ref="A", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_mechanism="paints_input_cost",
             published_mechanism="aviation_fuel_cost"),
        pair(company_ref="B", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_mechanism="upstream_realization",
             published_mechanism="refiner_marketing_margin"),
    ])
    assert (rate.numerator, rate.denominator) == (0, 2)


def test_the_other_attribute_metrics_do_not_normalize_as_node_ids():
    """The comparator for tier / materiality / directness / evidence /
    section stays an ENUM case-fold. Running those through
    `normalize_node_id` would be the same defect in the other direction: it
    singularizes, drops noise words and hoists DIRECTION words, so
    "HIGHER" -- a direction word with nothing left beside it -- collapses to
    the placeholder id "node", and "HIGH" does not. A controlled vocabulary
    is not a node id."""
    from eval.metrics import materiality_accuracy

    rate = materiality_accuracy([
        pair(company_ref="A", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_materiality="high", published_materiality="HIGH"),
        pair(company_ref="B", expected_tier="PRIMARY", published_tier="PRIMARY",
             expected_materiality="HIGH", published_materiality="HIGHER"),
    ])
    assert (rate.numerator, rate.denominator) == (1, 2)
