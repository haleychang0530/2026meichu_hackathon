import type {
  CaptureViewModel,
  ObserverSessionViewModel,
  SetupViewModel,
  StudentAction,
  StudentSessionViewModel,
} from '../types/viewModels';
import type { components } from '../generated/api';

export interface FrontendAdapter {
  getSetup(): Promise<SetupViewModel>;
  getCapture(): Promise<CaptureViewModel>;
  confirmLesson(lessonId: string): Promise<{ readonly sessionId: string }>;
  getStudentSession(sessionId: string): Promise<StudentSessionViewModel>;
  submitStudentAction(
    sessionId: string,
    action: StudentAction,
  ): Promise<StudentSessionViewModel>;
  submitStudentAnswer(
    sessionId: string,
    submission: components['schemas']['TurnSubmission'],
  ): Promise<StudentSessionViewModel>;
  getObserverSession(sessionId: string): Promise<ObserverSessionViewModel>;
}
