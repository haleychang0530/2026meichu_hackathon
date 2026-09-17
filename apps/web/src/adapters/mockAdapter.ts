import type { FrontendAdapter } from './adapter';
import { AdapterError } from './errors';
import type { components } from '../generated/api';
import type {
  CaptureViewModel,
  HealthStatus,
  HealthSummaryView,
  ObserverSessionViewModel,
  ServiceHealthView,
  SetupViewModel,
  StudentAction,
  StudentSessionViewModel,
} from '../types/viewModels';

const DEMO_SESSION_ID = 'demo-session';
const DEMO_LESSON_ID = 'demo-lesson';

function requestedHealthStatus(): HealthStatus {
  if (typeof window === 'undefined') return 'ready';
  const value = new URLSearchParams(window.location.search).get('health');
  return value === 'degraded' || value === 'offline' || value === 'recoverable_error'
    ? value
    : 'ready';
}

function createHealth(status: HealthStatus): HealthSummaryView {
  const lastError = status === 'ready' ? undefined : 'Mock health override：後端或語音服務尚未完全可用。';
  const services: readonly ServiceHealthView[] = [
    { service: 'Core Backend', status, device: 'laptop', modelRevision: 'mock-core-v0.1', lastError },
    { service: 'Speech Gateway', status: status === 'offline' ? 'offline' : status, device: 'laptop', modelRevision: 'mock-speech-v0.1', lastError },
    { service: 'Local RAG', status: status === 'ready' ? 'ready' : 'degraded', device: 'laptop', modelRevision: 'mock-rag-v0.1', lastError },
  ];
  return { status, checkedAt: new Date().toISOString(), services };
}

export class MockAdapter implements FrontendAdapter {
  private readonly health = createHealth(requestedHealthStatus());
  private answered = false;
  private lastFeedback = '尚未開始回答。你可以先播放提示，再按下開始回答。';

  async getSetup(): Promise<SetupViewModel> {
    return {
      title: '聽見母語｜Mock 教學流程',
      description: '用合成教材與 Mock adapter 走完學生／教師家長雙模式流程。',
      health: this.health,
      nextRoute: '/capture',
    };
  }

  async getCapture(): Promise<CaptureViewModel> {
    return {
      lessonId: DEMO_LESSON_ID,
      title: '水果攤：聽聲音認識水果',
      description: '這是一份不含個資的合成教材，用來驗證教材確認與 session 建立。',
      reviewStatus: 'pending',
      images: [
        { src: '/lesson-images/lesson-market.svg', alt: '沒有角色的水果攤合成教材圖', label: '水果攤' },
        { src: '/lesson-images/lesson-shapes.svg', alt: '圓形、三角形與方形的合成教材圖', label: '形狀與顏色' },
        { src: '/lesson-images/lesson-weather.svg', alt: '太陽、雲朵與雨滴的合成教材圖', label: '天氣觀察' },
      ],
      health: this.health,
    };
  }

  async confirmLesson(lessonId: string): Promise<{ readonly sessionId: string }> {
    if (lessonId !== DEMO_LESSON_ID) throw new Error('Mock lesson 不存在。');
    return { sessionId: DEMO_SESSION_ID };
  }

  async getStudentSession(sessionId: string): Promise<StudentSessionViewModel> {
    return {
      sessionId,
      lessonTitle: '水果攤：聽聲音認識水果',
      prompt: '請聽提示，說出你想介紹的水果。這裡沒有顯示標準答案。',
      feedback: this.lastFeedback,
      progressLabel: this.answered ? '第 2 / 3 步' : '第 1 / 3 步',
      progressValue: this.answered ? 66 : 33,
      health: this.health,
      canAnswer: this.health.status !== 'offline',
    };
  }

  async submitStudentAction(sessionId: string, action: StudentAction): Promise<StudentSessionViewModel> {
    if (action === 'answer') {
      this.answered = true;
      this.lastFeedback = '已收到你的 Mock 回答，接下來可以到教師／家長模式查看過程。';
    } else if (action === 'listen') {
      this.lastFeedback = '提示播放完成；播放結束後才開啟麥克風。';
    } else if (action === 'hint') {
      this.lastFeedback = '提示：想想水果的顏色、形狀或味道。';
    } else {
      this.lastFeedback = '流程已暫停，可以稍後繼續。';
    }
    return this.getStudentSession(sessionId);
  }

  async submitStudentAnswer(
    sessionId: string,
    submission: components['schemas']['TurnSubmission'],
  ): Promise<StudentSessionViewModel> {
    if (!submission.transcript.trim()) {
      throw new AdapterError({
        code: 'VALIDATION_ERROR',
        message: '回答內容不能是空白。',
        retryable: false,
        fallback: 'keyboard_input',
        request_id: null,
      });
    }
    this.answered = true;
    this.lastFeedback = '已收到你的 Mock 回答，接下來可以到教師／家長模式查看過程。';
    return this.getStudentSession(sessionId);
  }

  async getObserverSession(sessionId: string): Promise<ObserverSessionViewModel> {
    return {
      sessionId,
      lessonTitle: '水果攤：聽聲音認識水果',
      transcript: this.answered ? '這是一段 Mock 學生回答。' : '尚未收到學生回答。',
      evaluation: this.answered ? 'partial' : 'not_started',
      feedback: this.answered ? '可在下一回合用聲音提示引導學生補充。' : '等待學生開始回答。',
      progressLabel: this.answered ? '第 2 / 3 步' : '第 1 / 3 步',
      latencyMs: this.answered ? { asr: 320, backend: 80, total: 610 } : { asr: null, backend: null, total: null },
      fallbacks: this.health.status === 'ready' ? [] : ['mock-health-override'],
      health: this.health,
    };
  }
}
