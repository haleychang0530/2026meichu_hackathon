import type {
  CaptureViewModel,
  ObserverSessionViewModel,
  SetupViewModel,
  StudentAction,
  StudentSessionViewModel,
} from '../types/viewModels';

export interface FrontendAdapter {
  getSetup(): Promise<SetupViewModel>;
  getCapture(): Promise<CaptureViewModel>;
  confirmLesson(lessonId: string): Promise<{ readonly sessionId: string }>;
  getStudentSession(sessionId: string): Promise<StudentSessionViewModel>;
  submitStudentAction(
    sessionId: string,
    action: StudentAction,
  ): Promise<StudentSessionViewModel>;
  getObserverSession(sessionId: string): Promise<ObserverSessionViewModel>;
}
