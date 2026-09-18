export type HealthStatus = 'ready' | 'degraded' | 'offline' | 'recoverable_error';

export interface ServiceHealthView {
  readonly service: string;
  readonly status: HealthStatus;
  readonly device: string;
  readonly modelRevision?: string;
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

export type StudentAction = 'listen' | 'answer' | 'hint' | 'pause';

export interface StudentSessionViewModel {
  readonly sessionId: string;
  readonly lessonTitle: string;
  readonly prompt: string;
  readonly feedback: string;
  readonly progressLabel: string;
  readonly progressValue: number;
  readonly health: HealthSummaryView;
  readonly canAnswer: boolean;
}

export interface ObserverSessionViewModel {
  readonly sessionId: string;
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
