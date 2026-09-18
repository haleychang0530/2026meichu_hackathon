import { describe, expect, it } from 'vitest';
import { consumeSessionEventFrames, parseSessionEventFrame } from './sessionEvents';

const event = (eventId: number, revision = eventId) => ({
  schema_version: '0.1.0',
  event_id: eventId,
  session_id: 'session_demo_001',
  event: 'session.action',
  request_id: `request-${eventId}`,
  revision,
  payload: { feedback: 'student-safe' },
});

describe('session SSE parser', () => {
  it('parses complete frames and retains a partial frame for the next chunk', () => {
    const received: unknown[] = [];
    const first = `id: 1\nevent: session.action\ndata: ${JSON.stringify(event(1))}\n\n`;
    const second = `id: 2\nevent: session.action\ndata: ${JSON.stringify(event(2))}`;

    const remainder = consumeSessionEventFrames(`${first}${second}`, (next) => received.push(next));

    expect(received).toEqual([event(1)]);
    expect(remainder).toContain('id: 2');
    expect(parseSessionEventFrame(`${remainder}\n\n`)).toEqual(event(2));
  });

  it('ignores heartbeats, malformed JSON, and mismatched durable ids', () => {
    expect(parseSessionEventFrame(': heartbeat')).toBeNull();
    expect(parseSessionEventFrame('id: 3\ndata: {not-json}')).toBeNull();
    expect(parseSessionEventFrame(`id: 3\ndata: ${JSON.stringify(event(4))}`)).toBeNull();
  });
});
