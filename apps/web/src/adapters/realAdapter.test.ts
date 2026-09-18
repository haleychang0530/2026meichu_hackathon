import { afterEach, describe, expect, it, vi } from 'vitest';
import { RealAdapter } from './realAdapter';

const healthPayload = {
  schema_version: '0.1.0',
  request_id: '00000000-0000-4000-8000-000000000101',
  status: 'ready',
  services: [
    {
      schema_version: '0.1.0',
      service: 'core-api',
      status: 'ready',
      device: 'laptop',
      model_revision: null,
      queue_depth: 0,
      last_error: null,
      checked_at: '2026-09-17T10:00:00+08:00',
    },
    {
      schema_version: '0.1.0',
      service: 'asr',
      status: 'ready',
      device: 'laptop',
      model_revision: 'breeze-cpu-v0.1',
      queue_depth: 0,
      last_error: null,
      checked_at: '2026-09-17T10:00:00+08:00',
    },
  ],
};

const sessionPayload = {
  schema_version: '0.1.0',
  session_id: 'session_demo_001',
  lesson_id: 'lesson_market_001',
  state: 'SPEAKING',
  phase: 'introduction',
  progress: 0.4,
  current_prompt: '請說：阿媽欲去市場。',
  can_answer: false,
  revision: 0,
  last_event_id: 0,
};

const lessonPayload = {
  schema_version: '0.1.0',
  lesson_id: 'lesson_market_001',
  topic: '去市場',
  source_text: '阿媽欲去市場買菜。',
  vocabulary: [],
  scene: '市場情境。',
  original_activity: '看圖回答。',
  learning_objective: '練習市場詞彙。',
  accessible_activity: '聽線索回答。',
  evidence: [],
  confidence: 0.9,
  review_status: 'pending',
  vlm_model_revision: null,
  rag_index_revision: null,
};

const actionPayload = {
  schema_version: '0.1.0',
  session_id: 'session_demo_001',
  lesson_id: 'lesson_market_001',
  state: 'SPEAKING',
  progress: 0.4,
  current_prompt: '想想人物要去哪裡。',
  action: 'request_hint',
  feedback: '提示已準備完成。',
  next_prompt: '請再說一次：阿媽欲去市場。',
  can_answer: false,
  phase: 'hint',
  revision: 1,
  last_event_id: 1,
};

const turnPayload = {
  schema_version: '0.1.0',
  turn_id: 'turn_001',
  session_id: 'session_demo_001',
  transcript_raw: '市場',
  transcript_normalized: '市場',
  result: 'correct',
  matched_concepts: ['市場'],
  feedback: '答對了。',
  next_prompt: '請說：阿媽欲去市場。',
  progress: 0.4,
  latency_ms: { asr: 820, backend: 95, vlm: null, tts: 310, total: 1225 },
  asr_device: 'cpu',
  fallbacks: ['asr_cpu'],
  phase: 'comprehension',
  revision: 2,
  last_event_id: 2,
};

const summaryPayload = {
  schema_version: '0.1.0',
  session_id: 'session_demo_001',
  lesson_id: 'lesson_market_001',
  state: 'SPEAKING',
  progress: 0.4,
  completed_turns: 1,
  turns: [turnPayload],
  concepts_to_review: ['欲去'],
  hint_history: [],
  familiarity: [{ concept: '市場', status: 'developing' }],
};

