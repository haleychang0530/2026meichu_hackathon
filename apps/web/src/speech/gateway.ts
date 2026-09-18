import { AdapterError, adapterErrorFromResponse } from '../adapters/errors';
import type { components, operations } from '../generated/speech';

export type SpeechState =
  | 'IDLE'
  | 'SPEAKING'
  | 'LISTENING'
  | 'TRANSCRIBING'
  | 'EVALUATING';

export type SpeechLanguage = 'nan-TW' | 'zh-TW';
// openapi-typescript exposes the external schema's JSON Schema `$defs` as an
// instance property. `$defs` is schema metadata, not part of an Utterance
// payload, so remove only that generator artifact at the client boundary.
export type SpeechUtterance = Omit<components['schemas']['utterance.schema'], '$defs'>;
export type SpeechTranscript =
  operations['transcribeAudio']['responses'][200]['content']['application/json'];
export type SpeechHealth =
  operations['getSpeechHealth']['responses'][200]['content']['application/json'];

export interface SpeechGatewayClient {
  readonly state: SpeechState;
  subscribe(listener: (state: SpeechState) => void): () => void;
  play(utterance: SpeechUtterance): Promise<void>;
  startRecording(language?: SpeechLanguage): Promise<void>;
  stopRecording(): Promise<SpeechTranscript>;
  markEvaluationComplete(): void;
  cancel(): Promise<void>;
  dispose(): void;
}

export interface SpeechGatewayClientOptions {
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
  readonly mediaDevices?: Pick<MediaDevices, 'getUserMedia'>;
  readonly mediaRecorderFactory?: (
    stream: MediaStream,
    options?: MediaRecorderOptions,
  ) => MediaRecorder;
  readonly audioFactory?: () => HTMLAudioElement;
  readonly requestIdFactory?: () => string;
}

export class SpeechGatewayError extends AdapterError {
  constructor(
    envelope: ConstructorParameters<typeof AdapterError>[0],
    options?: { readonly cause?: unknown },
  ) {
    super(envelope, options);
    this.name = 'SpeechGatewayError';
  }
}

const SCHEMA_VERSION = '0.1.0' as const;
const DEFAULT_BASE_URL = 'http://127.0.0.1:8200';
const DEFAULT_TRANSCRIPT = '這是一段測試語音。';

function randomRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return '00000000-0000-4000-8000-000000000000';
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, '');
}

function isAbortError(error: unknown): boolean {
  return (
    (typeof DOMException !== 'undefined'
      && error instanceof DOMException
      && error.name === 'AbortError')
    || (error instanceof Error && error.name === 'AbortError')
  );
}

function speechClientError(
  code: string,
  message: string,
  fallback: string | null,
  cause?: unknown,
): SpeechGatewayError {
  return new SpeechGatewayError(
    {
      code,
      message,
      retryable: true,
      fallback,
      request_id: null,
    },
    cause === undefined ? undefined : { cause },
  );
}

function isAllowedMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined;
  if (typeof MediaRecorder.isTypeSupported !== 'function') return undefined;
  return MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : undefined;
}

function stopTracks(stream: MediaStream): void {
  stream.getTracks().forEach((track) => track.stop());
}

