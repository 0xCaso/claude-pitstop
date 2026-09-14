# pitstop

A local Claude Code plugin that keeps long sessions cheap without losing the thread.

When the main conversation grows past 200K tokens, pitstop asks Claude to save a compact checkpoint at the next
clean point and tells you to run `/clear`. The first message you send after that resumes from the checkpoint
automatically.

## Why

Most of the cost of a long session is re-reading a large cached context on every turn. Restarting from a small
checkpoint that points to files, instead of summarizing them, cuts that cost. Quality comes first: pitstop skips
when a checkpoint would lose something that lives only in the context, such as a debugging session half-way.

## Install

Requires macOS and `/usr/bin/python3` (3.9+, standard library only).

```bash
mkdir -p ~/.claude/skills && ln -sfn "$PWD" ~/.claude/skills/pitstop
claude plugin validate --strict ~/.claude/skills/pitstop
claude plugin details pitstop
```

The plugin loads in the next session as `pitstop@skills-dir`. It does not touch `settings.json`.

## Commands

| Command | Effect |
|---|---|
| `/pitstop status` | On/off, notifications, current context, threshold, pitstops, real resume size, gaps |
| `/pitstop on` · `/pitstop off` | Enable or disable in all sessions |
| `/pitstop off here` | Disable in the current session |
| `/pitstop now` | Checkpoint and resume right away |
| `/pitstop notify on` · `off` | macOS notifications |
| `/pitstop gap <what was missing>` | Record something the checkpoint was missing |

The `/` menu shows the skill namespaced as `/pitstop:pitstop`.

Emergency switch: `claude plugin disable pitstop@skills-dir`.

## How it works

- `Stop` and `PostToolBatch` hooks read the context size from the transcript. Past the threshold they ask Claude,
  once per segment, for a pitstop at the next clean point.
- The `pitstop` skill writes the checkpoint, registers it and tells the user to run `/clear`.
- After `/clear`, a `UserPromptSubmit` hook injects the checkpoint once into the first message of the fresh
  session, when it is in the same project (even if the working directory changed mid-session, e.g. via `cd`)
  and starts within the configured resume window (default 60 minutes).
- A matching checkpoint found past that window, but still under 24 hours old, is not resumed automatically
  but gets a one-line "checkpoint scaduto" notice instead of silence, with the path to resume from it.
- Every hook fails open: any error leaves the conversation untouched.

Working files live in `~/.claude/pitstop/`: `config.json`, `state/`, `pending/`, `checkpoints/`, `log.jsonl` and
`gaps.jsonl`. The log holds numbers and states only.

## Configuration

`~/.claude/pitstop/config.json` (missing file = defaults):

```json
{
  "enabled": true,
  "notify": true,
  "threshold_tokens": 200000,
  "retrigger_step_tokens": 50000,
  "resume_window_minutes": 60
}
```

## Development

```bash
/usr/bin/python3 -m unittest discover -s tests -t . -v
```

## Uninstall

```bash
rm ~/.claude/skills/pitstop
```

Delete `~/.claude/pitstop/` too if you do not need the checkpoints and the log.
