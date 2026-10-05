// Spike: does a mod-driven compaction replace the manual /clear?
// /pitstop-spike arm [checkpoint]  -> compacts when the next turn ends, keeping that turn's answer
// The host refuses a compaction from prompt.submit (and from work it started), and a hot reload drops
// timers started in session.start, so the compaction runs from turn.complete, after the turn.
// /pitstop-spike last              -> pane with the answer kept before the compaction
// /pitstop-spike status            -> what happened, with context tokens before and after
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionMessage } from 'claude-code'

import type { Armed, SpikeEvent } from '../types'

const PANE = 'pitstop-last'
const armed = atom({ plugin: 'pitstop-spike', key: 'armed' } as const, null as Armed | null)
const last = atom({ plugin: 'pitstop-spike', key: 'last' } as const, '')
const log = atom({ plugin: 'pitstop-spike', key: 'log' } as const, [] as SpikeEvent[])

const DEFAULT_CHECKPOINT =
  'Pitstop spike checkpoint. Task: verify the mod compaction. Say "checkpoint ricevuto" and quote the first line of the previous answer below.'

// The last turn's visible answer: assistant text after the last prompt the person typed.
function lastAnswer(messages: readonly SessionMessage[]): string {
  const texts: string[] = []
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.role === 'user' && !m.toolResults?.length) break
    if (m.role === 'assistant' && m.text) texts.unshift(m.text)
  }
  return texts.join('\n\n')
}

async function note($: EngineInterface, what: string) {
  const tokens = (await $.session.usage()).context.tokens
  const at = await $.clock.now()
  await update($, log, list => [...list, { at, what, tokens }].slice(-50))
}

// Compacts once the turn has ended; retries from a timer if the host still counts the turn as running.
async function compactNow($: EngineInterface, tries = 1): Promise<void> {
  try {
    const r = await $.session.compact({ instructions: 'pitstop' })
    await note($, r.skip ? `compact skipped: ${r.skip}` : `compacted after the turn (try ${tries})`)
    if (r.skip) await update($, armed, () => null)
  } catch (err) {
    if (tries < 5) {
      await note($, `compact failed, retrying: ${String(err)}`)
      $.clock.after(300 * tries, () => void compactNow($, tries + 1))
      return
    }
    await note($, `gave up: ${String(err)}`)
    await update($, armed, () => null)
    $.ui.status(undefined)
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'pitstop-spike',
      description: 'Spike: arm a pitstop that compacts when the next turn ends (arm | last | status | disarm)',
      argumentHint: 'arm [checkpoint] | last | status | disarm',
    })
    return next(e)
  })

  on('command.run', { command: 'pitstop-spike' }, async ($, e) => {
    const [sub, ...rest] = e.args.trim().split(/\s+/)
    if (sub === 'arm') {
      const tokens = (await $.session.usage()).context.tokens
      const armedAt = await $.clock.now()
      await update($, armed, () => ({ checkpoint: rest.join(' ') || DEFAULT_CHECKPOINT, lastAnswer: '', armedAt, tokensAtArm: tokens }))
      await note($, 'armed')
      $.ui.status('pitstop armato: compatta a fine del prossimo turno')
      return { text: `Pitstop armato a ${tokens ?? '?'} token: compatta alla fine del prossimo turno.` }
    }
    if (sub === 'disarm') {
      await update($, armed, () => null)
      $.ui.status(undefined)
      return { text: 'Pitstop disarmato.' }
    }
    if (sub === 'last') {
      await $.ui.open({ id: PANE, title: 'Ultima risposta prima del pitstop' })
      return { text: 'Pannello aperto.' }
    }
    const list = await read($, log)
    return {
      text: list.length
        ? list.map(x => `${typeof x.at === 'number' ? new Date(x.at).toISOString().slice(11, 19) : '--:--:--'}  ${x.tokens ?? '?'}  ${x.what}`).join('\n')
        : 'Nessun evento.',
    }
  })

  // The compaction itself: the conversation becomes the checkpoint plus the last answer, verbatim.
  on('session.compact', { trigger: 'plugin' }, async ($, e, next) => {
    const a = await read($, armed)
    if (!a || e.agentId) return next(e)
    await update($, armed, () => null)
    $.ui.status(undefined)
    const messages: SessionMessage[] = [
      {
        role: 'user',
        text: `[pitstop] Ripresa da checkpoint.\n\n${a.checkpoint}\n\nLa tua ultima risposta prima del pitstop segue alla lettera.`,
        toolUses: [],
      },
      { role: 'assistant', text: a.lastAnswer || '(nessuna risposta trovata)', toolUses: [] },
    ]
    return { messages }
  })

  // At the end of the armed turn: keep its answer, then compact.
  on('turn.complete', async ($, e, next) => {
    const r = await next(e)
    if (e.agentId) return r
    const list = await read($, log)
    const prev = list[list.length - 1]
    if (prev && prev.what.startsWith('compacted')) await note($, 'first turn after compaction')
    const a = await read($, armed)
    if (!a || e.reason !== 'answer') return r
    const messages = await $.session.messages()
    const answer = Array.isArray(messages) ? lastAnswer(messages) : ''
    await update($, armed, x => (x ? { ...x, lastAnswer: answer } : x))
    await update($, last, () => answer)
    await note($, `turn ended (answer ${answer.length} chars), compacting`)
    await compactNow($)
    return r
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Markdown, Text } = $.ui.resolve(e)
    const text = await read($, last)
    return (
      <Box flexDirection="column">
        {text ? <Markdown text={text.slice(0, 10000)} /> : <Text dimColor>Nessuna risposta salvata.</Text>}
      </Box>
    )
  })
}
