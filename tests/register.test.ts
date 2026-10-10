import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const HOME = '/home/u'
const PENDING = `${HOME}/.claude/pitstop/pending`
const NOW = 1_800_000_000_000
const SUMMARY = 'Resume from the pitstop checkpoint.'

type World = { files: Record<string, string>; env?: Record<string, string>; calls: string[] }

function world(on: On, w: World) {
  mock.env(on, { HOME, ...w.env })
  const clock = mock.clock(on, { now: NOW })
  on('session.id', () => ({ value: 's1' }))
  on('fs.exists', (_$, e) => ({ value: Object.keys(w.files).some(p => p.startsWith(e.path)) }))
  on('fs.list', (_$, e) => ({
    value: Object.keys(w.files)
      .filter(p => p.startsWith(`${e.path}/`))
      .map(p => ({ name: p.slice(e.path.length + 1), kind: 'file' as const, size: 1, mtimeMs: NOW })),
  }))
  on('fs.read', (_$, e) => {
    const text = w.files[e.path]
    if (text === undefined) throw new Error('ENOENT')
    return { value: text }
  })
  on('command.run', (_$, e) => {
    w.calls.push(`/${e.command} ${e.args}`)
    return { text: '' }
  })
  on('prompt.submit', (_$, e) => {
    w.calls.push(e.text)
    return { text: e.text }
  })
  on('ui.toast', () => ({ value: undefined }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  return clock
}

const record = (sessionId: string, ageMinutes = 1) =>
  JSON.stringify({ session_id: sessionId, created_at: NOW / 1000 - ageMinutes * 60, checkpoint: '/cp.md' })

const turn = { answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as const

test('compacts, then queues the resume message, once per record', async ($, on) => {
  const w: World = { files: { [`${PENDING}/1-a.json`]: record('s1') }, calls: [] }
  const clock = world(on, w)
  await $.turn.complete(turn)
  await clock.advance(1)
  expect(w.calls).toEqual([`/compact One-line summary: "${SUMMARY}"`, SUMMARY])
  await $.turn.complete(turn)
  await clock.advance(1)
  expect(w.calls.length).toBe(2)
})

test('leaves the session alone without a checkpoint of its own in the window', async ($, on) => {
  const w: World = {
    files: {
      [`${PENDING}/1-a.json`]: record('other'),
      [`${PENDING}/2-b.json`]: record('s1', 61),
      [`${PENDING}/.3-c.json`]: record('s1'),
    },
    calls: [],
  }
  const clock = world(on, w)
  await $.turn.complete(turn)
  await clock.advance(1)
  expect(w.calls).toEqual([])
})

test('does nothing in an SDK host, where the skill queues its own /compact', async ($, on) => {
  const w: World = {
    files: { [`${PENDING}/1-a.json`]: record('s1') },
    env: { CLAUDE_CODE_ENTRYPOINT: 'sdk-ts' },
    calls: [],
  }
  const clock = world(on, w)
  await $.turn.complete(turn)
  await clock.advance(1)
  expect(w.calls).toEqual([])
})

test('restarts under claude -p, which has no thread to queue on', async ($, on) => {
  const w: World = {
    files: { [`${PENDING}/1-a.json`]: record('s1') },
    env: { CLAUDE_CODE_ENTRYPOINT: 'sdk-cli' },
    calls: [],
  }
  const clock = world(on, w)
  await $.turn.complete(turn)
  await clock.advance(1)
  expect(w.calls.length).toBe(2)
})

test('does nothing after an interrupted turn or a subagent turn', async ($, on) => {
  const w: World = { files: { [`${PENDING}/1-a.json`]: record('s1') }, calls: [] }
  const clock = world(on, w)
  await $.turn.complete({ ...turn, reason: 'aborted', isAborted: true })
  await $.turn.complete({ ...turn, agentId: 'a1' })
  await clock.advance(1)
  expect(w.calls).toEqual([])
})
