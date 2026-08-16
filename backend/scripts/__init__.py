"""Operational scripts that are run, not imported by the application.

``scripts.score_baseline`` is importable (pytest.ini puts backend/ on the
path) so its metric functions can be tested directly instead of only
through the CLI.
"""
