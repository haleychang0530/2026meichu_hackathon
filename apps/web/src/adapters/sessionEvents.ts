import type { StudentSessionEvent } from './adapter';

/**
 * Consume complete SSE frames and return the not-yet-complete remainder.
 * The Core API sends one JSON SessionEvent envelope in each data field.  A
 * parser is kept separate from the fetch loop so reconnect and replay logic
 * can be tested without a browser EventSource implementation.
 */
export function consumeSessionEventFrames(
  input: string,
  onEvent: (event: StudentSessionEvent) => void,
): string {
  const normalized = input.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const frames = normalized.split('\n\n');
  const remainder = frames.pop() ?? '';

  for (const frame of frames) {
    const event = parseSessionEventFrame(frame);
    if (event) onEvent(event);
  }
  return remainder;
}

export function parseSessionEventFrame(frame: string): StudentSessionEvent | null {
  let eventId: number | null = null;
  const dataLines: string[] = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith(':')) continue;
    if (line.startsWith('id:')) {
      const parsed = Number(line.slice(3).trim());
      if (Number.isInteger(parsed) && parsed > 0) eventId = parsed;
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (eventId === null || dataLines.length === 0) return null;
  try {
    const payload = JSON.parse(dataLines.join('\n')) as unknown;
    if (!isRecord(payload) || payload.event_id !== eventId) return null;
    if (typeof payload.session_id !== 'string' || typeof payload.event !== 'string') return null;
    if (typeof payload.revision !== 'number' || !Number.isInteger(payload.revision)) return null;
    if (typeof payload.request_id !== 'string' || !isRecord(payload.payload)) return null;
    return payload as StudentSessionEvent;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
