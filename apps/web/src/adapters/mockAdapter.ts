import type {
  FrontendAdapter,
  StudentRequestOptions,
  StudentSessionEvent,
  StudentSessionStreamOptions,
} from './adapter';
import { AdapterError } from './errors';
import type { components } from '../generated/api';
import type {
  CaptureViewModel,
  HealthStatus,
  HealthSummaryView,
  LessonReviewPatch,
  LessonImageUpload,
  ObserverAction,
  ObserverEvidenceView,
  ObserverFamiliarityView,
  ObserverHintView,
  ObserverLessonViewModel,
  ObserverSessionViewModel,
  ObserverTurnView,
  ServiceHealthView,
  SessionState,
  SetupViewModel,
  StudentAction,
  StudentSessionViewModel,
  TeachingPhase,
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
    { service: 'Core Backend', status, device: 'Ryzen AI 9 laptop', modelRevision: 'mock-core-v0.1', queueDepth: 0, lastError },
    { service: 'Local RAG', status: status === 'ready' ? 'ready' : 'degraded', device: 'laptop CPU', modelRevision: 'mock-rag-v0.1', queueDepth: 0, lastError },
    { service: 'MI300 VLM', status: status === 'offline' ? 'offline' : status === 'ready' ? 'ready' : 'degraded', device: 'MI300 96GB', modelRevision: 'mock-vlm-v0.1', queueDepth: 0, lastError },
    { service: 'ASR', status: status === 'offline' ? 'offline' : status, device: 'laptop CPU', modelRevision: 'mock-breeze-cpu-v0.1', queueDepth: 0, lastError },
    { service: 'TTS', status: status === 'offline' ? 'offline' : status, device: 'laptop CPU', modelRevision: 'mock-mms-v0.1', queueDepth: 0, lastError },
  ];
  return { status, checkedAt: new Date().toISOString(), services };
}

function createDemoLesson(): ObserverLessonViewModel {
  return {
    lessonId: DEMO_LESSON_ID,
    topic: '水果攤：聽聲音認識水果',
    sourceText: '阿媽欲去市場買菜。',
    vocabulary: [
      { hanji: '市場', tailo: 'tshī-tiûnn', meaning: '市場', audioKey: 'nan-market-001' },
      { hanji: '欲', tailo: 'beh', meaning: '要', audioKey: 'nan-want-001' },
      { hanji: '水果', tailo: 'tsuí-kó', meaning: '水果', audioKey: 'nan-fruit-001' },
    ],
    scene: '市場裡有阿媽、菜販與囡仔。',
    originalActivity: '看圖片，說說看誰正在買菜。',
    learningObjective: '辨識人物與買菜動作，練習市場與水果詞彙。',
    accessibleActivity: '聽三個角色與動作線索，判斷哪一位角色正在買菜，不直接描述圖中答案。',
    evidence: [
      {
        sourceId: 'mock-dictionary-market',
        title: '教育部臺灣台語常用詞辭典（Mock）',
        excerpt: '市場：tshī-tiûnn；水果：tsuí-kó。',
        locator: 'demo/market',
      },
    ],
    confidence: 0.91,
    reviewStatus: 'pending',
    answerEvidence: ['教師檢視依據：活動以角色與動作線索引導回答，未將視覺答案放入學生提示。'],
    vlmModelRevision: 'mock-vlm-v0.1',
    ragIndexRevision: 'mock-rag-2026-09',
  };
}

function createEvent(
  sessionId: string,
  eventId: number,
  revision: number,
  event: StudentSessionEvent['event'],
  payload: Record<string, unknown>,
): StudentSessionEvent {
  return {
    schema_version: '0.1.0',
    event_id: eventId,
    session_id: sessionId,
    event,
    request_id: `mock-request-${eventId}`,
    revision,
    payload,
  };
}