export class HttpSpeechGatewayClient implements SpeechGatewayClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly mediaDevices?: Pick<MediaDevices, 'getUserMedia'>;
  private readonly mediaRecorderFactory: (
    stream: MediaStream,
    options?: MediaRecorderOptions,
  ) => MediaRecorder;
  private readonly audioFactory: () => HTMLAudioElement;
  private readonly requestIdFactory: () => string;
  private readonly listeners = new Set<(state: SpeechState) => void>();
  private currentState: SpeechState = 'IDLE';
  private recording: {
    readonly recorder: MediaRecorder;
    readonly stream: MediaStream;
    readonly language: SpeechLanguage;
    readonly chunks: Blob[];
  } | null = null;
  private activeAudio: HTMLAudioElement | null = null;
  private activeObjectUrl: string | null = null;
  private activeRequest: AbortController | null = null;

  constructor(options: SpeechGatewayClientOptions = {}) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl || DEFAULT_BASE_URL);
    this.fetchImpl = options.fetchImpl || fetch.bind(globalThis);
    this.mediaDevices = options.mediaDevices || (
      typeof navigator !== 'undefined' ? navigator.mediaDevices : undefined
    );
    this.mediaRecorderFactory = options.mediaRecorderFactory || (
      (stream, recorderOptions) => new MediaRecorder(stream, recorderOptions)
    );
    this.audioFactory = options.audioFactory || (() => new Audio());
    this.requestIdFactory = options.requestIdFactory || randomRequestId;
  }

  get state(): SpeechState {
    return this.currentState;
  }

  subscribe(listener: (state: SpeechState) => void): () => void {
    this.listeners.add(listener);
    listener(this.currentState);
    return () => this.listeners.delete(listener);
  }

  async play(utterance: SpeechUtterance): Promise<void> {
    await this.cancel();
    this.setState('SPEAKING');
    const controller = new AbortController();
    this.activeRequest = controller;
    try {
      const response = await this.request('/v1/audio/speech', {
        method: 'POST',
        body: JSON.stringify({ schema_version: SCHEMA_VERSION, utterance, format: 'wav' }),
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
      });
      const audio = this.audioFactory();
      const objectUrl = URL.createObjectURL(await response.blob());
      this.activeAudio = audio;
      this.activeObjectUrl = objectUrl;
      audio.src = objectUrl;
      await new Promise<void>((resolve, reject) => {
        const finish = () => {
          audio.onended = null;
          audio.onerror = null;
          resolve();
        };
        audio.onended = finish;
        audio.onerror = () => reject(new Error('audio playback failed'));
        void Promise.resolve(audio.play()).catch(reject);
      });
    } catch (error) {
      if (!isAbortError(error)) {
        this.setState('IDLE');
        if (error instanceof AdapterError) throw error;
        throw speechClientError(
          'TTS_FAILED',
          '語音播放失敗，請稍後再試。',
          'prerecorded_audio',
          error,
        );
      }
    } finally {
      if (this.activeAudio) {
        this.activeAudio.pause();
        this.activeAudio.removeAttribute('src');
        this.activeAudio.load();
      }
      if (this.activeObjectUrl) URL.revokeObjectURL(this.activeObjectUrl);
      this.activeAudio = null;
      this.activeObjectUrl = null;
      if (this.activeRequest === controller) this.activeRequest = null;
      if (this.currentState === 'SPEAKING') this.setState('IDLE');
    }
  }

  async startRecording(language: SpeechLanguage = 'nan-TW'): Promise<void> {
    if (this.currentState === 'LISTENING' || this.currentState === 'TRANSCRIBING') {
      throw speechClientError(
        'ASR_FAILED',
        '目前已經在錄音或辨識中。',
        'keyboard_input',
      );
    }
    await this.cancel();
    if (!this.mediaDevices?.getUserMedia) {
      throw speechClientError(
        'ASR_UNAVAILABLE',
        '此瀏覽器沒有可用的麥克風。',
        'keyboard_input',
      );
    }

    let stream: MediaStream | null = null;
    try {
      stream = await this.mediaDevices.getUserMedia({ audio: true, video: false });
      const mimeType = isAllowedMimeType();
      const recorder = this.mediaRecorderFactory(
        stream,
        mimeType ? { mimeType } : undefined,
      );
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      };
      recorder.start();
      this.recording = { recorder, stream, language, chunks };
      this.setState('LISTENING');
    } catch (error) {
      if (stream) stopTracks(stream);
      this.setState('IDLE');
      throw speechClientError(
        'ASR_UNAVAILABLE',
        '無法使用麥克風，請檢查權限或改用鍵盤輸入。',
        'keyboard_input',
        error,
      );
    }
  }

  async stopRecording(): Promise<SpeechTranscript> {
    const recording = this.recording;
    if (!recording) {
      throw speechClientError('ASR_FAILED', '目前沒有進行中的錄音。', 'keyboard_input');
    }
    this.recording = null;
    this.setState('TRANSCRIBING');
    let blob: Blob;
    try {
      blob = await new Promise<Blob>((resolve, reject) => {
        recording.recorder.onstop = () => {
          resolve(new Blob(recording.chunks, {
            type: recording.recorder.mimeType || 'audio/webm',
          }));
        };
        recording.recorder.onerror = () => reject(new Error('recording failed'));
        if (recording.recorder.state === 'recording') recording.recorder.stop();
        else resolve(new Blob(recording.chunks, { type: recording.recorder.mimeType || 'audio/webm' }));
      });
      stopTracks(recording.stream);
      const form = new FormData();
      form.append('file', blob, 'student-answer.webm');
      form.append('language', recording.language);
      form.append('device_preference', 'auto');
      const controller = new AbortController();
      this.activeRequest = controller;
      const response = await this.request('/v1/audio/transcriptions', {
        method: 'POST',
        body: form,
        signal: controller.signal,
      });
      const transcript = (await response.json()) as SpeechTranscript;
      this.setState('EVALUATING');
      return transcript;
    } catch (error) {
      stopTracks(recording.stream);
      this.setState('IDLE');
      if (isAbortError(error)) {
        throw speechClientError('ASR_FAILED', '錄音已取消。', 'keyboard_input', error);
      }
      if (error instanceof AdapterError) throw error;
      throw speechClientError(
        'ASR_FAILED',
        '語音辨識失敗，請重錄或改用鍵盤輸入。',
        'keyboard_input',
        error,
      );
    } finally {
      this.activeRequest = null;
    }
  }

  markEvaluationComplete(): void {
    if (this.currentState === 'EVALUATING') this.setState('IDLE');
  }

  async cancel(): Promise<void> {
    const hadActivity = this.currentState !== 'IDLE'
      || this.recording !== null
      || this.activeAudio !== null
      || this.activeRequest !== null;
    this.activeRequest?.abort();
    this.activeRequest = null;
    if (this.recording) {
      const recording = this.recording;
      this.recording = null;
      recording.recorder.ondataavailable = null;
      recording.recorder.onstop = null;
      recording.recorder.onerror = null;
      if (recording.recorder.state === 'recording') recording.recorder.stop();
      stopTracks(recording.stream);
    }
    if (this.activeAudio) {
      this.activeAudio.pause();
      // `play()` waits for either ended or error. Pause alone does not settle
      // that promise, so cancellation must complete the same callback path.
      this.activeAudio.onended?.(new Event('ended'));
    }
    if (this.activeObjectUrl) URL.revokeObjectURL(this.activeObjectUrl);
    this.activeAudio = null;
    this.activeObjectUrl = null;
    this.setState('IDLE');
    if (hadActivity) {
      try {
        await this.request('/local/cancel', { method: 'POST' });
      } catch {
        // Local cancellation is best effort; browser-owned media is already stopped.
      }
    }
  }

  dispose(): void {
    this.activeRequest?.abort();
    if (this.recording) {
      const recording = this.recording;
      this.recording = null;
      if (recording.recorder.state === 'recording') recording.recorder.stop();
      stopTracks(recording.stream);
    }
    if (this.activeAudio) {
      this.activeAudio.pause();
      this.activeAudio.onended?.(new Event('ended'));
    }
    if (this.activeObjectUrl) URL.revokeObjectURL(this.activeObjectUrl);
    this.activeRequest = null;
    this.activeAudio = null;
    this.activeObjectUrl = null;
    this.setState('IDLE');
    this.listeners.clear();
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set('Accept', 'application/json');
    headers.set('X-Request-ID', this.requestIdFactory());
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers,
    });
    if (!response.ok) throw await adapterErrorFromResponse(response);
    return response;
  }

  private setState(nextState: SpeechState): void {
    if (this.currentState === nextState) return;
    this.currentState = nextState;
    this.listeners.forEach((listener) => listener(nextState));
  }
}

