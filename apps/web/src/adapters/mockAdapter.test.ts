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
    await adapter.submitStudentAnswer('demo-session', {
      schema_version: '0.1.0',
      transcript: '這是一段 Mock 學生回答。',
      input_mode: 'keyboard',
    });
    const observer = await adapter.getObserverSession('demo-session');
    expect(observer.evaluation).toBe('partial');
    expect(observer.transcript).toContain('Mock 學生回答');
  });

  it('projects the observer dashboard fields and supports review/control actions', async () => {
    const adapter = new MockAdapter();
    const initial = await adapter.getObserverSession('demo-session');

    expect(initial.lesson.vocabulary[0].tailo).toBe('tshī-tiûnn');
    expect(initial.evidence[0].locator).toBe('demo/market');
    expect(initial.health.services.map((service) => service.service)).toEqual([
      'Core Backend', 'Local RAG', 'MI300 VLM', 'ASR', 'TTS',
    ]);

    await adapter.reviewLesson('demo-lesson', {
      topic: '修改後的水果活動',
      accessibleActivity: '聽線索後說出自己的觀察。',
    });
    const reviewed = await adapter.getObserverSession('demo-session');
    expect(reviewed.lesson.topic).toBe('修改後的水果活動');
    expect(reviewed.lesson.accessibleActivity).toContain('自己的觀察');

    const skipped = await adapter.submitObserverAction('demo-session', 'skip');
    expect(skipped.phase).toBe('review');
    const reset = await adapter.submitObserverAction('demo-session', 'reset');
    expect(reset.completedTurns).toBe(0);
    expect(reset.lesson.reviewStatus).toBe('pending');
  });
});
