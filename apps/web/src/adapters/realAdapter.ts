import { adapterErrorFromResponse, AdapterError } from './errors';
import type { FrontendAdapter } from './adapter';
import type {
  CaptureViewModel,
  ObserverSessionViewModel,
  SetupViewModel,
  StudentAction,
  StudentSessionViewModel,
} from '../types/viewModels';

/**
 * Transport boundary for the real Core Backend.
 *
 * The canonical OpenAPI contract is not present in this repository yet. This
 * adapter deliberately refuses to cast unknown responses into parallel
 * Lesson/Session types. Once Agent A publishes the contract, run
 * `npm run contracts:generate` and replace the guarded mappings below with
 * generated types and the contract client.
 */
export class RealAdapter implements FrontendAdapter {
  constructor(private readonly baseUrl = import.meta.env.VITE_CORE_API_BASE_URL || '/api') {}

  private async request(path: string, init?: RequestInit): Promise<unknown> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init?.headers || {}) },
    });
    if (!response.ok) throw await adapterErrorFromResponse(response);
    return response.json();
  }

  private async contractNotReady<T>(route: string): Promise<T> {
    try {
      await this.request(route);
    } catch (error) {
      if (error instanceof AdapterError) throw error;
      throw error;
    }
    throw new AdapterError({
      code: 'CONTRACT_NOT_GENERATED',
      message: `Real adapter 收到 ${route} 回應，但 Agent A 的 canonical contract 尚未生成。`,
      retryable: false,
      fallback: 'mock',
      request_id: null,
    });
  }

  getSetup(): Promise<SetupViewModel> {
    return this.contractNotReady('/health');
  }

  getCapture(): Promise<CaptureViewModel> {
    return this.contractNotReady('/lessons/demo-lesson');
  }

  confirmLesson(): Promise<{ readonly sessionId: string }> {
    return this.contractNotReady('/sessions');
  }

  getStudentSession(sessionId: string): Promise<StudentSessionViewModel> {
    return this.contractNotReady(`/sessions/${encodeURIComponent(sessionId)}`);
  }

  submitStudentAction(sessionId: string, action: StudentAction): Promise<StudentSessionViewModel> {
    return this.contractNotReady(`/sessions/${encodeURIComponent(sessionId)}/turns?action=${action}`);
  }

  getObserverSession(sessionId: string): Promise<ObserverSessionViewModel> {
    return this.contractNotReady(`/sessions/${encodeURIComponent(sessionId)}/summary`);
  }
}
