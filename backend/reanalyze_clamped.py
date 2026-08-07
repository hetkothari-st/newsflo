"""One-off wrapper: run reanalyze_cascade.py with every LLM call's
max_tokens clamped to 4096.

Why: Groq's FREE-tier orgs count prompt + requested max_tokens against
the per-minute ceiling, so the company stage's max_tokens=8192 pushes an
~3k-token prompt to an 11k+ "requested" size and 413s on gpt-oss-20b's
8,000 TPM -- even though the actual response needs only ~2-3k tokens.
The paid production org bills differently, which is why the live
pipeline never sees this. Clamping the response budget (NOT the prompt,
NOT the models, NOT the analysis logic) makes the identical request fit.

Usage: python reanalyze_clamped.py --alert-id 1547 --force
(with GROQ_API_KEY etc. in the environment, same as reanalyze_cascade)
"""
import runpy
import sys

import app.analysis.claude_client as claude_client

_MAX_TOKENS = 4096


class _ClampedCompletions:
    def __init__(self, inner):
        self._inner = inner

    def create(self, **kwargs):
        if kwargs.get("max_tokens", 0) > _MAX_TOKENS:
            kwargs["max_tokens"] = _MAX_TOKENS
        return self._inner.create(**kwargs)


class _ClampedChat:
    def __init__(self, inner):
        self.completions = _ClampedCompletions(inner.completions)


class _ClampedClient:
    def __init__(self, inner):
        self._inner = inner
        self.chat = _ClampedChat(inner.chat)


_original_build_client = claude_client.build_client


def _clamped_build_client(*args, **kwargs):
    return _ClampedClient(_original_build_client(*args, **kwargs))


claude_client.build_client = _clamped_build_client

# reanalyze_cascade's own `from ... import build_client` resolves at ITS
# import time, which happens inside run_path -- after the patch above.
sys.argv[0] = "reanalyze_cascade.py"
runpy.run_path("reanalyze_cascade.py", run_name="__main__")
