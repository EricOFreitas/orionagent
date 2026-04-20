"""
agent.py — All interactions with the Anthropic API.

Design decisions:
- AgentSession holds the in-memory multi-turn message list for one conversation.
- send_message() appends the user turn, calls the API, records the assistant turn
  and returns the text.
- summarize_conversation() produces a short summary for database storage.
- quick_message() is a stateless single-turn helper (used by the scheduler).
- Model routing: Haiku by default; Sonnet when `use_sonnet=True` (i.e. /decidir).
"""
from __future__ import annotations

import logging
from typing import Optional

import anthropic

from prompts.system import build_system_prompt, SUMMARY_PROMPT
from settings import (
    ANTHROPIC_API_KEY,
    DEFAULT_MODEL,
    DECISION_MODEL,
    MAX_TOKENS_DEFAULT,
    MAX_TOKENS_DECISION,
)

logger = logging.getLogger(__name__)

# Single shared Anthropic client (thread-safe, reuses the underlying HTTP session).
_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


class AgentSession:
    """Maintains conversation history for a single agent session."""

    def __init__(
        self,
        session_type: str,
        context: dict | None = None,
        use_sonnet: bool = False,
    ) -> None:
        self.session_type = session_type
        self.context: dict = context or {}
        self.use_sonnet = use_sonnet
        self.model = DECISION_MODEL if use_sonnet else DEFAULT_MODEL
        self.max_tokens = MAX_TOKENS_DECISION if use_sonnet else MAX_TOKENS_DEFAULT
        self.messages: list[dict] = []

    # ------------------------------------------------------------------
    # Message management
    # ------------------------------------------------------------------

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def get_transcript(self) -> str:
        """Return the full conversation as a plain-text transcript."""
        lines: list[str] = []
        for msg in self.messages:
            label = "Usuário" if msg["role"] == "user" else "Orion"
            lines.append(f"{label}: {msg['content']}")
        return "\n".join(lines)

    def last_assistant_message(self) -> str:
        """Return the most recent assistant message, or an empty string."""
        for msg in reversed(self.messages):
            if msg["role"] == "assistant":
                return msg["content"]
        return ""


# ---------------------------------------------------------------------------
# Core API helpers
# ---------------------------------------------------------------------------


async def send_message(
    session: AgentSession,
    user_message: str,
    system_prompt: Optional[str] = None,
) -> str:
    """
    Append *user_message* to the session, call the API, persist the assistant
    reply, and return the reply text.

    Args:
        session:       Active AgentSession object.
        user_message:  Text from the user.
        system_prompt: Override the auto-built system prompt (optional).

    Raises:
        anthropic.APIConnectionError: Network / DNS failure.
        anthropic.RateLimitError:     API rate limit exceeded.
        anthropic.APIStatusError:     Non-2xx HTTP response from the API.
    """
    session.add_user(user_message)

    if system_prompt is None:
        system_prompt = build_system_prompt(session.context)

    try:
        response = _client.messages.create(
            model=session.model,
            max_tokens=session.max_tokens,
            system=system_prompt,
            messages=session.messages,
        )
        reply: str = response.content[0].text
        session.add_assistant(reply)
        return reply

    except anthropic.APIConnectionError:
        logger.error("Anthropic API connection error", exc_info=True)
        raise
    except anthropic.RateLimitError:
        logger.error("Anthropic rate-limit reached", exc_info=True)
        raise
    except anthropic.APIStatusError as exc:
        logger.error("Anthropic API status error %s: %s", exc.status_code, exc.message)
        raise


async def summarize_conversation(transcript: str) -> str:
    """
    Ask Haiku to produce a concise summary of a finished conversation.
    Falls back to a generic message if the API call fails.
    """
    prompt = SUMMARY_PROMPT.format(conversation=transcript)
    try:
        response = _client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        logger.warning("Could not summarize conversation", exc_info=True)
        return "Resumo indisponível."


async def quick_message(
    prompt: str,
    system: Optional[str] = None,
    use_sonnet: bool = False,
) -> str:
    """
    Single-turn, stateless API call. Used by the scheduler for automated messages.

    Args:
        prompt:     The user-side message.
        system:     Optional system prompt.
        use_sonnet: If True, use the decision model.

    Returns:
        The assistant reply text.
    """
    model = DECISION_MODEL if use_sonnet else DEFAULT_MODEL
    max_tokens = MAX_TOKENS_DECISION if use_sonnet else MAX_TOKENS_DEFAULT

    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

    try:
        response = _client.messages.create(**kwargs)
        return response.content[0].text.strip()
    except Exception:
        logger.error("quick_message failed", exc_info=True)
        raise