export interface MockSpeechGatewayClientOptions {
  readonly transcript?: string;
  readonly delayMs?: number;
}

export class MockSpeechGatewayClient implements SpeechGatewayClient {
  private readonly transcript: string;
  private readonly delayMs: number;
  private readonly listeners = new Set<(state: SpeechState) => void>();
  private currentState: SpeechState = 'IDLE';
  private recording = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private timerResolve: (() => void) | null = null;

  constructor(options: MockSpeechGatewayClientOptions = {}) {
    this.transcript = options.transcript || DEFAULT_TRANSCRIPT;
    this.delayMs = options.delayMs ?? 80;
  }

  get state(): SpeechState {
    return this.currentState;
  }

  subscribe(listener: (state: SpeechState) => void): () => void {
    this.listeners.add(listener);
    listener(this.currentState);
    return () => this.listeners.delete(listener);
  }

  async play(_utterance: SpeechUtterance): Promise<void> {
    await this.cancel();
    this.setState('SPEAKING');
    await this.wait();
    if (this.currentState === 'SPEAKING') this.setState('IDLE');
  }

  async startRecording(_language: SpeechLanguage = 'nan-TW'): Promise<void> {
    await this.cancel();
    this.recording = true;
    this.setState('LISTENING');
  }

  async stopRecording(): Promise<SpeechTranscript> {
    if (!this.recording) {
      throw speechClientError('ASR_FAILED', '目前沒有進行中的錄音。', 'keyboard_input');
    }
    this.recording = false;
    this.setState('TRANSCRIBING');
    await this.wait();
    this.setState('EVALUATING');
    return {
      schema_version: SCHEMA_VERSION,
      request_id: randomRequestId(),
      text: this.transcript,
      language: 'nan-TW',
      device: 'cpu',
      latency_ms: this.delayMs,
    };
  }

  markEvaluationComplete(): void {
    if (this.currentState === 'EVALUATING') this.setState('IDLE');
  }

  async cancel(): Promise<void> {
    this.recording = false;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.timerResolve?.();
    this.timerResolve = null;
    this.setState('IDLE');
  }

  dispose(): void {
    void this.cancel();
    this.listeners.clear();
  }

  private wait(): Promise<void> {
    if (this.delayMs <= 0) return Promise.resolve();
    return new Promise((resolve) => {
      this.timerResolve = resolve;
      this.timer = setTimeout(() => {
        this.timer = null;
        this.timerResolve = null;
        resolve();
      }, this.delayMs);
    });
  }

  private setState(nextState: SpeechState): void {
    if (this.currentState === nextState) return;
    this.currentState = nextState;
    this.listeners.forEach((listener) => listener(nextState));
  }
}

export function createSpeechGatewayClient(): SpeechGatewayClient {
  const mode = import.meta.env.VITE_SPEECH_MODE || 'mock';
  if (mode === 'real') {
    return new HttpSpeechGatewayClient({
      baseUrl: import.meta.env.VITE_SPEECH_GATEWAY_BASE_URL || DEFAULT_BASE_URL,
    });
  }
  return new MockSpeechGatewayClient();
}