export class MockAdapter implements FrontendAdapter {
  private readonly health = createHealth(requestedHealthStatus());
  private lesson: ObserverLessonViewModel = createDemoLesson();
  private turns: ObserverTurnView[] = [];
  private conceptsToReview: string[] = ['水果'];
  private hintHistory: ObserverHintView[] = [];
  private familiarity: ObserverFamiliarityView[] = [
    { concept: '市場', status: 'developing' },
    { concept: '水果', status: 'new' },
  ];
  private answered = false;
  private answerCount = 0;
  private lastFeedback = '尚未開始回答。你可以先播放提示，再按下開始回答。';
  private transcript = '';
  private state: SessionState = 'SPEAKING';
  private phase: TeachingPhase = 'introduction';
  private progress = 0.0;
  private revision = 0;
  private lastEventId = 0;
  private readonly listeners = new Set<(event: StudentSessionEvent) => void>();

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
      providerMode: 'mock',
      canConfirm: true,
    };
  }

  async getCaptureFallback(): Promise<CaptureViewModel> {
    return this.getCapture();
  }

  async analyzeLesson(image: LessonImageUpload, signal?: AbortSignal): Promise<CaptureViewModel> {
    if (signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError');
    if (image.quality.status === 'rejected') {
      throw new AdapterError({
        code: 'IMAGE_QUALITY_LOW',
        message: '照片品質未達到教材分析的最低要求。',
        retryable: false,
        fallback: 'manual_review',
        request_id: null,
      });
    }
    return {
      ...(await this.getCapture()),
      description: image.quality.status === 'warning'
        ? 'Mock 已收到照片；這張照片有可覆寫的品質提醒。'
        : 'Mock 已收到照片；目前使用離線合成教材回應。',
    };
  }

  async confirmLesson(lessonId: string): Promise<{ readonly sessionId: string }> {
    if (lessonId !== DEMO_LESSON_ID) throw new Error('Mock lesson 不存在。');
    return { sessionId: DEMO_SESSION_ID };
  }

  async getStudentSession(
    sessionId: string,
    _options?: { readonly snapshot?: boolean; readonly signal?: AbortSignal },
  ): Promise<StudentSessionViewModel> {
    return this.studentView(sessionId);
  }

  async submitStudentAction(
    sessionId: string,
    action: StudentAction,
    _options?: StudentRequestOptions,
  ): Promise<StudentSessionViewModel> {
    if (action === 'answer') {
      this.state = 'LISTENING';
      this.lastFeedback = '可以開始回答；播放已停止。';
    } else if (action === 'listen') {
      this.state = 'SPEAKING';
      this.lastFeedback = '提示播放完成；播放結束後才開啟麥克風。';
    } else if (action === 'hint') {
      this.phase = 'hint';
      this.state = 'SPEAKING';
      this.lastFeedback = '提示：想想水果的顏色、形狀或味道。';
      this.hintHistory = [
        ...this.hintHistory,
        {
          turnId: this.turns.at(-1)?.turnId || `turn_mock_${Math.max(1, this.answerCount)}`,
          prompt: '想想水果的顏色、形狀或味道。',
          feedback: '提示只提供思考方向，不直接揭露教材答案。',
        },
      ];
    } else if (action === 'pause') {
      this.state = 'IDLE';
      this.lastFeedback = '流程已暫停，可以稍後繼續。';
    } else if (action === 'resume') {
      this.state = this.phase === 'complete' ? 'COMPLETE' : 'SPEAKING';
      this.lastFeedback = '已繼續目前活動。';
    } else if (action === 'next') {
      this.state = this.phase === 'complete' ? 'COMPLETE' : 'SPEAKING';
      this.progress = Math.min(1, this.progress + 0.1);
      this.lastFeedback = this.phase === 'complete' ? '本課完成，做得很好。' : '已進入下一個活動。';
    }
    this.revision += 1;
    const view = this.studentView(sessionId);
    this.emit(sessionId, 'session.action', {
      schema_version: '0.1.0',
      session_id: sessionId,
      state: this.state,
      progress: this.progress,
      current_prompt: view.prompt,
      action: action === 'listen' ? 'replay_prompt' : action === 'answer' ? 'start_answer' : action,
      feedback: this.lastFeedback,
      next_prompt: view.prompt,
      can_answer: view.canAnswer,
      phase: this.phase,
      revision: this.revision,
      last_event_id: this.lastEventId + 1,
    });
    return this.studentView(sessionId);
  }

  async submitStudentAnswer(
    sessionId: string,
    submission: components['schemas']['TurnSubmission'],
    _options?: StudentRequestOptions,
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
    this.answerCount += 1;
    this.answered = true;
    this.transcript = submission.transcript;
    this.state = 'SPEAKING';
    this.phase = this.answerCount >= 3 ? 'complete' : 'comprehension';
    this.progress = this.answerCount >= 3 ? 1 : Math.min(0.9, 0.33 + this.answerCount * 0.2);
    this.lastFeedback = this.answerCount >= 3
      ? '本課完成，做得很好。'
      : '已收到你的回答，接下來可以繼續下一個活動。';
    this.revision += 1;
    const view = this.studentView(sessionId);
    this.turns = [
      ...this.turns,
      {
        turnId: `turn_mock_${this.answerCount}`,
        transcriptRaw: this.transcript,
        transcriptNormalized: this.transcript,
        result: 'partial',
        matchedConcepts: [],
        feedback: this.lastFeedback,
        nextPrompt: view.prompt,
        progress: this.progress,
        latencyMs: { asr: 20, backend: 5, vlm: null, tts: null, total: 25 },
        asrDevice: submission.asr_device || 'cpu',
        fallbacks: ['fixture_mode'],
        phase: this.phase,
        revision: this.revision,
        lastEventId: this.lastEventId + 1,
      },
    ];
    this.emit(sessionId, 'turn.completed', {
      schema_version: '0.1.0',
      turn_id: `mock-turn-${this.answerCount}`,
      session_id: sessionId,
      transcript_raw: this.transcript,
      transcript_normalized: this.transcript,
      result: 'partial',
      matched_concepts: [],
      feedback: this.lastFeedback,
      next_prompt: view.prompt,
      progress: this.progress,
      latency_ms: { asr: 20, backend: 5, vlm: null, tts: null, total: 25 },
      asr_device: submission.asr_device || 'cpu',
      fallbacks: ['fixture_mode'],
      phase: this.phase,
      revision: this.revision,
      last_event_id: this.lastEventId + 1,
    });
    return this.studentView(sessionId);
  }

  subscribeStudentSession(_sessionId: string, options: StudentSessionStreamOptions): () => void {
    this.listeners.add(options.onEvent);
    options.onStatus?.('connected');
    return () => this.listeners.delete(options.onEvent);
  }

  async getObserverSession(sessionId: string): Promise<ObserverSessionViewModel> {
    const latestTurn = this.turns.at(-1);
    return {
      sessionId,
      lessonId: this.lesson.lessonId,
      state: this.state,
      phase: this.phase,
      progress: this.progress,
      completedTurns: this.turns.length,
      lesson: this.lesson,
      turns: this.turns,
      conceptsToReview: this.conceptsToReview,
      hintHistory: this.hintHistory,
      familiarity: this.familiarity,
      evidence: this.lesson.evidence,
      answerEvidence: this.lesson.answerEvidence,
      vlmModelRevision: this.lesson.vlmModelRevision,
      ragIndexRevision: this.lesson.ragIndexRevision,
      reviewStatus: this.lesson.reviewStatus,
      revision: this.revision,
      lastEventId: this.lastEventId,
      lessonTitle: this.lesson.topic,
      transcript: this.answered ? this.transcript : '尚未收到學生回答。',
      evaluation: this.answered ? 'partial' : 'not_started',
      feedback: this.answered ? '可在下一回合用聲音提示引導學生補充。' : '等待學生開始回答。',
      progressLabel: `${this.turns.length} 回合 · ${Math.round(this.progress * 100)}%`,
      latencyMs: latestTurn
        ? { asr: latestTurn.latencyMs.asr, backend: latestTurn.latencyMs.backend, total: latestTurn.latencyMs.total }
        : { asr: null, backend: null, total: null },
      fallbacks: latestTurn?.fallbacks ?? (this.health.status === 'ready' ? [] : ['mock-health-override']),
      health: this.health,
    };
  }

  async reviewLesson(lessonId: string, patch: LessonReviewPatch): Promise<ObserverLessonViewModel> {
    if (lessonId !== this.lesson.lessonId) throw new Error('Mock lesson 不存在。');
    this.lesson = {
      ...this.lesson,
      ...(patch.topic === undefined ? {} : { topic: patch.topic }),
      ...(patch.sourceText === undefined ? {} : { sourceText: patch.sourceText }),
      ...(patch.accessibleActivity === undefined ? {} : { accessibleActivity: patch.accessibleActivity }),
      ...(patch.reviewStatus === undefined ? {} : { reviewStatus: patch.reviewStatus }),
    };
    return this.lesson;
  }

  async submitObserverAction(sessionId: string, action: ObserverAction): Promise<ObserverSessionViewModel> {
    if (action === 'skip') {
      this.state = 'SPEAKING';
      this.phase = this.phase === 'complete' ? 'complete' : 'review';
      this.progress = Math.min(1, this.progress + 0.1);
      this.lastFeedback = '教師／家長已跳過目前活動。';
    } else if (action === 'redo') {
      this.state = 'LISTENING';
      this.phase = 'comprehension';
      this.lastFeedback = '已回到目前活動，學生可以重新作答。';
    } else if (action === 'end') {
      this.state = 'COMPLETE';
      this.phase = 'complete';
      this.progress = 1;
      this.lastFeedback = '教學回合已由教師／家長結束。';
    } else if (action === 'reset') {
      this.answered = false;
      this.answerCount = 0;
      this.lastFeedback = '示範 session 已重設，可以重新開始。';
      this.transcript = '';
      this.state = 'SPEAKING';
      this.phase = 'introduction';
      this.progress = 0;
      this.revision = 0;
      this.lastEventId = 0;
      this.turns = [];
      this.hintHistory = [];
      this.conceptsToReview = ['水果'];
      this.lesson = { ...this.lesson, reviewStatus: 'pending' };
    }
    if (action !== 'reset') this.revision += 1;
    return this.getObserverSession(sessionId);
  }

  private studentView(sessionId: string): StudentSessionViewModel {
    const progressValue = Math.round(this.progress * 100);
    return {
      sessionId,
      lessonTitle: '水果攤：聽聲音認識水果',
      state: this.state,
      phase: this.phase,
      prompt: '請聽提示，說出你想介紹的水果。這裡沒有顯示標準答案。',
      feedback: this.lastFeedback,
      progressLabel: '目前進度',
      progressValue,
      revision: this.revision,
      lastEventId: this.lastEventId,
      health: this.health,
      canAnswer: this.health.status !== 'offline' && this.state === 'LISTENING' && this.phase !== 'complete',
      transcript: this.transcript,
      fallbacks: this.health.status === 'ready' ? [] : ['mock-health-override'],
    };
  }

  private emit(
    sessionId: string,
    event: StudentSessionEvent['event'],
    payload: Record<string, unknown>,
  ): void {
    this.lastEventId += 1;
    const nextEvent = createEvent(sessionId, this.lastEventId, this.revision, event, payload);
    for (const listener of this.listeners) listener(nextEvent);
  }
}
