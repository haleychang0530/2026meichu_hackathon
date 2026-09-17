import { describe, expect, it } from 'vitest';
import { MockAdapter } from './mockAdapter';

describe('MockAdapter', () => {
  it('keeps observer-only fields out of the student response', async () => {
    const adapter = new MockAdapter();
    const student = await adapter.getStudentSession('demo-session');
    expect(student).not.toHaveProperty('answer');
    expect(student).not.toHaveProperty('confidence');
    expect(student).not.toHaveProperty('teacher');
    expect(student.prompt).toContain('沒有顯示標準答案');
  });

  it('keeps state across student and observer adapters calls', async () => {
    const adapter = new MockAdapter();
    await adapter.submitStudentAction('demo-session', 'answer');
    const observer = await adapter.getObserverSession('demo-session');
    expect(observer.evaluation).toBe('partial');
    expect(observer.transcript).toContain('Mock 學生回答');
  });
});
