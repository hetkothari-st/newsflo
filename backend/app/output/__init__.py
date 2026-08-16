"""V5 output layer (docs/v5/01_PHASE_0_canonical_truth.md Task 0.6).

Prose is COMPILED from records, never written by a model:

    CompanyImpact + Claims -> compiler (deterministic templates)
                           -> optional LLM fluency pass (rewrite only)
                           -> entailment firewall (delete, never repair)

Both modules here are LLM-free by construction: the optional rewriter and
the stage-2 entailment judge are INJECTED by the caller, so neither module
can build a client and no test can accidentally reach the network.
"""
