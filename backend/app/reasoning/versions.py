"""Version stamps logged on every Alert so any analysis can be traced back to
exactly which prompt/rulebook version produced it -- enough for debugging and
future A/B comparison without a full prompt-registry service. Bump these
whenever ANALYSIS_INSTRUCTIONS or the rulebook/playbook content changes
meaningfully; never edit history, only add a new version string.
"""

PROMPT_VERSION = "2026.07.30-reasoning-v4"  # elite-analyst discipline: event classification first, precise causal chains, relationship-graph company selection, institutional same-day reality check, narrow-event ripple suppression
KNOWLEDGE_VERSION = "2026.07.27-rulebook-v2"
