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

export interface CaptureViewModel {
  readonly lessonId: string;
  readonly title: string;
  readonly description: string;
  readonly reviewStatus: 'pending' | 'approved' | 'rejected';
  readonly images: readonly CaptureImageView[];
  readonly health: HealthSummaryView;
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
