export type HealthStatus = 'ready' | 'degraded' | 'offline' | 'recoverable_error';

export interface ServiceHealthView {
  readonly service: string;
  readonly status: HealthStatus;
  readonly device: string;
  readonly modelRevision?: string;
  readonly queueDepth?: number;
  readonly lastError?: string;
}

export interface HealthSummaryView {
  readonly status: HealthStatus;
  readonly checkedAt: string;
  readonly services: readonly ServiceHealthView[];
}

export type ImageQualityStatus = 'good' | 'warning' | 'rejected';

export type ImageQualityIssueCode =
  | 'unsupported_type'
  | 'file_too_large'
  | 'resolution_too_low'
  | 'too_blurry'
  | 'too_dark'
  | 'too_bright';

export interface ImageQualityMetrics {
  readonly meanLuminance: number;
  readonly darkPixelRatio: number;
  readonly brightPixelRatio: number;
  readonly sharpness: number;
}

export interface ImageQualityIssue {
  readonly code: ImageQualityIssueCode;
  readonly severity: 'blocking' | 'warning';
  readonly message: string;
  readonly suggestion: string;
}

export interface ImageQualityReport {
  readonly status: ImageQualityStatus;
  readonly width: number;
  readonly height: number;
  readonly bytes: number;
  readonly mimeType: string;
  readonly issues: readonly ImageQualityIssue[];
  readonly metrics?: ImageQualityMetrics;
}

/**
 * A browser-prepared image. The Core Backend receives only `blob`; previewUrl
 * is a short-lived object URL owned by the Camera component.
 */
export interface LessonImageUpload {
  readonly blob: Blob;
  readonly fileName: string;
  readonly mimeType: string;
  readonly width: number;
  readonly height: number;
  readonly sourceBytes: number;
  readonly quality: ImageQualityReport;
}

export interface CaptureAsset extends LessonImageUpload {
  readonly previewUrl: string;
}

export interface SetupViewModel {
  readonly title: string;
  readonly description: string;
  readonly health: HealthSummaryView;
  readonly nextRoute: '/capture';
}

export interface CaptureImageView {
  readonly src: string;
  readonly alt: string;
  readonly label: string;
}

export type CaptureProviderMode = 'mock' | 'real' | 'fixture' | 'fixture-fallback';

export interface CaptureViewModel {
  readonly lessonId: string;
  readonly title: string;
  readonly description: string;
  readonly reviewStatus: 'pending' | 'approved' | 'rejected';
  readonly images: readonly CaptureImageView[];
  readonly health: HealthSummaryView;
  readonly providerMode: CaptureProviderMode;
  /** Stage 08 owns the runtime session-confirmation endpoint. */
  readonly canConfirm: boolean;
}

export type SessionState =
  | 'IDLE'
  | 'SPEAKING'
  | 'LISTENING'
  | 'TRANSCRIBING'
  | 'EVALUATING'
  | 'RECOVERABLE_ERROR'
  | 'COMPLETE';

export type TeachingPhase =
  | 'introduction'
  | 'demonstration'
  | 'read_aloud'
  | 'comprehension'
  | 'hint'
  | 'review'
  | 'complete';

export type StudentAction = 'listen' | 'answer' | 'hint' | 'pause' | 'resume' | 'next';

export interface StudentSessionViewModel {
  readonly sessionId: string;
  readonly lessonTitle: string;
  readonly state: SessionState;
  readonly phase: TeachingPhase;
  readonly prompt: string;
  readonly feedback: string;
  readonly progressLabel: string;
  readonly progressValue: number;
  readonly revision: number;
  readonly lastEventId: number;
  readonly health: HealthSummaryView;
  readonly canAnswer: boolean;
  /** Only the student's own transcript is allowed in this view model. */
  readonly transcript: string;
  readonly fallbacks: readonly string[];
}

export type LessonReviewStatus = 'pending' | 'approved' | 'rejected';

export interface ObserverVocabularyView {
  readonly hanji: string;
  readonly tailo: string;
  readonly meaning: string;
  readonly audioKey: string | null;
}

export interface ObserverEvidenceView {
  readonly sourceId: string;
  readonly title: string;
  readonly excerpt: string;
  readonly locator: string;
}

export interface ObserverLessonViewModel {
  readonly lessonId: string;
  readonly topic: string;
  readonly sourceText: string;
  readonly vocabulary: readonly ObserverVocabularyView[];
  readonly scene: string;
  readonly originalActivity: string;
  readonly learningObjective: string;
  readonly accessibleActivity: string;
  readonly evidence: readonly ObserverEvidenceView[];
  readonly confidence: number;
  readonly reviewStatus: LessonReviewStatus;
  readonly answerEvidence: readonly string[];
  readonly vlmModelRevision: string | null;
  readonly ragIndexRevision: string | null;
}

export interface ObserverTurnView {
  readonly turnId: string;
  readonly transcriptRaw: string;
  readonly transcriptNormalized: string;
  readonly result: 'correct' | 'partial' | 'retry';
  readonly matchedConcepts: readonly string[];
  readonly feedback: string;
  readonly nextPrompt: string;
  readonly progress: number;
  readonly latencyMs: Readonly<{
    readonly asr: number | null;
    readonly backend: number;
    readonly vlm: number | null;
    readonly tts: number | null;
    readonly total: number;
  }>;
  readonly asrDevice: 'npu' | 'cpu';
  readonly fallbacks: readonly string[];
  readonly phase: TeachingPhase;
  readonly revision: number;
  readonly lastEventId: number;
}

export interface ObserverHintView {
  readonly turnId: string;
  readonly prompt: string;
  readonly feedback: string;
}

export interface ObserverFamiliarityView {
  readonly concept: string;
  readonly status: 'new' | 'developing' | 'familiar';
}

export interface LessonReviewPatch {
  readonly topic?: string;
  readonly sourceText?: string;
  readonly accessibleActivity?: string;
  readonly reviewStatus?: LessonReviewStatus;
}

export type ObserverAction = 'skip' | 'redo' | 'end' | 'reset';

export interface ObserverSessionViewModel {
  readonly sessionId: string;
  readonly lessonId: string;
  readonly state: SessionState;
  readonly phase: TeachingPhase;
  readonly progress: number;
  readonly completedTurns: number;
  readonly lesson: ObserverLessonViewModel;
  readonly turns: readonly ObserverTurnView[];
  readonly conceptsToReview: readonly string[];
  readonly hintHistory: readonly ObserverHintView[];
  readonly familiarity: readonly ObserverFamiliarityView[];
  readonly evidence: readonly ObserverEvidenceView[];
  readonly answerEvidence: readonly string[];
  readonly vlmModelRevision: string | null;
  readonly ragIndexRevision: string | null;
  readonly reviewStatus: LessonReviewStatus | null;
  readonly revision: number;
  readonly lastEventId: number;

  /** Compatibility projection retained for the original Stage 02 observer UI. */
  readonly lessonTitle: string;
  readonly transcript: string;
  readonly evaluation: 'correct' | 'partial' | 'retry' | 'not_started';
  readonly feedback: string;
  readonly progressLabel: string;
  readonly latencyMs: Readonly<{
    readonly asr: number | null;
    readonly backend: number | null;
    readonly total: number | null;
  }>;
  readonly fallbacks: readonly string[];
  readonly health: HealthSummaryView;
}
