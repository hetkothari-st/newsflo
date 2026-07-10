import json

from openai import OpenAI, RateLimitError

from app.analysis.schemas import SECTORS, AnalysisOutput

MODEL = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Precise definitions the model must use for sector inference. Ambiguity here
# (e.g. treating "semiconductor" as close enough to "it") is what causes the
# resolver to attach real reasoning about one company (say, a Korean chip
# maker) to an unrelated company that merely shares a loosely-matched sector
# tag (e.g. an Indian IT services firm). Precision here is load-bearing.
SECTOR_DEFINITIONS = """
- oil_gas: oil & gas exploration, refining, and marketing companies only.
- banking: deposit-taking banks, NBFCs, and financial services firms only.
- auto: automobile and two-wheeler manufacturers, and auto component makers.
- it: INDIAN IT SERVICES / software consulting / outsourcing firms only \
(e.g. TCS, Infosys, Wipro). Does NOT include semiconductor, chip, or \
hardware manufacturers -- those have no matching sector in this system.
- pharma: pharmaceutical and healthcare companies.
- fmcg: fast-moving consumer goods, food & beverage, personal care.
- metals: metals, mining, and materials companies.
- telecom: telecommunications and network infrastructure operators.
- infra: industrial, infrastructure, construction, and heavy equipment.
- other: none of the above.
""".strip()

SYSTEM_PROMPT = (
    "You are a senior equity research analyst with 20+ years covering Indian "
    "and global markets across every major sector -- oil & gas, banking, "
    "autos, IT services, pharma, FMCG, metals, telecom, and infrastructure. "
    "You have deep, current knowledge of real companies, their actual "
    "business models, competitive positioning, and what genuinely moves "
    "their earnings. You reason the way an experienced desk analyst does: "
    "skeptical by default, unwilling to state a causal link you can't "
    "actually defend, and comfortable saying \"nothing tradeable here\" when "
    "that's the honest read. You determine which companies are affected "
    "strictly from what THIS article says -- never from outside assumptions, "
    "general market sentiment, or what would be a plausible-sounding guess. "
    "If the article doesn't support a specific, defensible call, you don't "
    "manufacture one."
)

RECORD_ANALYSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "record_analysis",
        "description": "Record which companies are affected by this news article and how.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "companies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "ticker": {"type": ["string", "null"]},
                            "is_direct": {"type": "boolean"},
                            "sector": {"type": ["string", "null"], "enum": SECTORS + [None]},
                            "direction": {"type": "string", "enum": ["bullish", "bearish"]},
                            "magnitude_low": {"type": "number"},
                            "magnitude_high": {"type": "number"},
                            "rationale": {
                                "type": "string",
                                "description": (
                                    "Company-specific reasoning for THIS company only -- "
                                    "state the concrete mechanism (what the news changes, "
                                    "and how this company's actual, specific business is "
                                    "exposed to that change). Never reuse the same sentence "
                                    "for multiple companies in the same response."
                                ),
                            },
                        },
                        "required": ["name", "is_direct", "direction", "magnitude_low", "magnitude_high", "rationale"],
                    },
                },
            },
            "required": ["category", "companies"],
        },
    },
}


class _RotatingCompletions:
    def __init__(self, rotator: "RotatingClient"):
        self._rotator = rotator

    def create(self, **kwargs):
        return self._rotator._call(**kwargs)


class _RotatingChat:
    def __init__(self, rotator: "RotatingClient"):
        self.completions = _RotatingCompletions(rotator)


class RotatingClient:
    """Duck-types the subset of the OpenAI client surface analyze_article
    uses (client.chat.completions.create(...)), backed by multiple API keys.

    On a RateLimitError from the currently active key, tries the next key in
    the rotation before giving up -- a rate-limited key stays "current" for
    subsequent calls once another key is found to work, rather than resetting
    to the first key every time (so a working key isn't abandoned prematurely
    on the next call). Any error OTHER than a rate limit is not a rotation
    trigger -- it propagates immediately, so a genuine bug isn't masked by
    silently trying more keys.
    """

    def __init__(self, api_keys: list[str], base_url: str):
        if not api_keys:
            raise ValueError("RotatingClient requires at least one API key")
        self._clients = [OpenAI(api_key=key, base_url=base_url) for key in api_keys]
        self._active = 0
        self.chat = _RotatingChat(self)

    def _call(self, **kwargs):
        last_error: RateLimitError | None = None
        for offset in range(len(self._clients)):
            index = (self._active + offset) % len(self._clients)
            try:
                result = self._clients[index].chat.completions.create(**kwargs)
                self._active = index
                return result
            except RateLimitError as exc:
                last_error = exc
                continue
        raise last_error


def build_client(api_key: str | list[str]) -> OpenAI | RotatingClient:
    if isinstance(api_key, list):
        return RotatingClient(api_key, base_url=GROQ_BASE_URL)
    return OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)


def analyze_article(client, title: str, content: str) -> AnalysisOutput:
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=1024,
        tools=[RECORD_ANALYSIS_TOOL],
        tool_choice={"type": "function", "function": {"name": "record_analysis"}},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                "Analyze this financial news article for a trading-signal app. Accuracy "
                "matters more than coverage -- a wrong or speculative pick is worse than "
                "no pick, since real users may trade on this.\n\n"
                "RULES:\n"
                "1. Prefer companies literally named in the article, OR companies you are "
                "specifically, confidently thinking of even if not named verbatim -- set "
                "is_direct=true and put the real company name, with ticker=null if you "
                "are not sure of the exact symbol. Do NOT drop down to sector-level "
                "inference just because you lack the ticker; only use sector-level "
                "inference when you do NOT have specific companies in mind at all, only "
                "a general sense that a whole sector is affected.\n"
                "2. Only use sector-level inference (is_direct=false, sector=<value>) when "
                "the news is a genuine, PROXIMATE, sector-wide catalyst (e.g. a commodity "
                "price shock, a rate decision, a regulatory change) that plausibly moves "
                "EVERY company in that sector similarly -- not a speculative multi-step "
                "chain of reasoning.\n"
                "3. The `sector` value MUST come from this exact list, using these exact "
                "definitions -- if the real-world industry you're reasoning about does not "
                "match one of these definitions, DO NOT force it into the closest-sounding "
                "one. Omit that company/sector entirely instead:\n"
                f"{SECTOR_DEFINITIONS}\n"
                "4. Do not chain multiple unrelated sector inferences from one article "
                "(e.g. do not infer both an oil-sector effect AND an IT-sector effect from "
                "one macro/rates story unless the article is genuinely, specifically about "
                "both).\n"
                "5. List at most 5 companies total, fewer if you are not genuinely confident "
                "in more. If nothing in the article has a specific, defensible link to a "
                "real company or one of the sectors above, return an empty companies list -- "
                "that is a correct answer, not a failure.\n"
                "6. Each rationale must name the specific mechanism for THAT company -- not "
                "a sentence that would apply equally to any company in its sector.\n\n"
                f"Title: {title}\n\nContent: {content or '(no summary available -- reason only from the title, and be more conservative about sector-level inference given the limited signal)'}"
            ),
        }],
    )
    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_analysis"), None)
    if tool_call is None:
        raise ValueError(f"Claude response contained no tool_use block for article: {title!r}")
    arguments = json.loads(tool_call.function.arguments)
    return AnalysisOutput.model_validate(arguments)
