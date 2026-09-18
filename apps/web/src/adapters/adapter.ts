import type {
  CaptureViewModel,
  LessonImageUpload,
  LessonReviewPatch,
  ObserverSessionViewModel,
  ObserverAction,
  SetupViewModel,
  StudentAction,
  StudentSessionViewModel,
} from '../types/viewModels';
import type { components } from '../generated/api';

export type StudentSessionEvent = components['schemas']['SessionEvent'];

export interface StudentRequestOptions {
  readonly expectedRevision?: number;
  readonly idempotencyKey?: string;
  readonly signal?: AbortSignal;
}

export interface StudentSessionStreamOptions {
  readonly afterEventId: number;
  readonly onEvent: (event: StudentSessionEvent) => void;
  readonly onError: (error: unknown) => void;
  readonly onStatus?: (status: 'connected' | 'reconnecting') => void;
}

export interface FrontendAdapter {
  getSetup(): Promise<SetupViewModel>;
  getCapture(): Promise<CaptureViewModel>;
  getCaptureFallback(): Promise<CaptureViewModel>;
  analyzeLesson(image: LessonImageUpload, signal?: AbortSignal): Promise<CaptureViewModel>;
  confirmLesson(lessonId: string): Promise<{ readonly sessionId: string }>;
  getStudentSession(
    sessionId: string,
    options?: { readonly snapshot?: boolean; readonly signal?: AbortSignal },
  ): Promise<StudentSessionViewModel>;
  submitStudentAction(
    sessionId: string,
    action: StudentAction,
    options?: StudentRequestOptions,
  ): Promise<StudentSessionViewModel>;
  submitStudentAnswer(
    sessionId: string,
    submission: components['schemas']['TurnSubmission'],
    options?: StudentRequestOptions,
  ): Promise<StudentSessionViewModel>;
  subscribeStudentSession(sessionId: string, options: StudentSessionStreamOptions): () => void;
  getObserverSession(sessionId: string): Promise<ObserverSessionViewModel>;
  reviewLesson(lessonId: string, patch: LessonReviewPatch): Promise<ObserverSessionViewModel['lesson']>;
  submitObserverAction(sessionId: string, action: ObserverAction): Promise<ObserverSessionViewModel>;
}
