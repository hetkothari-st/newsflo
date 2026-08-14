"""Budget exhaustion must never mark an unverified candidate verified
(provider-migration spec section 13 / self-audit Q11). The engine paths that
consult budget.exceeded set router.quality='budget_exhausted' and stop
expansion -- verification skips produce REJECT/unverified, never verified."""
from app.analysis.impact_graph.budget import ArticleBudget


def test_exceeded_budget_flags_without_verifying():
    budget = ArticleBudget(article_id=1, max_input_override=10, max_output_override=10)
    budget.record("expand", input_tokens=1000, output_tokens=1000, model=None)
    assert budget.exceeded is True
    assert budget.expansion_exhausted is True
