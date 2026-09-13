---
name: pitstop
description: Use when the user types /pitstop (on, off, off here, now, status, notify on, notify off, gap) or when a "[pitstop]" hook message asks for a pitstop. Saves a checkpoint, then tells the user to run /clear and resumes from it on the first message after that.
---

# pitstop

pitstop keeps the context small but complete. Past the threshold it saves a checkpoint at a clean point, then
tells you to run `/clear`: the first message you send after that resumes from the checkpoint automatically.

CLI, always with this interpreter and this path:

```bash
/usr/bin/python3 ~/.claude/skills/pitstop/bin/pitstop <command>
```

Below, `pitstop <command>` means that full command.

In the `/` menu this skill appears as `/pitstop:pitstop`. Below, `/pitstop <cmd>` also means `/pitstop:pitstop <cmd>`.

## Commands

| User types | Run | Then |
|---|---|---|
| `/pitstop` or `/pitstop status` | `pitstop status` | Show the output as is. |
| `/pitstop on` | `pitstop on` | Show the output line. |
| `/pitstop off` | `pitstop off` | Show the output line. |
| `/pitstop off here` | `pitstop off-here` | Show the output line. |
| `/pitstop notify on` · `/pitstop notify off` | `pitstop notify on` · `pitstop notify off` | Show the output line. |
| `/pitstop gap <what was missing>` | `pitstop gap "<what was missing>"` | Show the output line. |
| `/pitstop now` | Follow "Manual pitstop". | |

A command that exits non-zero prints `🔋 pitstop · <reason>`: show that line to the user and stop.

## Automatic pitstop

A `[pitstop]` hook message gives you: mode, context, cwd, background tasks, and the step before the next request.

1. **When.** Mode `conversation`: now. Mode `superpowers`: finish the current step up to the boundary named in
   the message, then come back here before starting anything new.
2. **Exceptions.** Skip the pitstop when any of these applies:
   - a debugging session is half-way (discarded hypotheses and observed output live only in this context);
   - you are fine-editing a long text you already read (you need the exact text);
   - the work ends within about ten exchanges;
   - subagents or background tasks are still running;
   - a brainstorming or grilling session is half-way.

   When in doubt, skip. To skip, print exactly this line and carry on normally:
   `🔋 **pitstop** · saltato: <motivo in italiano>`
3. Otherwise run the "Checkpoint procedure" with `--cwd <cwd from the message>`.

## Manual pitstop

`/pitstop now`: no exceptions, the user asked. Run the "Checkpoint procedure" now, without `--cwd`.

## Checkpoint procedure

1. Run `pitstop new-checkpoint`. It prints the checkpoint path P.
2. Write the checkpoint (see "Checkpoint content") to P with the Write tool.
   If the write fails or is refused, print `🔋 **pitstop** · fallito: checkpoint non scritto → continuo qui`
   and stop the procedure.
3. Run `pitstop mark-pending --checkpoint P`, adding `--cwd <cwd>` for an automatic pitstop and
   `--plan <plan path>` when a superpowers plan is being executed. If it exits non-zero, print
   `🔋 **pitstop** · fallito: <its reason> → continuo qui` and stop the procedure.
4. Print the last line of its output (`🔋 **pitstop** · fatto a …`) as a line of its own.
5. Print, as the last line of your reply:
   `Scrivi /clear, poi un messaggio qualsiasi (per esempio «riprendi»): riparto dal checkpoint entro 10 minuti.`
   Then end your turn. Do not call `mcp__ccd_session_mgmt__clear_session`: the desktop app drops the clear it queues.

   The clean session receives the checkpoint by itself: do not paste it anywhere else.

## Checkpoint content

Markdown, in Italian like the conversation, at most about 4K tokens. It points to files and artifacts and never
summarizes them.

```markdown
# Checkpoint pitstop — <session topic>

## Obiettivo
## Stato attuale
## Prossima azione
<one precise action>
## Decisioni prese
- <decision> — <reason>
## Preferenze dell'utente
- "<exact quote>"
## Scartato
- <option> — <why>
## Da rileggere
- `path/to/file:line` — <why the next action needs it>
## Lavoro non salvato o non committato
## Domande aperte
## Skill suggerite
```

- Quote user preferences word for word.
- Cite files as `path:line`; name specs, plans, ledgers and PRs by path or URL.
- Superpowers: point to spec, plan, ledger and workspace; name the current task and the open decisions. Do not restate them.
- Leave out secrets, tokens, passwords and personal data.
- Write `—` under an empty section.

## Resuming

The first message after `/clear` (any text) arrives with a `[pitstop]` checkpoint; follow the steps in that
message: re-read only the cited files the next action needs, print `🔋 **pitstop** · ripartito da <K> · Dove eravamo:`
with three short lines (goal, state, next action), then continue. If something is missing, run
`pitstop gap "<what was missing>"` and recover it.
