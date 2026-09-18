import { adapterErrorFromResponse } from './errors';
import type { FrontendAdapter } from './adapter';
import type { components, operations } from '../generated/api';
import type {
  CaptureProviderMode,
  CaptureViewModel,
  HealthSummaryView,
  LessonImageUpload,
  ObserverSessionViewModel,
  ServiceHealthView,
  SetupViewModel,
  StudentAction,
  StudentSessionViewModel,
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
};

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
    // Session creation is an Agent A Stage 08 runtime capability, not part of
    // the Stage 04 Core API currently available on the laptop.
    canConfirm: false,
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
): StudentSessionViewModel {
  const progress = toProgress(session.progress);
  return {
    sessionId: session.session_id,
    lessonTitle: '目前教材',
    prompt: session.current_prompt ?? '目前沒有可播放的提示。',
    feedback,
    progressLabel: progress.label,
    progressValue: progress.value,
    health,
    canAnswer: health.status !== 'offline' && session.state !== 'COMPLETE',
  };
}

function toStudentActionView(
  actionResult: CoreStudentActionResult,
  health: HealthSummaryView,
): StudentSessionViewModel {
  const progress = toProgress(actionResult.progress);
  return {
    sessionId: actionResult.session_id,
    lessonTitle: '目前教材',
    prompt: actionResult.current_prompt ?? actionResult.next_prompt ?? '目前沒有可播放的提示。',
    feedback: actionResult.feedback ?? '操作已完成。',
    progressLabel: progress.label,
    progressValue: progress.value,
    health,
    canAnswer: actionResult.can_answer && health.status !== 'offline',
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
    prompt: turn.next_prompt,
    feedback: turn.feedback,
    progressLabel: progress.label,
    progressValue: progress.value,
    health,
    canAnswer: health.status !== 'offline',
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

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const result = await this.requestWithResponse<T>(path, init);
    return result.payload;
  }

  private async requestWithResponse<T>(
    path: string,
    init?: RequestInit,
  ): Promise<{ readonly payload: T; readonly response: Response }> {
    const headers = new Headers(init?.headers);
    headers.set('Accept', 'application/json');
    const isMultipart = typeof FormData !== 'undefined' && init?.body instanceof FormData;
    if (init?.body && !headers.has('Content-Type') && !isMultipart) {
      headers.set('Content-Type', 'application/json');
    }
    const response = await fetch(this.url(path), { ...init, headers });
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
    // Stage 04 runtime exposes health and analyze only. Do not probe the
    // future Stage 08 lesson/session routes just to render the capture page.
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
    });
    return { sessionId: session.session_id };
  }

  async getStudentSession(sessionId: string): Promise<StudentSessionViewModel> {
    const [session, health] = await Promise.all([
      this.request<CoreSession>(`/api/sessions/${encodeURIComponent(sessionId)}`),
      this.getHealth(),
    ]);
    return toStudentView(session, health);
  }

  async submitStudentAction(sessionId: string, action: StudentAction): Promise<StudentSessionViewModel> {
    const body: CoreStudentActionRequest = {
      schema_version: SCHEMA_VERSION,
      action: actionMap[action],
      input_mode: 'keyboard',
    };
    const [actionResult, health] = await Promise.all([
      this.request<CoreStudentActionResult>(`/api/sessions/${encodeURIComponent(sessionId)}/actions`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
      this.getHealth(),
    ]);
    return toStudentActionView(actionResult, health);
  }

  async submitStudentAnswer(
    sessionId: string,
    submission: CoreTurnSubmission,
  ): Promise<StudentSessionViewModel> {
    const [turn, health] = await Promise.all([
      this.request<CoreTurnResult>(`/api/sessions/${encodeURIComponent(sessionId)}/turns`, {
        method: 'POST',
        body: JSON.stringify(submission),
      }),
      this.getHealth(),
    ]);
    return toTurnStudentView(turn, health);
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
