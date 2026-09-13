"""Claude Code hook protocol: parse the JSON on stdin, build the JSON for stdout."""
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional


class HookInputError(Exception):
    """The hook input is not what Claude Code documents."""


@dataclass(frozen=True)
class HookInput:
    event: str
    session_id: str
    transcript_path: str
    cwd: str
    agent_id: Optional[str] = None
    stop_hook_active: bool = False
    source: Optional[str] = None
    session_title: Optional[str] = None
    background_tasks: int = 0


def _text(data: Dict[str, Any], key: str) -> Optional[str]:
    value = data.get(key)
    return value if isinstance(value, str) and value else None


def parse_hook_input(raw: str) -> HookInput:
    try:
        data = json.loads(raw)
    except ValueError:
        raise HookInputError("stdin is not JSON") from None
    if not isinstance(data, dict):
        raise HookInputError("stdin is not a JSON object")
    for key in ("hook_event_name", "session_id", "transcript_path", "cwd"):
        if _text(data, key) is None:
            raise HookInputError("missing %s" % key)
    tasks = data.get("background_tasks")
    return HookInput(
        event=data["hook_event_name"],
        session_id=data["session_id"],
        transcript_path=data["transcript_path"],
        cwd=data["cwd"],
        agent_id=_text(data, "agent_id"),
        stop_hook_active=data.get("stop_hook_active") is True,
        source=_text(data, "source"),
        session_title=_text(data, "session_title"),
        background_tasks=len(tasks) if isinstance(tasks, list) else 0,
    )


def build_output(event_name: str, system_message: Optional[str] = None, additional_context: Optional[str] = None,
                 initial_user_message: Optional[str] = None, session_title: Optional[str] = None) -> str:
    output: Dict[str, Any] = {}
    if system_message:
        output["systemMessage"] = system_message
    specific: Dict[str, Any] = {"hookEventName": event_name}
    if additional_context:
        specific["additionalContext"] = additional_context
    if initial_user_message:
        specific["initialUserMessage"] = initial_user_message
    if session_title:
        specific["sessionTitle"] = session_title
    if len(specific) > 1:
        output["hookSpecificOutput"] = specific
    return json.dumps(output, ensure_ascii=True)
