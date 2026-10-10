"""Pure decision: should this hook event ask Claude for a pitstop?"""
from dataclasses import dataclass
from typing import Optional

from pitstop.core.config import Config
from pitstop.core.state import SessionState

NOOP = "noop"
REQUEST = "request"


@dataclass(frozen=True)
class Event:
    kind: str  # "stop" or "post_tool_batch"
    context_tokens: Optional[int]
    is_subagent: bool = False
    stop_hook_active: bool = False


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str


def segment_start(config: Config, state: SessionState, context_tokens: Optional[int]) -> None:
    """A context back under the threshold was compacted or cleared outside pitstop: a new segment starts, so the
    next request comes at the threshold again, not at the old request plus the step."""
    if context_tokens is not None and context_tokens < config.threshold_tokens:
        state.requested_at_tokens = None


def decide(config: Config, state: SessionState, event: Event) -> Decision:
    """One request per segment (the stretch since the last resume), again after every retrigger step."""
    if not config.enabled:
        return Decision(NOOP, "disabled")
    if state.excluded:
        return Decision(NOOP, "excluded")
    if event.is_subagent:
        return Decision(NOOP, "subagent")
    if event.stop_hook_active:
        return Decision(NOOP, "stop_hook_active")
    if event.context_tokens is None:
        return Decision(NOOP, "no_usage")
    if event.context_tokens < config.threshold_tokens:
        return Decision(NOOP, "below_threshold")
    last = state.requested_at_tokens
    if last is not None and event.context_tokens < last + config.retrigger_step_tokens:
        return Decision(NOOP, "already_requested")
    return Decision(REQUEST, "threshold")
