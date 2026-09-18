import { adapterErrorFromResponse } from './errors';
import { consumeSessionEventFrames } from './sessionEvents';
import type {
  FrontendAdapter,
  StudentRequestOptions,
  StudentSessionEvent,
  StudentSessionStreamOptions,
} from './adapter';
import type { components, operations } from '../generated/api';
import type {
  CaptureProviderMode,
  CaptureViewModel,
  HealthSummaryView,
  LessonImageUpload,
  ObserverSessionViewModel,
  ServiceHealthView,
  SetupViewModel,
  SessionState,
  StudentAction,
  StudentSessionViewModel,
  TeachingPhase,
} from '../types/viewModels';

type CoreHealthResponse = operations['getHealth']['responses'][200]['content']['application/json'];
type CoreAnalyzeLessonResponse = operations['analyzeLesson']['responses'][200]['content']['application/json'];
type CoreLesson = components['schemas']['Lesson'];
type CoreSession = components['schemas']['Session'];
type CoreTurnResult = components['schemas']['TurnResult'];
type CoreObserverSummary = components['schemas']['ObserverSessionSummary'];
type CoreStudentActionResult = components['schemas']['StudentAction'];
type CoreStudentAction = components['schemas']['action'];
type CoreStudentActionRequest = components['schemas']['StudentActionRequest'];
type CoreTurnSubmission = components['schemas']['TurnSubmission'];
type CoreServiceHealth = components['schemas']['ServiceHealth'];

const DEMO_LESSON_ID = 'lesson_market_001';
const PENDING_CAPTURE_ID = 'pending-capture';
const SCHEMA_VERSION = '0.1.0' as const;

const actionMap: Record<StudentAction, CoreStudentAction> = {
  listen: 'replay_prompt',
  answer: 'start_answer',
  hint: 'request_hint',
  pause: 'pause',
  resume: 'resume',
  next: 'next',
};

