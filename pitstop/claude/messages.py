"""Everything pitstop says. All of it is English."""
import time
from typing import Optional

from pitstop.core.store import PendingRecord

NOTIFY_TITLE = "pitstop"
# The /compact the skill queues on its own thread in SDK hosts (T3 Code); the PreToolUse guard recognises it.
COMPACT_SUMMARY = "Resume from the pitstop checkpoint."
COMPACT_COMMAND = '/compact One-line summary: "%s"' % COMPACT_SUMMARY


def compact_queue_lines() -> list:
    """What the skill queues, in order, on its own thread in SDK hosts: the /compact, then the message that starts
    the first turn after it. Printed by mark-pending, because a session keeps the skill text it loaded first."""
    return [
        'queue: with t3_thread_send (mode "queue"), in this order:',
        "queue 1: %s" % COMPACT_COMMAND,
        "queue 2: %s" % COMPACT_SUMMARY,
    ]
BADGE = "🔋"


def k(tokens: int) -> str:
    return "%dK" % (tokens // 1000)


def banner_triggered(tokens: int) -> str:
    return "🔋 pitstop · %s → pitting at the next clean point" % k(tokens)


def banner_resumed(tokens: int) -> str:
    return "🔋 pitstop · resumed from %s" % k(tokens)


def banner_config_invalid(error: str) -> str:
    return "🔋 pitstop · off: invalid config.json → %s" % error


def banner_checkpoint_missing() -> str:
    return "🔋 pitstop · checkpoint not found, starting without it"


def banner_checkpoint_expired() -> str:
    return "🔋 pitstop · checkpoint expired, starting without it"


def notify_triggered(tokens: int) -> str:
    return "Pitting at %s: checkpoint at the next clean point" % k(tokens)


def notify_resumed(tokens: int) -> str:
    return "Resumed from %s" % k(tokens)


def done_line(tokens: int) -> str:
    return "🔋 **pitstop** · done at %s → back on track with a clean context" % k(tokens)


def resumed_line(tokens: int) -> str:
    return "🔋 **pitstop** · resumed from %s · Where we were:" % k(tokens)


def badge_title(title: Optional[str]) -> Optional[str]:
    if not title or not title.strip():
        return None
    title = title.strip()
    return title if title.startswith(BADGE) else "%s %s" % (BADGE, title)


_SKILL_POINTER = (
    "Invoke the `pitstop` skill with the Skill tool (it may be listed as `pitstop:pitstop`; if it is not "
    "available, Read `{skill}`) and follow \"Automatic pitstop\" with these values:\n"
    "- mode: {mode}\n"
    "- context: {tokens} tokens ({k})\n"
    "- cwd: {cwd}\n"
    "- cli: /usr/bin/python3 {cli}\n"
    "- background tasks running: {background}\n"
    "- if you skip, the next request comes after +{step} tokens\n"
)


def _request_context(head: str, mode: str, tokens: int, threshold: int, step: int, cwd: str, cli: str,
                     skill: str, background_tasks: Optional[int]) -> str:
    background = "unknown, check yourself" if background_tasks is None else str(background_tasks)
    return (head + _SKILL_POINTER).format(k=k(tokens), threshold=k(threshold), tokens=tokens, step=step, cwd=cwd,
                                          cli=cli, skill=skill, background=background, mode=mode)


def stop_request_context(tokens: int, threshold: int, step: int, cwd: str, cli: str, skill: str,
                         background_tasks: Optional[int]) -> str:
    head = "[pitstop] Main-thread context is {k}, over the {threshold} threshold. Pitstop now, at this clean point.\n"
    return _request_context(head, "conversation", tokens, threshold, step, cwd, cli, skill, background_tasks)


def batch_request_context(tokens: int, threshold: int, step: int, cwd: str, cli: str, skill: str,
                          background_tasks: Optional[int]) -> str:
    head = (
        "[pitstop] Main-thread context is {k}, over the {threshold} threshold. Pitstop at the next clean boundary, "
        "not in the middle of a step.\n"
        "Boundaries: subagent-driven-development = current task reviewed and ledger updated; brainstorming = spec "
        "written; writing-plans = plan written; before the final review; outside superpowers = end of the current "
        "step. At the boundary, do the pitstop before starting anything new.\n"
    )
    mode = "superpowers if a superpowers spec, plan or ledger is in use, otherwise conversation"
    return _request_context(head, mode, tokens, threshold, step, cwd, cli, skill, background_tasks)


def resume_context(record: PendingRecord, checkpoint_text: str, cli: str) -> str:
    base = (
        "[pitstop] This session restarts from a pitstop checkpoint taken at {k}. Checkpoint file: {path}\n\n"
        "<pitstop-checkpoint>\n{text}\n</pitstop-checkpoint>\n\n"
        "Resume:\n"
        "1. Re-read only the files the checkpoint cites that the next action needs. Do not re-explore.\n"
        "2. Print exactly `{line}` followed by three short lines in the language of the conversation: goal, current state, next action.\n"
        "3. Continue from the next action.\n"
        "4. If something you need is missing from the checkpoint, run "
        "`/usr/bin/python3 {cli} gap \"<what was missing>\"`, then recover it.\n"
    ).format(k=k(record.context_tokens), path=record.checkpoint, text=checkpoint_text.strip(),
             line=resumed_line(record.context_tokens), cli=cli)
    if record.plan:
        base += "5. A superpowers plan is being executed: resume the plan `%s` from its ledger with superpowers:subagent-driven-development.\n" % record.plan
    return base


def expired_line(hhmm: str, checkpoint: str) -> str:
    return ("🔋 **pitstop** · checkpoint expired (taken at %s): %s — say “resume from the checkpoint” "
            "to pick up from there" % (hhmm, checkpoint))


def expired_context(record: PendingRecord) -> str:
    hhmm = time.strftime("%H:%M", time.localtime(record.created_at))
    return (
        "[pitstop] pitstop found a checkpoint matching this session that expired, created at {hhmm} local "
        "time. Checkpoint file: {path}\n\n"
        "As the first line of your reply, print exactly `{line}`, then answer the user's message normally. "
        "If the user later asks to resume from it, Read {path} and follow the \"Resuming\" steps of the "
        "pitstop skill.\n"
    ).format(hhmm=hhmm, path=record.checkpoint, line=expired_line(hhmm, record.checkpoint))


def compact_blocked_reason() -> str:
    return ("[pitstop] Blocked: this session has no registered pitstop checkpoint, so pitstop must not compact it. "
            "If you skipped the pitstop, carry on normally; if mark-pending failed, report it and continue here.")
