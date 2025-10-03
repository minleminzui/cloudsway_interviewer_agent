from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ..config import settings
from ..core import llm
from .state_machine import ConversationState

LOGGER = logging.getLogger(__name__)


@dataclass
class PolicyDecision:
    action: str
    question: str
    rationale: str


class PolicyError(RuntimeError):
    """Raised when policy decision generation fails."""


async def decide_policy(state: ConversationState) -> PolicyDecision:
    if not settings.llm_credentials_ready:
        raise PolicyError("Ark credentials missing")

    payload = {
        "topic": state.topic,
        "stage": state.stage.value,
        "coverage": round(state.coverage(), 3),
        "pending_clarifications": list(state.pending_clarifications),
        "recent_turns": state.recent_turns(),
    }
    system_prompt = (
        "你是采访策略助手，需要根据最近的对话、提纲覆盖率和待澄清事项，"
        "选择下一步行动（ask/followup/clarify/regress/close），并给出追问。"
        "返回 JSON：{\"action\":..., \"question\":..., \"rationale\":...}。"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    chunks: list[str] = []
    try:
        async for part in llm.chat_stream(
            messages,
            model=settings.ark_policy_model_id or settings.ark_model_id,
        ):
            chunks.append(part)
    except llm.LLMNotConfiguredError as exc:
        raise PolicyError("Ark credentials missing") from exc
    raw = "".join(chunks).strip()
    if not raw:
        raise PolicyError("Empty response from policy model")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        LOGGER.warning("Malformed policy response: %s", raw)
        raise PolicyError("Invalid JSON from policy model") from exc
    action = str(data.get("action") or "ask").strip()
    question = str(data.get("question") or "").strip()
    rationale = str(data.get("rationale") or "").strip()
    if not question:
        raise PolicyError("Policy response missing question")
    if action not in {"ask", "followup", "clarify", "regress", "close"}:
        LOGGER.debug("Unexpected action '%s' from policy, defaulting to ask", action)
        action = "ask"
    return PolicyDecision(action=action, question=question, rationale=rationale)


__all__ = ["PolicyDecision", "PolicyError", "decide_policy"]