function createIdempotencyKey(prefix: string): string {
  const suffix = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${suffix}`;
}

function isAbortError(error: unknown): boolean {
  return (
    (typeof DOMException !== 'undefined' && error instanceof DOMException && error.name === 'AbortError')
    || (error instanceof Error && error.name === 'AbortError')
  );
}

function serviceLabel(service: CoreServiceHealth['service']): string {
  const labels: Record<CoreServiceHealth['service'], string> = {
    'core-api': 'Core Backend',
    rag: 'Local RAG',
    'vlm-mi300': 'MI300 VLM',
    asr: 'Speech ASR',
    tts: 'Speech TTS',
  };
  return labels[service];
}

function toHealthSummary(payload: CoreHealthResponse): HealthSummaryView {
  const services: readonly ServiceHealthView[] = payload.services.map((service) => ({
    service: serviceLabel(service.service),
    status: service.status,
    device: service.device ?? 'unknown',
    modelRevision: service.model_revision ?? undefined,
    lastError: service.last_error?.message,
  }));
  const checkedAt = [...payload.services]
    .map((service) => service.checked_at)
    .sort()
    .at(-1) ?? new Date().toISOString();
  return {
    status: payload.status,
    checkedAt,
    services,
  };
}

function degradedHealth(message: string): HealthSummaryView {
  const checkedAt = new Date().toISOString();
  return {
    status: 'degraded',
    checkedAt,
    services: [
      {
        service: 'Core Backend',
        status: 'degraded',
        device: 'laptop',
        lastError: message,
      },
    ],
  };
}

function toCaptureView(lesson: CoreLesson, health: HealthSummaryView): CaptureViewModel {
  return {
    lessonId: lesson.lesson_id,
    title: lesson.topic,
    description: lesson.scene,
    reviewStatus: lesson.review_status,
    // v0.1 Lesson intentionally has no image URL. The Camera component owns
    // the short-lived local preview and Core Backend owns the uploaded bytes.
    images: [],
    health,
    providerMode: 'real',
    canConfirm: true,
  };
}

function pendingCaptureView(health: HealthSummaryView): CaptureViewModel {
  return {
    lessonId: PENDING_CAPTURE_ID,
    title: '等待教材分析',
    description: 'Core Backend 已就緒；請先拍攝或選擇一頁教材，再送出分析。',
    reviewStatus: 'pending',
    images: [],
    health,
    providerMode: 'real',
    canConfirm: false,
  };
}

function fixtureCaptureView(): CaptureViewModel {
  const checkedAt = new Date().toISOString();
  return {
    lessonId: 'fixture-lesson',
    title: '離線教材示範：水果攤',
    description: 'Core Backend 或 MI300 暫時離線；這是明確標示的合成教材，不代表即時分析結果。',
    reviewStatus: 'pending',
    images: [
      { src: '/lesson-images/lesson-market.svg', alt: '沒有角色的水果攤合成教材圖', label: '水果攤合成圖' },
      { src: '/lesson-images/lesson-shapes.svg', alt: '圓形、三角形與方形的合成教材圖', label: '形狀合成圖' },
    ],
    health: {
      status: 'degraded',
      checkedAt,
      services: [
        { service: 'Core Backend', status: 'offline', device: 'laptop', lastError: '目前使用前端離線 fixture。' },
        { service: 'MI300 VLM', status: 'offline', device: 'mi300', lastError: '尚未取得即時分析結果。' },
        { service: 'Local RAG', status: 'degraded', device: 'laptop', lastError: 'fixture 模式不使用 RAG。' },
      ],
    },
    providerMode: 'fixture',
    canConfirm: false,
  };
}

function providerModeFromHeader(value: string | null): CaptureProviderMode {
  if (value === 'fixture' || value === 'fixture-fallback' || value === 'mock') return value;
  return 'real';
}

function toProgress(progress: number): { readonly label: string; readonly value: number } {
  const value = Math.round(progress * 100);
  return { label: `目前進度 ${value}%`, value };
}

function toStudentView(
  session: CoreSession,
  health: HealthSummaryView,
  feedback = '尚未收到回饋。',
  transcript = '',
): StudentSessionViewModel {
  const progress = toProgress(session.progress);
  return {
    sessionId: session.session_id,
    lessonTitle: '目前教材',
    state: session.state as SessionState,
    phase: session.phase as TeachingPhase,
    prompt: session.current_prompt ?? '目前沒有可播放的提示。',
    feedback,
    progressLabel: progress.label,
    progressValue: progress.value,
    revision: session.revision,
    lastEventId: session.last_event_id,
    health,
    canAnswer: health.status !== 'offline' && session.can_answer && session.state !== 'COMPLETE',
    transcript,
    fallbacks: [],
  };
}

function toStudentActionView(
  actionResult: CoreStudentActionResult,
  health: HealthSummaryView,
  transcript = '',
): StudentSessionViewModel {
  const progress = toProgress(actionResult.progress);
  return {
    sessionId: actionResult.session_id,
    lessonTitle: '目前教材',
    state: actionResult.state as SessionState,
    phase: actionResult.phase as TeachingPhase,
    prompt: actionResult.current_prompt ?? actionResult.next_prompt ?? '目前沒有可播放的提示。',
    feedback: actionResult.feedback ?? '操作已完成。',
    progressLabel: progress.label,
    progressValue: progress.value,
    revision: actionResult.revision,
    lastEventId: actionResult.last_event_id,
    health,
    canAnswer: actionResult.can_answer && health.status !== 'offline',
    transcript,
    fallbacks: [],
  };
}

function toTurnStudentView(
  turn: CoreTurnResult,
  health: HealthSummaryView,
): StudentSessionViewModel {
  const progress = toProgress(turn.progress);
  return {
    sessionId: turn.session_id,
    lessonTitle: '目前教材',
    state: turn.phase === 'complete' ? 'COMPLETE' : 'SPEAKING',
    phase: turn.phase as TeachingPhase,
    prompt: turn.next_prompt,
    feedback: turn.feedback,
    progressLabel: progress.label,
    progressValue: progress.value,
    revision: turn.revision,
    lastEventId: turn.last_event_id,
    health,
    canAnswer: health.status !== 'offline' && turn.phase !== 'complete',
    transcript: turn.transcript_raw,
    fallbacks: turn.fallbacks,
  };
}

export class RealAdapter implements FrontendAdapter {
  constructor(private readonly baseUrl = import.meta.env.VITE_CORE_API_BASE_URL || '') {}

  private url(path: string): string {
    const normalizedBase = this.baseUrl.replace(/\/+$/, '');
    if (!normalizedBase) return path;
    if (normalizedBase.endsWith('/api') && path.startsWith('/api/')) {
      return `${normalizedBase}${path.slice('/api'.length)}`;
    }
    return `${normalizedBase}${path}`;
  }

  private async request<T>(
    path: string,
    init?: RequestInit,
    options: StudentRequestOptions = {},
  ): Promise<T> {
    const result = await this.requestWithResponse<T>(path, init, options);
    return result.payload;
  }

  private async requestWithResponse<T>(
    path: string,
    init?: RequestInit,
    options: StudentRequestOptions = {},
  ): Promise<{ readonly payload: T; readonly response: Response }> {
    const headers = new Headers(init?.headers);
    headers.set('Accept', 'application/json');
    const isMultipart = typeof FormData !== 'undefined' && init?.body instanceof FormData;
    if (init?.body && !headers.has('Content-Type') && !isMultipart) {
      headers.set('Content-Type', 'application/json');
    }
    if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey);
    if (options.expectedRevision !== undefined) {
      headers.set('X-Session-Revision', String(options.expectedRevision));
    }
    const response = await fetch(this.url(path), {
      ...init,
      signal: options.signal ?? init?.signal,
      headers,
    });
    if (!response.ok) throw await adapterErrorFromResponse(response);
    return { payload: (await response.json()) as T, response };
  }

  private async getHealth(signal?: AbortSignal): Promise<HealthSummaryView> {
    const payload = await this.request<CoreHealthResponse>('/api/health', signal ? { signal } : undefined);
    return toHealthSummary(payload);
  }

  private async getLesson(lessonId: string): Promise<CoreLesson> {
    return this.request<CoreLesson>(`/api/lessons/${encodeURIComponent(lessonId)}`);
  }

  async getSetup(): Promise<SetupViewModel> {
    const health = await this.getHealth();
    return {
      title: '聽見母語｜正式 API 流程',
      description: '服務健康狀態來自 Core Backend；教材、session 與回合狀態由 server-side session 管理。',
      health,
      nextRoute: '/capture',
    };
  }

  async getCapture(): Promise<CaptureViewModel> {
    // The capture landing page has no lesson id yet, so it only needs health.
    return pendingCaptureView(await this.getHealth());
  }

  async getCaptureFallback(): Promise<CaptureViewModel> {
    return fixtureCaptureView();
  }

  async analyzeLesson(image: LessonImageUpload, signal?: AbortSignal): Promise<CaptureViewModel> {
    const formData = new FormData();
    formData.append('image', image.blob, image.fileName);
    formData.append('language', 'nan-TW');
    formData.append('use_fixture_on_failure', 'true');
    const [analysis, health] = await Promise.all([
      this.requestWithResponse<CoreAnalyzeLessonResponse>('/api/lessons/analyze', {
        method: 'POST',
        body: formData,
        signal,
      }),
      this.getHealth(signal),
    ]);
    return {
      ...toCaptureView(analysis.payload, health),
      providerMode: providerModeFromHeader(analysis.response.headers.get('X-Provider-Mode')),
    };
  }

  async confirmLesson(lessonId: string): Promise<{ readonly sessionId: string }> {
    const session = await this.request<CoreSession>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ schema_version: SCHEMA_VERSION, lesson_id: lessonId }),
    }, { idempotencyKey: createIdempotencyKey('create-session') });
    return { sessionId: session.session_id };
  }

  async getStudentSession(
    sessionId: string,
    options: { readonly snapshot?: boolean; readonly signal?: AbortSignal } = {},
  ): Promise<StudentSessionViewModel> {
    const sessionPath = options.snapshot
      ? `/api/sessions/${encodeURIComponent(sessionId)}/snapshot`
      : `/api/sessions/${encodeURIComponent(sessionId)}`;
    const [sessionResult, healthResult] = await Promise.allSettled([
      this.request<CoreSession>(sessionPath, options.signal ? { signal: options.signal } : undefined),
      this.getHealth(options.signal),
    ]);
    if (sessionResult.status === 'rejected') throw sessionResult.reason;
    const health = healthResult.status === 'fulfilled'
      ? healthResult.value
      : degradedHealth('健康檢查暫時失敗；目前顯示的 session 仍以 Core Backend 為準。');
    return toStudentView(sessionResult.value, health);
  }

  async submitStudentAction(
    sessionId: string,
    action: StudentAction,
    options: StudentRequestOptions = {},
  ): Promise<StudentSessionViewModel> {
    const body: CoreStudentActionRequest = {
      schema_version: SCHEMA_VERSION,
      action: actionMap[action],
      input_mode: 'keyboard',
    };
    const requestOptions: StudentRequestOptions = {
      ...options,
      idempotencyKey: options.idempotencyKey || createIdempotencyKey(`action-${action}`),
    };
    const [actionResult, healthResult] = await Promise.allSettled([
      this.request<CoreStudentActionResult>(
        `/api/sessions/${encodeURIComponent(sessionId)}/actions`,
        { method: 'POST', body: JSON.stringify(body) },
        requestOptions,
      ),
      this.getHealth(options.signal),
    ]);
    if (actionResult.status === 'rejected') throw actionResult.reason;
    const health = healthResult.status === 'fulfilled'
      ? healthResult.value
      : degradedHealth('健康檢查暫時失敗；控制結果已由 Core Backend 接受。');
    return toStudentActionView(actionResult.value, health);
  }

  async submitStudentAnswer(
    sessionId: string,
    submission: CoreTurnSubmission,
    options: StudentRequestOptions = {},
  ): Promise<StudentSessionViewModel> {
    const requestOptions: StudentRequestOptions = {
      ...options,
      idempotencyKey: options.idempotencyKey || createIdempotencyKey('turn'),
    };
    const [turnResult, healthResult] = await Promise.allSettled([
      this.request<CoreTurnResult>(
        `/api/sessions/${encodeURIComponent(sessionId)}/turns`,
        { method: 'POST', body: JSON.stringify(submission) },
        requestOptions,
      ),
      this.getHealth(options.signal),
    ]);
    if (turnResult.status === 'rejected') throw turnResult.reason;
    const health = healthResult.status === 'fulfilled'
      ? healthResult.value
      : degradedHealth('健康檢查暫時失敗；回饋結果已由 Core Backend 接受。');
    return toTurnStudentView(turnResult.value, health);
  }

  subscribeStudentSession(sessionId: string, options: StudentSessionStreamOptions): () => void {
    const controller = new AbortController();
    let closed = false;
    let cursor = Math.max(0, options.afterEventId);
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = 500;

    const waitBeforeReconnect = (milliseconds: number): Promise<void> => new Promise((resolve) => {
      retryTimer = setTimeout(() => {
        retryTimer = null;
        resolve();
      }, milliseconds);
    });

    const connect = async (): Promise<void> => {
      while (!closed) {
        try {
          const response = await fetch(this.url(`/api/sessions/${encodeURIComponent(sessionId)}/events`), {
            headers: {
              Accept: 'text/event-stream',
              'Last-Event-ID': String(cursor),
            },
            signal: controller.signal,
          });
          if (!response.ok) throw await adapterErrorFromResponse(response);
          if (!response.body) throw new Error('SSE response body is unavailable');
          options.onStatus?.('connected');
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          const handleEvent = (event: StudentSessionEvent): void => {
            if (event.event_id <= cursor) return;
            cursor = event.event_id;
            reconnectDelay = 500;
            options.onEvent(event);
          };
          while (!closed) {
            const chunk = await reader.read();
            if (chunk.done) break;
            buffer += decoder.decode(chunk.value, { stream: true });
            buffer = consumeSessionEventFrames(buffer, handleEvent);
          }
          buffer += decoder.decode();
          if (buffer.trim()) consumeSessionEventFrames(`${buffer}\n\n`, handleEvent);
          if (!closed) {
            options.onStatus?.('reconnecting');
            const delay = reconnectDelay;
            reconnectDelay = Math.min(10_000, reconnectDelay * 2);
            await waitBeforeReconnect(delay);
          }
        } catch (error) {
          if (closed || isAbortError(error)) return;
          options.onError(error);
          options.onStatus?.('reconnecting');
          const delay = Math.max(1000, reconnectDelay);
          reconnectDelay = Math.min(10_000, delay * 2);
          await waitBeforeReconnect(delay);
        }
      }
    };

    void connect();
    return () => {
      closed = true;
      controller.abort();
      if (retryTimer !== null) clearTimeout(retryTimer);
      retryTimer = null;
    };
  }

  async getObserverSession(sessionId: string): Promise<ObserverSessionViewModel> {
    const summaryPromise = this.request<CoreObserverSummary>(
      `/api/sessions/${encodeURIComponent(sessionId)}/summary`,
    );
    const healthPromise = this.getHealth();
    const summary = await summaryPromise;
    const [lesson, health] = await Promise.all([
      this.getLesson(summary.lesson_id),
      healthPromise,
    ]);
    const latestTurn = summary.turns.at(-1);
    return {
      sessionId: summary.session_id,
      lessonTitle: lesson.topic,
      transcript: latestTurn?.transcript_raw || '尚未收到學生回答。',
      evaluation: latestTurn?.result ?? 'not_started',
      feedback: latestTurn?.feedback ?? '等待學生開始回答。',
      progressLabel: `${summary.completed_turns} 回合 · ${Math.round(summary.progress * 100)}%`,
      latencyMs: latestTurn
        ? {
            asr: latestTurn.latency_ms.asr,
            backend: latestTurn.latency_ms.backend,
            total: latestTurn.latency_ms.total,
          }
        : { asr: null, backend: null, total: null },
      fallbacks: latestTurn?.fallbacks ?? [],
      health,
    };
  }
}
