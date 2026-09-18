import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  HttpSpeechGatewayClient,
  MockSpeechGatewayClient,
  type SpeechState,
  type SpeechUtterance,
} from './gateway';

const utterance: SpeechUtterance = {
  schema_version: '0.1.0',
  id: 'utt_frontend_stage04',
  segments: [
    {
      lang: 'nan-TW',
      hanji: '食飯',
      tailo_citation: 'tsiah-png',
      poj_citation: 'chiah-peng',
      zh_gloss: '吃飯',
      source: 'generated',
      pronunciation_status: 'verified',
    },
  ],
  tts_provider: 'mms-tts-nan',
  audio_url: null,
  audio_cache_key: null,
};

describe('MockSpeechGatewayClient', () => {
  it('walks recording → transcription → evaluation → playback without a microphone', async () => {
    const client = new MockSpeechGatewayClient({ delayMs: 0 });
    const states: SpeechState[] = [];
    client.subscribe((state) => states.push(state));

    await client.startRecording();
    expect(client.state).toBe('LISTENING');
    const transcript = await client.stopRecording();
    expect(transcript.text).toBe('這是一段測試語音。');
    expect(client.state).toBe('EVALUATING');

    client.markEvaluationComplete();
    expect(client.state).toBe('IDLE');
    await client.play(utterance);
    expect(client.state).toBe('IDLE');
    expect(states).toEqual([
      'IDLE',
      'LISTENING',
      'TRANSCRIBING',
      'EVALUATING',
      'IDLE',
      'SPEAKING',
      'IDLE',
    ]);
    client.dispose();
  });

  it('cancels an active mock recording before playback', async () => {
    const client = new MockSpeechGatewayClient({ delayMs: 10 });
    await client.startRecording();
    await client.play(utterance);
    await expect(client.stopRecording()).rejects.toThrow('沒有進行中的錄音');
    expect(client.state).toBe('IDLE');
    client.dispose();
  });
});

describe('HttpSpeechGatewayClient', () => {
  afterEach(() => vi.restoreAllMocks());

  it('uses the Speech Gateway multipart and WAV routes with browser media ownership', async () => {
    const track = { stop: vi.fn() } as unknown as MediaStreamTrack;
    const stream = {
      getTracks: () => [track],
    } as unknown as MediaStream;
    let recorder: MediaRecorder;
    recorder = {
      state: 'inactive',
      mimeType: 'audio/webm',
      ondataavailable: null,
      onstop: null,
      onerror: null,
      start: vi.fn(() => { (recorder as unknown as { state: string }).state = 'recording'; }),
      stop: vi.fn(() => {
        recorder.ondataavailable?.({ data: new Blob(['synthetic']) } as BlobEvent);
        (recorder as unknown as { state: string }).state = 'inactive';
        recorder.onstop?.(new Event('stop'));
      }),
    } as unknown as MediaRecorder;

    const fakeAudio = {
      src: '',
      onended: null,
      onerror: null,
      play: vi.fn(async () => {
        queueMicrotask(() => fakeAudio.onended?.(new Event('ended')));
      }),
      pause: vi.fn(),
      removeAttribute: vi.fn(),
      load: vi.fn(),
    } as unknown as HTMLAudioElement;
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:stage04');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);

    const calls: Array<{ readonly url: string; readonly init?: RequestInit }> = [];
    const fetchImpl: typeof fetch = vi.fn(async (input, init) => {
      const url = String(input);
      calls.push({ url, init });
      if (url.endsWith('/local/cancel')) {
        return new Response(JSON.stringify({ schema_version: '0.1.0', request_id: 'cancel', status: 'cancelled' }), { status: 200 });
      }
      if (url.endsWith('/v1/audio/transcriptions')) {
        expect(init?.body).toBeInstanceOf(FormData);
        expect((init?.body as FormData).get('device_preference')).toBe('cpu');
        return new Response(JSON.stringify({
          schema_version: '0.1.0',
          request_id: 'asr',
          text: '食飯',
          language: 'nan-TW',
          device: 'cpu',
          latency_ms: 3,
        }), { status: 200 });
      }
      if (url.endsWith('/v1/audio/speech')) {
        expect(JSON.parse(String(init?.body))).toEqual({
          schema_version: '0.1.0',
          utterance,
          format: 'wav',
        });
        return new Response(new Blob(['RIFFsynthetic']), {
          status: 200,
          headers: { 'content-type': 'audio/wav' },
        });
      }
      throw new Error(`Unexpected URL: ${url}`);
    });

    const client = new HttpSpeechGatewayClient({
      baseUrl: 'http://127.0.0.1:8200',
      fetchImpl,
      mediaDevices: { getUserMedia: vi.fn(async () => stream) },
      mediaRecorderFactory: () => recorder,
      audioFactory: () => fakeAudio,
      requestIdFactory: () => '00000000-0000-4000-8000-000000000401',
    });

    await client.startRecording();
    expect(client.state).toBe('LISTENING');
    const transcript = await client.stopRecording();
    expect(transcript.text).toBe('食飯');
    expect(client.state).toBe('EVALUATING');
    expect(track.stop).toHaveBeenCalled();

    client.markEvaluationComplete();
    await client.play(utterance);
    expect(client.state).toBe('IDLE');
    expect(fakeAudio.play).toHaveBeenCalledOnce();
    expect(calls.map((call) => call.url)).toEqual([
      'http://127.0.0.1:8200/v1/audio/transcriptions',
      'http://127.0.0.1:8200/v1/audio/speech',
    ]);
    client.dispose();
  });
});
