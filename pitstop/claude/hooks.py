"""Hook handlers: glue between Claude Code events and the pitstop core. Every error fails open."""
import os
import time
from pathlib import Path
from typing import Callable, Optional

from pitstop.claude import messages
from pitstop.claude.hookio import HookInput, HookInputError, build_output, parse_hook_input
from pitstop.claude.notify import notify
from pitstop.claude.transcript import TranscriptSchemaError, read_context_tokens
from pitstop.core.config import Config, load_config, should_show_config_notice
from pitstop.core.decide import REQUEST, Event, decide
from pitstop.core.fsutil import LockTimeout
from pitstop.core.log import log_event
from pitstop.core.paths import Layout
from pitstop.core.state import SessionState, locked_state
from pitstop.core.store import PendingRecord, consume_expired_pending, consume_pending, has_pending

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "bin" / "pitstop"
SKILL_PATH = REPO_ROOT / "skills" / "pitstop" / "SKILL.md"

Notifier = Callable[[str, str], None]

# log name -> (hookEventName in the output, builder of the instructions for the model)
_REQUESTS = {
    "stop": ("Stop", messages.stop_request_context),
    "post_tool_batch": ("PostToolBatch", messages.batch_request_context),
}


class UnknownHookEvent(Exception):
    pass


def run_hook(event_arg: str, raw: str, layout: Layout, notifier: Notifier = notify,
             now: Optional[float] = None) -> Optional[str]:
    """Handle one hook call. Returns the JSON for stdout, or None. Never raises."""
    log_name = event_arg.replace("-", "_")
    try:
        handler = _HANDLERS.get(event_arg)
        if handler is None:
            raise UnknownHookEvent(event_arg)
        inp = parse_hook_input(raw)
        return handler(inp, layout, notifier, time.time() if now is None else now)
    except Exception as exc:  # fail-open: whatever happens, the conversation goes on
        try:
            log_event(layout, log_name, "error", error=_error_category(exc))
        except Exception:
            pass
        return None


def _error_category(exc: Exception) -> str:
    if isinstance(exc, UnknownHookEvent):
        return "unknown_event"
    if isinstance(exc, HookInputError):
        return "input_error"
    if isinstance(exc, TranscriptSchemaError):
        return "schema_error"
    if isinstance(exc, LockTimeout):
        return "lock_timeout"
    if isinstance(exc, OSError):
        return "fs_error"
    return "internal_error"


def _safe_notify(notifier: Notifier, message: str) -> None:
    try:
        notifier(messages.NOTIFY_TITLE, message)
    except Exception:
        pass


def _context_tokens(layout: Layout, state: SessionState, log_name: str, transcript_path: str) -> Optional[int]:
    """Context tokens or None. Read and schema errors are logged once per category per session."""
    try:
        tokens = read_context_tokens(transcript_path)
    except (TranscriptSchemaError, OSError) as exc:
        category = _error_category(exc)
        if state.last_error != category:
            state.last_error = category
            log_event(layout, log_name, "error", session_id=state.session_id, error=category)
        return None
    state.last_error = None
    return tokens


def _request(inp: HookInput, layout: Layout, notifier: Notifier, config: Config, tokens: int, log_name: str,
             background_tasks: Optional[int]) -> str:
    output_event, build_context = _REQUESTS[log_name]
    log_event(layout, log_name, "request", session_id=inp.session_id, context_tokens=tokens,
              threshold=config.threshold_tokens)
    if config.notify:
        _safe_notify(notifier, messages.notify_triggered(tokens))
    context = build_context(tokens=tokens, threshold=config.threshold_tokens, step=config.retrigger_step_tokens,
                            cwd=inp.cwd, cli=str(CLI_PATH), skill=str(SKILL_PATH), background_tasks=background_tasks)
    return build_output(output_event, system_message=messages.banner_triggered(tokens), additional_context=context)


def _maybe_log_resume_base(layout: Layout, state: SessionState, log_name: str, session_id: str,
                           tokens: Optional[int]) -> None:
    """Log the real size of the first turn after a resume, exactly once, whichever hook (Stop or
    PostToolBatch) sees a valid reading first."""
    if state.awaiting_resume_base and tokens is not None:
        state.awaiting_resume_base = False
        log_event(layout, log_name, "resume_base", session_id=session_id, resume_base=tokens)


def _handle_stop(inp: HookInput, layout: Layout, notifier: Notifier, now: float) -> Optional[str]:
    config, config_error = load_config(layout)
    if config_error is not None:
        if should_show_config_notice(layout, config_error):
            return build_output("Stop", system_message=messages.banner_config_invalid(config_error))
        return None
    if not config.enabled or inp.agent_id:
        return None
    with locked_state(layout, inp.session_id) as state:
        if state.excluded:
            return None
        tokens = _context_tokens(layout, state, "stop", inp.transcript_path)
        _maybe_log_resume_base(layout, state, "stop", inp.session_id, tokens)
        event = Event("stop", tokens, stop_hook_active=inp.stop_hook_active)
        if decide(config, state, event).action != REQUEST:
            return None
        state.requested_at_tokens = tokens
    return _request(inp, layout, notifier, config, tokens, "stop", inp.background_tasks)


