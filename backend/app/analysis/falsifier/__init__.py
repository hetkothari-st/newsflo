"""V5 PHASE 6 / spec §12 -- THE FALSIFICATION STAGE.

An ADVERSARY, not a verifier. The V4 "verifier" confirms; this component's
objective is to DESTROY the candidate, and it runs BEFORE the reducer as a
signal producer -- it decides nothing, it raises objections and the reducer
folds them.

    from app.analysis.falsifier import Falsifier, load_falsifier_config

    falsifier = Falsifier(client=client, policy=load_falsifier_config(),
                          generator_provider=..., generator_model_id=...,
                          generator_prompt_lineage=...)
    result = falsifier.run(record_set)
    signals = falsifier.signals(result, event_id=..., company_id=...,
                                analysis_version=..., created_at=...)

THREE STRUCTURAL RULES, none of them a matter of prompting:

1. THE CLIENT IS INJECTED. Nothing in this package constructs a client,
   imports a provider SDK or reads an API key; the seam is one method wide
   (`client.generate(prompt) -> str`), so a stub is a complete
   implementation and the test suite makes zero network calls BY
   CONSTRUCTION.
2. THE OUTPUT IS A SIGNAL, NEVER A VERDICT. This package cannot write
   `company_impact` (the database refuses it) and does not evaluate a gate.
3. IT CANNOT ANSWER ITSELF. Nothing here emits a REBUTTAL -- ast-asserted by
   `tests/phase6/test_falsifier.py`. Rebuttals come from the stages that
   HOLD the cited data (`app.analysis.rebuttal`), and the reducer discards
   any rebuttal from the stage that raised the objection anyway.

WHAT IS NOT WIRED. The falsifier is not called from `app/pipeline.py`. V5
has no serving path (the standing Phase 0 ruling) and the live V4 path has
no record set of the shape §12.2 requires; wiring an adversary that objects
to every V4 entry would silently empty the live feed. It runs on the
canonical record when the canonical path runs.
"""
from app.analysis.falsifier.config import (  # noqa: F401
    FalsifierConfigError, FalsifierPolicy, load_falsifier_config, validate_policy,
)
from app.analysis.falsifier.engine import (  # noqa: F401
    Falsifier, FalsifierResult, ModelDiscipline, Objection,
)
