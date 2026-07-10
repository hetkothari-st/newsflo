import json
from types import SimpleNamespace

from anthropic import Anthropic
from anthropic import APIError as AnthropicAPIError
from openai import OpenAI, RateLimitError

from app.analysis.schemas import SECTORS, AnalysisOutput

# Anthropic is the primary provider when a real (funded) key is configured --
# best quality, native forced tool-use. Groq is the fallback so a real,
# funded key is never wasted on calls that a free provider could have
# served, and so the app keeps working if Anthropic's own rate limit is hit.
ANTHROPIC_MODEL = "claude-sonnet-4-5"

MODEL = "llama-3.3-70b-versatile"
# Groq enforces daily token quotas PER MODEL, not per key -- multiple keys on
# the same org share one quota bucket for a given model (confirmed: 3 keys
# from the same org all hit the same "org_..." rate-limit error for MODEL at
# the same time). FALLBACK_MODEL is a smaller model with its own SEPARATE
# quota bucket, used only when MODEL is rate-limited -- best quality when
# available, still available (slightly less reliable on strict schema
# adherence) when the primary model's daily budget is exhausted.
FALLBACK_MODEL = "llama-3.1-8b-instant"
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
                                    "Company-specific reasoning for THIS company only, drawing "
                                    "on what you actually know about it -- its specific role "
                                    "within its business (e.g. upstream producer vs refiner vs "
                                    "distributor vs miner -- never assume every company in a "
                                    "sector plays the same role), its market positioning (e.g. "
                                    "market leader vs smaller player, export-oriented vs "
                                    "domestic-focused, balance-sheet strength), and, when you "
                                    "genuinely know of one, a relevant precedent (how this "
                                    "company or a directly comparable one actually moved on a "
                                    "similar past event). Never write a sentence generic enough "
                                    "that it could be copy-pasted onto a different company in "
                                    "the same sector -- if you catch yourself doing that, you "
                                    "need is_direct=true with an actually distinct mechanism "
                                    "per company, not a shared sector-level rationale."
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


class _AnthropicCompletions:
    """Translates an OpenAI-shape chat.completions.create(...) call into a
    native Anthropic messages.create(...) call and translates the response
    back into the OpenAI response shape -- so analyze_article's parsing code
    (response.choices[0].message.tool_calls[...]) works unchanged for either
    provider. The `model` kwarg passed in is ignored; this always calls
    ANTHROPIC_MODEL, since callers pass Groq model names meant for the Groq
    path.
    """

    def __init__(self, anthropic_client: Anthropic):
        self._client = anthropic_client

    def create(self, *, max_tokens, tools, messages, **_ignored):
        system_content = None
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system_content = m["content"]
            else:
                chat_messages.append({"role": m["role"], "content": m["content"]})

        function_spec = tools[0]["function"]
        anthropic_tool = {
            "name": function_spec["name"],
            "description": function_spec["description"],
            "input_schema": function_spec["parameters"],
        }

        response = self._client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system_content,
            tools=[anthropic_tool],
            tool_choice={"type": "tool", "name": anthropic_tool["name"]},
            messages=chat_messages,
        )
        tool_use = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use is None:
            fake_tool_calls = []
        else:
            fake_tool_calls = [SimpleNamespace(
                function=SimpleNamespace(name=tool_use.name, arguments=json.dumps(tool_use.input)),
            )]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=fake_tool_calls))])


class _AnthropicChat:
    def __init__(self, anthropic_client: Anthropic):
        self.completions = _AnthropicCompletions(anthropic_client)


class AnthropicAdapter:
    """Duck-types the OpenAI client surface analyze_article uses, backed by
    the native Anthropic SDK, so the rest of the pipeline never needs to know
    which provider actually served a given call."""

    def __init__(self, api_key: str):
        self.chat = _AnthropicChat(Anthropic(api_key=api_key))


class _FallbackCompletions:
    def __init__(self, fallback_client: "FallbackClient"):
        self._fallback_client = fallback_client

    def create(self, **kwargs):
        return self._fallback_client._call(**kwargs)


class _FallbackChat:
    def __init__(self, fallback_client: "FallbackClient"):
        self.completions = _FallbackCompletions(fallback_client)


