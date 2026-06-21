"""
Claude API wrapper.
Receives only pre-aggregated, anonymised trend statistics — no raw row-level
company data is ever forwarded to the LLM.  Actual revenue figures are
replaced by indexed / percentage representations before this module is called
(see routes/insights.py for the sanitisation step).
"""
import os
from typing import Generator, Optional

import anthropic

MODEL = os.getenv("LLM_MODEL", "claude-opus-4-8")

_EXEC_AI_SYSTEM = (
    "You are a senior CPG analyst presenting to C-suite executives. "
    "Write exactly 4-5 sentences responding to the question. "
    "Use the specific numbers from the provided trend data — quote growth rates, rankings, or "
    "efficiency figures directly. Name what matters most, quantify it, and state the "
    "commercial implication. Write as confident, decisive prose — no bullet points, "
    "no headers, no markdown formatting."
)

_SYSTEM_PROMPT = (
    "You are a senior CPG (consumer packaged goods) sales analytics consultant. "
    "You receive pre-aggregated trend statistics — growth rates, market share indices, "
    "channel mix percentages, ranked performance data, and competitor event logs. "
    "Raw revenue totals are never shared with you.\n\n"
    "Your role:\n"
    "• Identify patterns, inflection points, and competitive dynamics in the data\n"
    "• Translate statistical trends into actionable commercial recommendations\n"
    "• Flag supply-chain risks, market-share vulnerabilities, and growth opportunities\n"
    "• Reference named competitors (RivalCo, ValueBrand, HealthFirst) when context is provided\n"
    "• Frame insights for a senior commercial leadership audience (CMO / CCO level)\n\n"
    "Rules:\n"
    "• Never invent figures not present in the provided context\n"
    "• Ground every claim in the trend data given\n"
    "• Use business language: market share points (pp), basis points (bps), momentum\n"
    "• Format with clear sections: a brief headline finding, supporting evidence, "
    "then 3-5 bullet-point recommendations\n"
    "• Be concise but thorough — executives read fast"
)

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY env var is not set. "
                "Add it to your .env file and never hard-code it."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def get_insight(question: str, sanitised_context: str) -> str:
    """
    Call Claude with a *sanitised* context string (non-streaming).
    The caller is responsible for stripping / indexing sensitive figures
    before passing sanitised_context here.
    """
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Trend context (aggregated, anonymised):\n"
                    f"{sanitised_context}\n\n"
                    f"Question: {question}"
                ),
            }
        ],
    )
    # adaptive thinking may prepend a thinking block; return the text block
    text_blocks = [b for b in response.content if b.type == "text"]
    return text_blocks[0].text if text_blocks else ""


def get_insight_stream(
    question: str,
    sanitised_context: str,
) -> Generator[str, None, None]:
    """
    Stream Claude's response token-by-token.
    Yields only text chunks — thinking blocks are filtered by text_stream internally.
    Any API or auth error is yielded as a readable message rather than silently closing
    the connection (which would show "Response ended prematurely" in the client).
    """
    try:
        client = _get_client()
        with client.messages.stream(
            model=MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Trend context (aggregated, anonymised):\n"
                        f"{sanitised_context}\n\n"
                        f"Question: {question}"
                    ),
                }
            ],
        ) as stream:
            for text in stream.text_stream:
                yield text
    except Exception as exc:
        err_type = type(exc).__name__
        hint = ""
        if "auth" in err_type.lower() or "authentication" in str(exc).lower():
            hint = " — check that ANTHROPIC_API_KEY in `.env` is a valid key (not the placeholder)."
        elif "not found" in str(exc).lower() or "model" in str(exc).lower():
            hint = " — the model ID may be unavailable on your account tier."
        yield f"\n\n**API Error ({err_type}):** {exc}{hint}"


def get_exec_brief_ai(
    question: str,
    sanitised_context: str,
) -> Generator[str, None, None]:
    """
    Stream a focused 4-5 sentence executive paragraph for the summary tab.
    Uses a tighter system prompt than get_insight_stream — prose only, no formatting.
    """
    try:
        client = _get_client()
        with client.messages.stream(
            model=MODEL,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=_EXEC_AI_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Trend data (aggregated, anonymised):\n"
                        f"{sanitised_context}\n\n"
                        f"Question: {question}"
                    ),
                }
            ],
        ) as stream:
            for text in stream.text_stream:
                yield text
    except Exception as exc:
        err_type = type(exc).__name__
        hint = ""
        if "auth" in err_type.lower() or "authentication" in str(exc).lower():
            hint = " — check ANTHROPIC_API_KEY in .env."
        yield f"*AI synthesis unavailable ({err_type}){hint}*"
