"""pitstop command line: the hook entry point and the management commands used by the skill."""
import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, TextIO

from pitstop.claude import messages
from pitstop.claude.hooks import run_hook
from pitstop.claude.transcript import (
    TranscriptSchemaError,
    default_projects_dir,
    find_transcript,
    read_context_tokens,
    read_last_cwd,
    read_session_title,
)
from pitstop.core.config import ConfigError, load_config, update_config
from pitstop.core.fsutil import append_line
from pitstop.core.log import log_event, read_events
from pitstop.core.paths import Layout, pitstop_home
from pitstop.core.state import load_state, locked_state
from pitstop.core.store import PendingRecord, mark_pending, new_checkpoint_path, prune_old_files, write_checkpoint

SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
ENTRYPOINT_ENV = "CLAUDE_CODE_ENTRYPOINT"
# Set by hooks/register.ts where it will restart the session itself (terminal and `claude -p`, not SDK hosts).
AUTO_RESTART_ENV = "PITSTOP_AUTO_RESTART"


class CliError(Exception):
    """Shown to the user as `🔋 pitstop · <message>`, exit code 1. Messages are English."""


def write_text(stream: TextIO, text: str) -> None:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:
        stream.write(text)


def read_text(stream: TextIO) -> str:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        return buffer.read().decode("utf-8", "replace")
    return stream.read()


@dataclass
class Ctx:
    layout: Layout
    stdin: TextIO
    stdout: TextIO
    env: Mapping[str, str]
    projects_dir: Path
    now: float

    def say(self, text: str) -> None:
        write_text(self.stdout, text + "\n")


def _session_id(args: argparse.Namespace, ctx: Ctx) -> str:
    session = getattr(args, "session", None) or ctx.env.get(SESSION_ENV)
    if not session:
        raise CliError("unknown session: %s is not set, pass --session" % SESSION_ENV)
    return session


def _transcript(args: argparse.Namespace, ctx: Ctx, session_id: str) -> Path:
    if getattr(args, "transcript", None):
        return Path(args.transcript)
    found = find_transcript(session_id, ctx.projects_dir)
    if found is None:
        raise CliError("transcript of session %s not found" % session_id)
    return found


def cmd_on(args: argparse.Namespace, ctx: Ctx) -> None:
    update_config(ctx.layout, enabled=True)
    ctx.say("🔋 pitstop on")


def cmd_off(args: argparse.Namespace, ctx: Ctx) -> None:
    update_config(ctx.layout, enabled=False)
    ctx.say("🔋 pitstop off in all sessions")


def cmd_off_here(args: argparse.Namespace, ctx: Ctx) -> None:
    with locked_state(ctx.layout, _session_id(args, ctx)) as state:
        state.excluded = True
    ctx.say("🔋 pitstop off in this session")


def cmd_notify(args: argparse.Namespace, ctx: Ctx) -> None:
    update_config(ctx.layout, notify=args.state == "on")
    ctx.say("🔋 pitstop notifications %s" % args.state)


def cmd_new_checkpoint(args: argparse.Namespace, ctx: Ctx) -> None:
    ctx.say(str(new_checkpoint_path(ctx.layout, _session_id(args, ctx), ctx.now)))


def cmd_mark_pending(args: argparse.Namespace, ctx: Ctx) -> None:
    session = _session_id(args, ctx)
    transcript = _transcript(args, ctx, session)
    try:
        tokens = read_context_tokens(str(transcript))
    except (OSError, TranscriptSchemaError) as exc:
        raise CliError("context not readable from the transcript (%s)" % type(exc).__name__) from None
    if tokens is None:
        raise CliError("context not readable from the transcript (no messages)")
    if args.stdin:
        text = read_text(ctx.stdin)
        if not text.strip():
            raise CliError("empty checkpoint")
        checkpoint = write_checkpoint(ctx.layout, session, text, ctx.now)
    else:
        checkpoint = Path(args.checkpoint).expanduser()
        if not checkpoint.is_file():
            raise CliError("checkpoint not found: %s" % checkpoint)
        if checkpoint.stat().st_size == 0:
            raise CliError("empty checkpoint: %s" % checkpoint)
    # SDK hosts (T3 Code) have no /clear: there the session compacts and resumes in place.
    if ctx.env.get(AUTO_RESTART_ENV) == "1":
        restart = "auto"
    else:
        restart = "compact" if ctx.env.get(ENTRYPOINT_ENV, "").startswith("sdk") else "clear"
    record = PendingRecord(
        checkpoint=str(checkpoint.resolve()),
        session_id=session,
        cwd=args.cwd or read_last_cwd(str(transcript)) or os.getcwd(),
        context_tokens=tokens,
        created_at=ctx.now,
        title=read_session_title(str(transcript)),
        plan=args.plan,
        project_dir=str(transcript.parent),
        restart=restart,
    )
    mark_pending(ctx.layout, record)
    prune_old_files(ctx.layout, ctx.now, keep=Path(record.checkpoint))
    log_event(ctx.layout, "cli", "pitstop_done", session_id=session, context_tokens=tokens,
              checkpoint=record.checkpoint)
    config, _ = load_config(ctx.layout)
    ctx.say("checkpoint registered: %s" % record.checkpoint)
    ctx.say("resume window: %d minutes" % config.resume_window_minutes)
    ctx.say("restart: %s" % restart)
    if restart == "compact":
        # Spelled out here and not only in SKILL.md: a session follows the skill text it loaded first (issue #1).
        for line in messages.compact_queue_lines():
            ctx.say(line)
    ctx.say(messages.done_line(tokens))


