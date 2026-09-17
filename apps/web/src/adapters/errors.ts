export interface ErrorEnvelope {
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
  readonly fallback: string | null;
  readonly request_id: string | null;
}

export class AdapterError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly fallback: string | null;
  readonly requestId: string | null;

  constructor(envelope: ErrorEnvelope, options?: { readonly cause?: unknown }) {
    super(envelope.message, options);
    this.name = 'AdapterError';
    this.code = envelope.code;
    this.retryable = envelope.retryable;
    this.fallback = envelope.fallback;
    this.requestId = envelope.request_id;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function stringOr(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.length > 0 ? value : fallback;
}

export async function adapterErrorFromResponse(response: Response): Promise<AdapterError> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const body = isRecord(payload) ? payload : {};
  return new AdapterError({
    code: stringOr(body.code, `HTTP_${response.status}`),
    message: stringOr(body.message, `Request failed with HTTP ${response.status}`),
    retryable: body.retryable === true,
    fallback: typeof body.fallback === 'string' ? body.fallback : null,
    request_id: typeof body.request_id === 'string' ? body.request_id : null,
  });
}

export function asAdapterError(error: unknown): AdapterError {
  if (error instanceof AdapterError) return error;
  if (error instanceof Error) {
    return new AdapterError({
      code: 'CLIENT_ERROR',
      message: error.message,
      retryable: true,
      fallback: 'mock',
      request_id: null,
    }, { cause: error });
  }
  return new AdapterError({
    code: 'UNKNOWN_CLIENT_ERROR',
    message: '發生未知的前端錯誤。',
    retryable: false,
    fallback: 'reload',
    request_id: null,
  });
}
