// Terminal and `claude -p` restart, hands-off: once a turn ends with a checkpoint this session has just registered,
// run /compact and queue the resume message. The SessionStart hook (source compact) injects the checkpoint.
import type { Register } from 'claude-code'

type Engine = Parameters<Parameters<Parameters<Register>[0]>[1]>[0]

// Must match COMPACT_SUMMARY in pitstop/claude/messages.py.
const SUMMARY = 'Resume from the pitstop checkpoint.'
const DEFAULT_WINDOW_MINUTES = 60
async function isSdkHost($: Engine): Promise<boolean> {
  // SDK hosts (T3 Code) restart through the skill's own queued /compact. `claude -p` (sdk-cli) has no
  // thread to queue on, so it restarts here like the terminal.
  const entrypoint = (await $.env.get('CLAUDE_CODE_ENTRYPOINT')) ?? ''
  return entrypoint.startsWith('sdk') && entrypoint !== 'sdk-cli'
}

async function pitstopHome($: Engine): Promise<string> {
  return (await $.env.get('PITSTOP_HOME')) || `${await $.env.get('HOME')}/.claude/pitstop`
}

async function windowSeconds($: Engine, home: string): Promise<number> {
  const path = `${home}/config.json`
  try {
    if (await $.fs.exists(path)) {
      const minutes = JSON.parse(await $.fs.read(path)).resume_window_minutes
      if (typeof minutes === 'number') return minutes * 60
    }
  } catch {
    // An invalid config: the default window.
  }
  return DEFAULT_WINDOW_MINUTES * 60
}

/** The name of this session's pending record, if it is still within the resume window. */
async function pendingRecord($: Engine, sessionId: string): Promise<string | undefined> {
  const home = await pitstopHome($)
  const dir = `${home}/pending`
  if (!(await $.fs.exists(dir))) return undefined
  const window = await windowSeconds($, home)
  const now = (await $.clock.now()) / 1000
  for (const entry of await $.fs.list(dir)) {
    if (entry.kind !== 'file' || !entry.name.endsWith('.json') || entry.name.startsWith('.')) continue
    try {
      const record = JSON.parse(await $.fs.read(`${dir}/${entry.name}`))
      if (record.session_id === sessionId && now - record.created_at <= window) return entry.name
    } catch {
      // A record claimed or removed meanwhile: not ours to restart from.
    }
  }
  return undefined
}

async function restart($: Engine): Promise<void> {
  try {
    await $.command.run({ command: 'compact', args: `One-line summary: "${SUMMARY}"` })
    await $.prompt.submit({ text: SUMMARY })
  } catch {
    await $.ui.toast('pitstop: automatic restart failed, run /clear and send any message')
  }
}

export const register: Register = on => {
  // One restart per record: if the checkpoint is not consumed, never compact twice for it.
  const restarted = new Set<string>()

  on('session.start', async ($, e, next) => {
    // Tells `pitstop mark-pending` (run later from Bash) that this module will restart the session.
    if (!(await isSdkHost($))) await $.env.set('PITSTOP_AUTO_RESTART', '1')
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    try {
      if (e.agentId !== undefined || e.reason !== 'answer' || (await isSdkHost($))) return done
      const name = await pendingRecord($, await $.session.id())
      if (name === undefined || restarted.has(name)) return done
      restarted.add(name)
      // After this hook returns: both calls queue and run once the session is idle, in order.
      $.clock.after(0, () => {
        void restart($)
      })
    } catch {
      // Fail open, as every pitstop hook does.
    }
    return done
  })
}
