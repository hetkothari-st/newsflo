"""The deterministic junk gate in front of the relevance LLM call.

Every test here is really one of two assertions: junk of a recognised
FORMAT never costs a call, and everything else -- especially anything that
merely looks like that format -- still reaches the LLM. The second set is
the load-bearing one. A missed junk headline costs one cheap call; a
wrongly filtered headline removes a real story from the feed with nothing
to notice it by.
"""
import json
from types import SimpleNamespace

from app.filtering.junk import (
    ADMIT, JUNK, JUNK_PATTERNS, is_junk, junk_verdict, matching_junk_pattern,
)
from app.filtering.relevance import filter_new_articles
from app.models import Article

# --- the exact titles measured in production that must never reach the LLM ---

# UK Takeover Code Rule 8 dealing disclosures, as the wires emit them.
FORM_8_JUNK = [
    "Man Group PLC : Form 8.3 - JTC Plc",
    "Dimensional Fund Advisors Ltd. : Form 8.3 - PROLOGIS INC - Ordinary Shares",
    "Form 8.3 - [GOOCH & HOUSEGO PLC - 04 08 2026] - (CGWL)",
    "Form 8.3 - [ADVANCED MEDICAL SOLUTIONS GROUP PLC - 04 08 2026] - (CGAML)",
]

# Award PR, with the body it actually ships with -- an empty body would be
# a weaker test, since the veto scans the body too and a realistic award
# release is exactly where a stray financial word might hide.
AWARD_JUNK = [
    (
        "Goranson Bain Ausley Named Best Family Law Firm in Texas Lawyer's Best Of",
        "Goranson Bain Ausley has been named Best Family Law Firm in the annual "
        "Texas Lawyer's Best Of survey. The firm was selected by readers across "
        "the state. 'We are honored by this recognition,' a partner said.",
    ),
]


def test_form_8_dealing_disclosures_are_filtered():
    for title in FORM_8_JUNK:
        verdict, reason = junk_verdict(title, "")
        assert verdict == JUNK, f"expected junk for {title!r} ({reason})"
        assert matching_junk_pattern(title).name == "uk_takeover_code_form_8"


def test_form_8_variants_beyond_8_3_are_filtered():
    # Rule 8 has several forms: 8.1 (a party to the offer), 8.3 (a 1%+
    # holder), 8.5 (an exempt principal trader). All are the same document
    # class and all must be filtered, not just the 8.3 seen most often.
    for title in [
        "Form 8.1 - Alpha PLC",
        "Form 8.5 (EPT/RI) - Beta Group PLC",
        "Barclays PLC : Form 8.5 (EPT/NON-RI) - Gamma Holdings",
    ]:
        assert junk_verdict(title, "")[0] == JUNK, title


def test_award_press_releases_are_filtered():
    for title, content in AWARD_JUNK:
        verdict, reason = junk_verdict(title, content)
        assert verdict == JUNK, f"expected junk for {title!r} ({reason})"


def test_more_award_shapes_are_filtered():
    for title in [
        "Acme Legal Wins 2026 Best Workplace Award",
        "Beta Advisors Recognized as a Leader in Client Service",
        "Gamma Named One of the Top Places to Work",
        "Delta Ranked #1 in Customer Satisfaction",
    ]:
        assert junk_verdict(title, "")[0] == JUNK, title


# --- what must NEVER be filtered ---

# The six production titles the user requires to keep reaching analysis.
MUST_REACH_ANALYSIS = [
    "Modi seeks sweeping tax cuts for global funds",
    "SpaceX's first earnings offer a chance to reverse stock's plunge",
    "Stocks get AI-boost; investors on tenterhooks over Mideast peace talks",
    "Gulf shipping traffic steady amid uncertainty of peace talks",
    "Utz Brands Reports Second Quarter 2026 Results",
    "Eton Pharmaceuticals Expands Infantile Hemangioma Franchise with Acquisition",
]


def test_every_required_keep_title_passes_untouched():
    for title in MUST_REACH_ANALYSIS:
        verdict, reason = junk_verdict(title, "")
        assert verdict == ADMIT, f"REGRESSION: {title!r} would be dropped ({reason})"
        assert is_junk(title, "") is False


def test_adversarial_near_misses_pass():
    """Headlines built to trip each pattern that are real news anyway."""
    for title in [
        # A US SEC filing, hyphenated, and a genuine material-events document.
        "Company X to file Form 10-K amid restatement",
        "Acme Corp files Form 8-K disclosing CEO departure",
        # "Form 8.3" present but not in disclosure position -- a story ABOUT
        # the filings, which is news.
        "Takeover Panel probes late Form 8.3 disclosures by hedge funds",
        "Investors criticise Form 8.3 reporting burden, FCA reviews rules",
        # Award vocabulary attached to a real financial event.
        "Award-winning fund manager warns on rate cuts",
        "Ranked #1 exporter reports record quarter",
        "Acme wins $400m defence contract award",
        "Beta Bank named top pick by analysts after upgrade",
        "Gamma recognized as systemically important, faces higher capital rules",
    ]:
        verdict, reason = junk_verdict(title, "")
        assert verdict == ADMIT, f"REGRESSION: {title!r} would be dropped ({reason})"


def test_empty_and_missing_titles_are_admitted():
    # An unparseable or absent headline is a reason to let the LLM look, not
    # a reason to drop the article.
    assert junk_verdict("", "")[0] == ADMIT
    assert junk_verdict(None, None)[0] == ADMIT


def test_financial_event_in_the_body_vetoes_an_award_headline():
    title = "Acme Named One of the Top Employers"
    assert junk_verdict(title, "")[0] == JUNK
    assert junk_verdict(title, "Separately, Acme raised its full-year revenue guidance.")[0] == ADMIT


def test_form_8_is_not_vetoed_by_its_own_boilerplate():
    # Load-bearing: every Rule 8 disclosure names shares and percentages, so
    # a financial-signal veto on this pattern would make it a permanent
    # no-op. The anchoring is what keeps it safe instead.
    title = "Man Group PLC : Form 8.3 - JTC Plc"
    body = "Class of relevant security: Ordinary Shares. Percentage: 1.24%. Total: 3,000,000 shares."
    assert junk_verdict(title, body)[0] == JUNK


def test_every_pattern_is_named_and_documented():
    # The pattern list is the extension point; a nameless entry would show
    # up in a production log line as an unidentifiable filter decision.
    names = [pattern.name for pattern in JUNK_PATTERNS]
    assert len(names) == len(set(names)), "junk pattern names must be unique"
    assert all(name and name.strip() for name in names)


# --- wiring into filter_new_articles ---

def _counting_client(calls: list):
    def create(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(tool_calls=[SimpleNamespace(
            function=SimpleNamespace(name="record_relevance", arguments=json.dumps({"relevant": True})),
        )])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_junk_article_is_filtered_without_an_llm_call(db_session):
    junk = Article(source="s", url="u1", title="Form 8.3 - [ACME PLC - 04 08 2026] - (CGWL)", content="Ordinary Shares.")
    real = Article(source="s", url="u2", title="Utz Brands Reports Second Quarter 2026 Results",
                   content="Net sales rose 4% to $400 million.")
    db_session.add_all([junk, real])
    db_session.commit()

    calls = []
    filter_new_articles(db_session, _counting_client(calls))

    assert junk.status == "FILTERED"
    assert real.status == "CATEGORIZED"
    assert len(calls) == 1, "the junk article must not have cost a classification call"
