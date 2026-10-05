export type Armed = { checkpoint: string; lastAnswer: string; armedAt: number; tokensAtArm?: number }
export type SpikeEvent = { at: number; what: string; tokens?: number }

declare module 'claude-code' {
  interface PluginState {
    'pitstop-spike': { armed: Armed | null; last: string; log: SpikeEvent[] }
  }
}