class FallbackClient:
    """Tries the primary client (Anthropic) first; on ANY Anthropic API-level
    failure (rate limit, insufficient credit balance, auth, server error,
    connection failure -- anthropic.APIError covers all of these) or an
    OpenAI-style RateLimitError, falls through to the secondary client (Groq,
    itself possibly a RotatingClient/model-fallback already). A credit/billing
    failure is a real, expected production scenario for a paid API -- not
    catching it here would crash the whole pipeline instead of degrading to
    the fallback provider. Errors from the secondary client itself still
    propagate normally.
    """

    def __init__(self, primary, secondary):
        self._primary = primary
        self._secondary = secondary
        self.chat = _FallbackChat(self)

    def _call(self, **kwargs):
        try:
            return self._primary.chat.completions.create(**kwargs)
        except (RateLimitError, AnthropicAPIError):
            return self._secondary.chat.completions.create(**kwargs)


def build_client(
    groq_api_key: str | list[str], anthropic_api_key: str | None = None,
) -> OpenAI | RotatingClient | FallbackClient:
    if isinstance(groq_api_key, list):
        groq_client = RotatingClient(groq_api_key, base_url=GROQ_BASE_URL)
    else:
        groq_client = OpenAI(api_key=groq_api_key, base_url=GROQ_BASE_URL)

    if anthropic_api_key:
        return FallbackClient(AnthropicAdapter(anthropic_api_key), groq_client)
    return groq_client


def analyze_article(client, title: str, content: str) -> AnalysisOutput:
    messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                "Analyze this financial news article for a trading-signal app. Accuracy "
                "matters more than coverage -- a wrong or speculative pick is worse than "
                "no pick, since real users may trade on this.\n\n"
                "RULES:\n"
                "1. You are a 20+ year analyst -- you already know real companies in every "
                "major sector, their actual business models, and how they differ from each "
                "other. Use that knowledge: prefer companies literally named in the article, "
                "OR companies you are specifically, confidently thinking of even if not named "
                "verbatim -- set is_direct=true and put the real company name, with "
                "ticker=null if you are not sure of the exact symbol. This applies EVEN for a "
                "sector-wide catalyst -- if you can name the 3-5 specific companies you know "
                "are most exposed, name them individually with is_direct=true rather than "
                "reaching for sector=<value>. Do NOT drop down to sector-level inference just "
                "because you lack the ticker, and do NOT drop down to it just because "
                "reasoning about individual companies is more work than reasoning about a "
                "sector in aggregate.\n"
                "2. Only use sector-level inference (is_direct=false, sector=<value>) as a "
                "last resort -- when you genuinely cannot name specific companies at all, "
                "only a general sense that some unnamed part of a sector is affected. Sector- "
                "level inference produces the SAME rationale for every company the resolver "
                "picks, which is only honest when you truly have no company-specific view; "
                "if you have one, use is_direct=true instead so each company gets its own "
                "reasoning.\n"
                "3. The `sector` value MUST be written EXACTLY as shown below -- lowercase, "
                "exact spelling, e.g. \"it\" not \"IT\", \"oil_gas\" not \"Oil_Gas\" or "
                "\"Oil & Gas\". If the real-world industry you're reasoning about does not "
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
                "6. Each rationale must name the specific mechanism for THAT company, grounded "
                "in what you actually know about it -- its specific role (e.g. upstream "
                "producer vs refiner vs distributor vs miner: never assume every company in a "
                "sector plays the same role), its market position (market leader vs smaller "
                "player, export vs domestic focus), and a real precedent if you know one (how "
                "this company or a directly comparable one actually moved in a similar past "
                "event). Not a sentence that would apply equally to any company in its "
                "sector.\n\n"
                f"Title: {title}\n\nContent: {content or '(no summary available -- reason only from the title, and be more conservative about sector-level inference given the limited signal)'}"
            ),
        },
    ]

    def _call(model: str):
        return client.chat.completions.create(
            model=model,
            max_tokens=1024,
            tools=[RECORD_ANALYSIS_TOOL],
            tool_choice={"type": "function", "function": {"name": "record_analysis"}},
            messages=messages,
        )

    try:
        response = _call(MODEL)
    except RateLimitError:
        # MODEL's daily quota is exhausted -- FALLBACK_MODEL has a separate
        # quota bucket on Groq, so this is a real fallback, not a retry of
        # the same exhausted budget.
        response = _call(FALLBACK_MODEL)

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_analysis"), None)
    if tool_call is None:
        raise ValueError(f"Claude response contained no tool_use block for article: {title!r}")
    arguments = json.loads(tool_call.function.arguments)
    return AnalysisOutput.model_validate(arguments)