function jsonResponse(
  payload: unknown,
  status = 200,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

describe('RealAdapter', () => {
  afterEach(() => vi.restoreAllMocks());

  it('sends the prepared image as multipart data to Core Backend without a JSON content type', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/health')) return jsonResponse(healthPayload);
      if (url.endsWith('/api/lessons/analyze')) {
        expect(init?.method).toBe('POST');
        expect(new Headers(init?.headers).get('content-type')).toBeNull();
        expect(init?.body).toBeInstanceOf(FormData);
        const form = init?.body as FormData;
        expect(form.get('language')).toBe('nan-TW');
        expect(form.get('use_fixture_on_failure')).toBe('true');
        const image = form.get('image');
        expect(image).toBeInstanceOf(Blob);
        expect((image as File).name).toBe('lesson.jpg');
        expect((image as Blob).type).toBe('image/jpeg');
        return jsonResponse(lessonPayload, 200, { 'X-Provider-Mode': 'fixture-fallback' });
      }
      throw new Error(`Unexpected URL: ${url}`);
    });

    const view = await new RealAdapter('http://127.0.0.1:8000').analyzeLesson({
      blob: new Blob(['synthetic image bytes'], { type: 'image/jpeg' }),
      fileName: 'lesson.jpg',
      mimeType: 'image/jpeg',
      width: 1280,
      height: 720,
      sourceBytes: 22,
      quality: {
        status: 'good',
        width: 1280,
        height: 720,
        bytes: 22,
        mimeType: 'image/jpeg',
        issues: [],
      },
    });

    expect(view.lessonId).toBe('lesson_market_001');
    expect(view.title).toBe('去市場');
    expect(view.providerMode).toBe('fixture-fallback');
    expect(view.canConfirm).toBe(true);
  });

  it('uses the Stage 04 health route as the capture entrypoint before Stage 08 routes exist', async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith('/api/health')) return jsonResponse(healthPayload);
      throw new Error(`Unexpected URL: ${url}`);
    });

    const view = await new RealAdapter('http://127.0.0.1:8000').getCapture();

    expect(view.lessonId).toBe('pending-capture');
    expect(view.canConfirm).toBe(false);
    expect(view.providerMode).toBe('real');
    expect(calls).toEqual(['http://127.0.0.1:8000/api/health']);
  });

  it('maps the canonical control action and sends no query-string action', async () => {
    const calls: Array<{ readonly url: string; readonly init?: RequestInit }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push({ url, init });
      if (url.endsWith('/api/health')) return jsonResponse(healthPayload);
      if (url.endsWith('/api/sessions/session_demo_001/actions')) {
        expect(JSON.parse(String(init?.body))).toEqual({
          schema_version: '0.1.0',
          action: 'request_hint',
          input_mode: 'keyboard',
        });
        return jsonResponse(actionPayload);
      }
      throw new Error(`Unexpected URL: ${url}`);
    });

    const view = await new RealAdapter('http://127.0.0.1:8000').submitStudentAction(
      'session_demo_001',
      'hint',
    );

    expect(view.feedback).toContain('提示已準備完成');
    expect(view.canAnswer).toBe(false);
    expect(calls.map((call) => call.url)).not.toContain(
      'http://127.0.0.1:8000/api/sessions/session_demo_001/turns?action=hint',
    );
  });

  it('sends answer submissions to /turns with the generated contract shape', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/health')) return jsonResponse(healthPayload);
      if (url.endsWith('/api/sessions/session_demo_001/turns')) {
        expect(JSON.parse(String(init?.body))).toEqual({
          schema_version: '0.1.0',
          transcript: '市場',
          input_mode: 'voice',
          asr_device: 'cpu',
        });
        return jsonResponse(turnPayload);
      }
      throw new Error(`Unexpected URL: ${url}`);
    });

    const view = await new RealAdapter().submitStudentAnswer('session_demo_001', {
      schema_version: '0.1.0',
      transcript: '市場',
      input_mode: 'voice',
      asr_device: 'cpu',
    });

    expect(view.feedback).toBe('答對了。');
    expect(view.progressValue).toBe(40);
  });

  it('maps teacher-only summary data without putting it into the student view', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/api/health')) return jsonResponse(healthPayload);
      if (url.endsWith('/api/sessions/session_demo_001/summary')) return jsonResponse(summaryPayload);
      if (url.endsWith('/api/lessons/lesson_market_001')) return jsonResponse(lessonPayload);
      throw new Error(`Unexpected URL: ${url}`);
    });

    const view = await new RealAdapter().getObserverSession('session_demo_001');

    expect(view.lessonTitle).toBe('去市場');
    expect(view.transcript).toBe('市場');
    expect(view.evaluation).toBe('correct');
    expect(view.latencyMs.total).toBe(1225);
    expect(view).not.toHaveProperty('confidence');
    expect(view).not.toHaveProperty('answer');
  });

  it('sends the current revision and a stable idempotency key for student mutations', async () => {
    const calls: Array<{ readonly url: string; readonly headers: Headers }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push({ url, headers: new Headers(init?.headers) });
      if (url.endsWith('/api/health')) return jsonResponse(healthPayload);
      if (url.endsWith('/api/sessions/session_demo_001/actions')) return jsonResponse(actionPayload);
      if (url.endsWith('/api/sessions/session_demo_001/turns')) return jsonResponse(turnPayload);
      throw new Error(`Unexpected URL: ${url}`);
    });

    const adapter = new RealAdapter('http://127.0.0.1:8000');
    await adapter.submitStudentAction('session_demo_001', 'hint', {
      expectedRevision: 4,
      idempotencyKey: 'action-hint-fixed',
    });
    await adapter.submitStudentAnswer('session_demo_001', {
      schema_version: '0.1.0',
      transcript: '市場',
      input_mode: 'keyboard',
    }, {
      expectedRevision: 5,
      idempotencyKey: 'turn-fixed',
    });

    const actionCall = calls.find((call) => call.url.endsWith('/actions'));
    const turnCall = calls.find((call) => call.url.endsWith('/turns'));
    expect(actionCall?.headers.get('Idempotency-Key')).toBe('action-hint-fixed');
    expect(actionCall?.headers.get('X-Session-Revision')).toBe('4');
    expect(turnCall?.headers.get('Idempotency-Key')).toBe('turn-fixed');
    expect(turnCall?.headers.get('X-Session-Revision')).toBe('5');
  });

  it('replays student-safe SSE events from the durable cursor', async () => {
    const calls: Array<{ readonly url: string; readonly headers: Headers }> = [];
    const frame = `id: 3\nevent: session.action\ndata: ${JSON.stringify({
      schema_version: '0.1.0',
      event_id: 3,
      session_id: 'session_demo_001',
      event: 'session.action',
      request_id: 'request-3',
      revision: 4,
      payload: { feedback: 'student-safe' },
    })}\n\n`;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      calls.push({ url: String(input), headers: new Headers(init?.headers) });
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(frame));
          controller.close();
        },
      });
      return new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } });
    });

    const received = new Promise<number>((resolve) => {
      let unsubscribe: () => void = () => undefined;
      unsubscribe = new RealAdapter('http://127.0.0.1:8000').subscribeStudentSession('session_demo_001', {
        afterEventId: 2,
        onEvent: (event) => {
          resolve(event.event_id);
          unsubscribe();
        },
        onError: () => undefined,
      });
    });

    await expect(received).resolves.toBe(3);
    expect(calls[0].url).toBe('http://127.0.0.1:8000/api/sessions/session_demo_001/events');
    expect(calls[0].headers.get('Last-Event-ID')).toBe('2');
  });
});
