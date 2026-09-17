import { describe, expect, it } from 'vitest';
import { parseRoute } from './routing';

describe('parseRoute', () => {
  it('supports the four Stage 02 routes', () => {
    expect(parseRoute('/setup')).toEqual({ kind: 'setup' });
    expect(parseRoute('/capture/')).toEqual({ kind: 'capture' });
    expect(parseRoute('/session/demo%2Fone/student')).toEqual({ kind: 'student', sessionId: 'demo/one' });
    expect(parseRoute('/session/demo-session/observer')).toEqual({ kind: 'observer', sessionId: 'demo-session' });
  });

  it('returns an explicit not-found route', () => {
    expect(parseRoute('/unknown')).toEqual({ kind: 'not_found', path: '/unknown' });
  });
});