def _handle_post_tool_batch(inp: HookInput, layout: Layout, notifier: Notifier, now: float) -> Optional[str]:
    config, config_error = load_config(layout)
    if config_error is not None or not config.enabled or inp.agent_id:
        return None  # the invalid-config banner is shown by Stop only
    with locked_state(layout, inp.session_id) as state:
        if state.excluded:
            return None
        try:
            size = os.path.getsize(inp.transcript_path)
        except OSError:
            size = -1  # unreadable: _context_tokens reads it and logs the error once per session
        if size != state.last_transcript_size or state.last_context_tokens is None:
            state.last_transcript_size = size
            state.last_context_tokens = _context_tokens(layout, state, "post_tool_batch", inp.transcript_path)
        tokens = state.last_context_tokens
        _maybe_log_resume_base(layout, state, "post_tool_batch", inp.session_id, tokens)
        if decide(config, state, Event("post_tool_batch", tokens)).action != REQUEST:
            return None
        state.requested_at_tokens = tokens
    return _request(inp, layout, notifier, config, tokens, "post_tool_batch", None)


def _is_fresh_session(transcript_path: str) -> bool:
    """No assistant reply yet: the first prompt after /clear or in a new session."""
    try:
        return read_context_tokens(transcript_path) is None
    except FileNotFoundError:
        return True


def _handle_user_prompt_submit(inp: HookInput, layout: Layout, notifier: Notifier, now: float) -> Optional[str]:
    if not has_pending(layout):
        return None
    if not _is_fresh_session(inp.transcript_path):
        return None
    # Resume even if pitstop was switched off meanwhile: the checkpoint exists and /clear already happened.
    config, _ = load_config(layout)
    project_dir = str(Path(inp.transcript_path).parent)
    record = consume_pending(layout, inp.session_id, inp.cwd, now, config.resume_window_minutes,
                             project_dir=project_dir)
    if record is None:
        expired = consume_expired_pending(layout, inp.session_id, inp.cwd, now, config.resume_window_minutes,
                                          project_dir=project_dir)
        if expired is None:
            return None
        log_event(layout, "user_prompt_submit", "resume_expired", session_id=inp.session_id,
                  checkpoint=expired.checkpoint)
        return build_output(
            "UserPromptSubmit",
            system_message=messages.banner_checkpoint_expired(),
            additional_context=messages.expired_context(expired),
        )
    return _resume(inp, layout, notifier, config, record, "UserPromptSubmit", "user_prompt_submit")


def _handle_session_start(inp: HookInput, layout: Layout, notifier: Notifier, now: float) -> Optional[str]:
    """After /compact (the restart available where /clear is not, e.g. T3 Code): the same session
    picks up its own checkpoint. Expired records are left alone: a fresh session announces them."""
    if inp.source != "compact" or inp.agent_id or not has_pending(layout):
        return None
    config, _ = load_config(layout)
    record = consume_pending(layout, inp.session_id, inp.cwd, now, config.resume_window_minutes,
                             same_session_only=True)
    if record is None:
        return None
    return _resume(inp, layout, notifier, config, record, "SessionStart", "session_start")


def _resume(inp: HookInput, layout: Layout, notifier: Notifier, config: Config, record: PendingRecord,
            output_event: str, log_name: str) -> str:
    try:
        with locked_state(layout, inp.session_id) as state:
            state.requested_at_tokens = None
            state.awaiting_resume_base = True
            state.last_transcript_size = -1
            state.last_context_tokens = None
            state.last_error = None
    except (LockTimeout, OSError) as exc:
        # The checkpoint is still readable even if the fresh session's state could not be reset:
        # resume_base tracking for the new segment is lost, but the resume itself must not be.
        log_event(layout, log_name, "error", session_id=inp.session_id, error=_error_category(exc))
    try:
        checkpoint_text = Path(record.checkpoint).read_text(encoding="utf-8")
    except OSError:
        log_event(layout, log_name, "error", session_id=inp.session_id, error="checkpoint_missing",
                  checkpoint=record.checkpoint)
        return build_output(output_event, system_message=messages.banner_checkpoint_missing())
    log_event(layout, log_name, "resume", session_id=inp.session_id, checkpoint=record.checkpoint,
              resumed_from=record.context_tokens)
    if config.notify:
        _safe_notify(notifier, messages.notify_resumed(record.context_tokens))
    return build_output(
        output_event,
        system_message=messages.banner_resumed(record.context_tokens),
        additional_context=messages.resume_context(record, checkpoint_text, cli=str(CLI_PATH)),
        # Only UserPromptSubmit can set the title; a compacted session keeps its own.
        session_title=messages.badge_title(record.title) if output_event == "UserPromptSubmit" else None,
    )


_HANDLERS = {
    "stop": _handle_stop,
    "post-tool-batch": _handle_post_tool_batch,
    "user-prompt-submit": _handle_user_prompt_submit,
    "session-start": _handle_session_start,
}
