"""V5 PHASE 5 -- calibrated confidence (spec §13). DISABLED, AND UNABLE TO
ACTIVATE.

    calibrated_p = P(the published directional call at the headline horizon is
                     judged CORRECT by expert review)

Everything §13 asks for is built here: the deterministic feature vector, the
isotonic fit, the reliability diagram, ECE and Brier, and the Mahalanobis
out-of-distribution gate. NONE OF IT IS ON, and none of it can be switched on
by editing a flag:

  * `config/calibration.yaml` ships `enabled: false`;
  * activation needs a labeled corpus above a configured minimum, and there is
    no labeled corpus (DATA_GAPS §1);
  * `calibration_model.is_active` carries a CHECK constraint pinning it to 0,
    so an ACTIVE row cannot exist without a migration;
  * `registry.record_model` refuses a model fitted on `_fixture` labels.

That is the phase file's own instruction, made structural: "until the corpus
exists, ship with calibration disabled and calibrated_p = null... do not ship
a fitted-looking model trained on synthetic labels."

NO MODEL SCORE IS A FEATURE. Every input to the vector is a number this system
computed or a category it assigned. `tests/phase5/test_calibration.py`
ast-scans this package against every provider module in the repo and ratchets
the count of confidence-asking prompt templates elsewhere.
"""