def cmd_gap(args: argparse.Namespace, ctx: Ctx) -> None:
    session = _session_id(args, ctx)
    entry = {"ts": round(ctx.now, 3), "session_id": session, "text": " ".join(args.text).strip()}
    append_line(ctx.layout.gaps, json.dumps(entry, ensure_ascii=False))
    log_event(ctx.layout, "cli", "gap", session_id=session)
    ctx.say("🔋 checkpoint gap recorded")


def _current_context(args: argparse.Namespace, ctx: Ctx, session: Optional[str]) -> str:
    if not session:
        return "not available"
    try:
        tokens = read_context_tokens(str(_transcript(args, ctx, session)))
    except (CliError, OSError, TranscriptSchemaError):
        return "not available"
    return messages.k(tokens) if tokens is not None else "not available"


def cmd_status(args: argparse.Namespace, ctx: Ctx) -> None:
    config, config_error = load_config(ctx.layout)
    session = args.session or ctx.env.get(SESSION_ENV)
    if config_error:
        ctx.say("🔋 pitstop: off (invalid config.json → %s)" % config_error)
    elif not config.enabled:
        ctx.say("🔋 pitstop: off in all sessions")
    elif session and load_state(ctx.layout, session).excluded:
        ctx.say("🔋 pitstop: off in this session")
    else:
        ctx.say("🔋 pitstop: on")
    ctx.say("notifications: %s" % ("on" if config.notify else "off"))
    ctx.say("current context: %s · threshold %s" % (_current_context(args, ctx, session),
                                                 messages.k(config.threshold_tokens)))
    events = read_events(ctx.layout)
    done = sum(1 for e in events if e.get("action") == "pitstop_done")
    gaps = sum(1 for e in events if e.get("action") == "gap")
    bases = [e["resume_base"] for e in events
             if e.get("action") == "resume_base" and isinstance(e.get("resume_base"), int)]
    ctx.say("pitstops: %d · real resumes: %d · gaps: %d" % (done, len(bases), gaps))
    if bases:
        ctx.say("real resume size: last %s · median %s" % (messages.k(bases[-1]),
                                                             messages.k(int(statistics.median(bases)))))


_COMMANDS = {
    "on": cmd_on,
    "off": cmd_off,
    "off-here": cmd_off_here,
    "notify": cmd_notify,
    "status": cmd_status,
    "new-checkpoint": cmd_new_checkpoint,
    "mark-pending": cmd_mark_pending,
    "gap": cmd_gap,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pitstop",
                                     description="Checkpoint past a context threshold and resume after /clear or /compact.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hook", help="run a Claude Code hook (event JSON on stdin)").add_argument("event")
    sub.add_parser("on", help="enable pitstop in all sessions")
    sub.add_parser("off", help="disable pitstop in all sessions")
    sub.add_parser("off-here", help="disable pitstop in the current session").add_argument("--session")
    notify = sub.add_parser("notify", help="macOS notifications")
    notify.add_argument("state", choices=["on", "off"])
    status = sub.add_parser("status", help="state, current context and pilot numbers")
    status.add_argument("--session")
    status.add_argument("--transcript")
    sub.add_parser("new-checkpoint", help="print the path for a new checkpoint").add_argument("--session")
    mark = sub.add_parser("mark-pending", help="register a checkpoint for the resume after /clear or /compact")
    source = mark.add_mutually_exclusive_group(required=True)
    source.add_argument("--checkpoint", help="checkpoint file already written")
    source.add_argument("--stdin", action="store_true", help="read the checkpoint text from stdin")
    mark.add_argument("--cwd")
    mark.add_argument("--plan")
    mark.add_argument("--session")
    mark.add_argument("--transcript")
    gap = sub.add_parser("gap", help="record something the checkpoint was missing")
    gap.add_argument("text", nargs="+")
    gap.add_argument("--session")
    return parser


def _hook(args: List[str], stdin: TextIO, stdout: TextIO, layout: Layout) -> int:
    """Hooks never fail: no argparse exit codes, no stderr noise, always exit 0."""
    try:
        raw = read_text(stdin)
    except Exception:
        return 0
    output = run_hook(args[0] if args else "", raw, layout)
    if output:
        write_text(stdout, output)
    return 0


def main(argv: List[str], stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout,
         env: Optional[Mapping[str, str]] = None, layout: Optional[Layout] = None,
         projects_dir: Optional[Path] = None, now: Optional[float] = None) -> int:
    layout = layout or Layout(pitstop_home())
    if argv[:1] == ["hook"]:
        return _hook(argv[1:], stdin, stdout, layout)
    args = build_parser().parse_args(argv)
    env = os.environ if env is None else env
    ctx = Ctx(layout, stdin, stdout, env, projects_dir or default_projects_dir(env),
              time.time() if now is None else now)
    try:
        _COMMANDS[args.command](args, ctx)
    except (CliError, ConfigError) as exc:
        ctx.say("🔋 pitstop · %s" % exc)
        return 1
    return 0
