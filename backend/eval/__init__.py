"""V5 PHASE 7 -- the evaluation harness, the shipping gates and monitoring.

    eval.metrics         the metric suite (Task 7.2), pure functions
    eval.harness         the offline V5 path + the corpus join (Tasks 7.1/7.2)
    eval.shipping_gates  the runnable gate evaluator (Task 7.3)
    eval.monitoring      the production signals as functions (Task 7.4)
    eval.cascade         section 18's routing, over the deployed gate (Task 7.5)
    eval.cost_ledger     the call ledger and the stage-result cache (Task 7.5)
    eval.prompt_audit    static-prefix-before-dynamic-suffix (Task 7.5)

WHY THIS IS NOT UNDER `app/`. Nothing here is part of the product: it
measures the product. `app.eval` is Session 0's corpus schema and store (the
tables the labelers fill); this package READS those tables and never writes
them. Nothing under `app/` imports this package, and a test pins that.

THIS PACKAGE MAKES NO NETWORK CALL AND CONSTRUCTS NO MODEL CLIENT. The two
V5 stages that would call a model -- the falsifier's checklist and the
firewall's stage-2 entailment judge -- take an INJECTED client, so the
harness is offline by construction rather than by mocking.

THE CORPUS IS EMPTY. Every corpus-dependent computation here refuses loudly
on empty input rather than returning 0.0 or 1.0 (DATA_GAPS sections 1 and 11).
"""
