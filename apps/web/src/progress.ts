export type ProgressEvent = { sequence: number; type: string; payload: Record<string, string> }
export type TerminalTurn = { state: string; correlation_id: string }

export function progressLabel(event: ProgressEvent): string | null {
  if (event.payload.label?.trim()) return event.payload.label
  if (event.type === 'agent.status' && event.payload.status) return event.payload.status.replaceAll('_', ' ')
  if (event.type.startsWith('tool.') && event.payload.tool) {
    const action = event.type === 'tool.requested' ? 'Requested' : event.type === 'tool.started' ? 'Running' : event.type === 'tool.completed' ? 'Completed' : 'Tool'
    return `${action} ${event.payload.tool}`
  }
  return null
}

export function terminalTurnError(turn?: TerminalTurn | null): string | null {
  return turn?.state === 'failed'
    ? `The durable agent could not complete this run. Reference: ${turn.correlation_id}`
    : null
}
