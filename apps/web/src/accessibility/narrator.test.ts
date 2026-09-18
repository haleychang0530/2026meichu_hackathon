import { describe, expect, it, vi } from 'vitest';
import { AppNarrator } from './narrator';

type FakeUtterance = SpeechSynthesisUtterance & { readonly text: string };

function createFakeSpeech() {
  let active: FakeUtterance | null = null;
  const spoken: FakeUtterance[] = [];
  const synthesis = {
    speak: vi.fn((utterance: FakeUtterance) => {
      active = utterance;
      spoken.push(utterance);
    }),
    cancel: vi.fn(() => { active = null; }),
    pause: vi.fn(),
    resume: vi.fn(),
  } as unknown as SpeechSynthesis;
  return {
    synthesis,
    spoken,
    get active() { return active; },
  };
}

function utteranceFactory(text: string): FakeUtterance {
  return {
    text,
    lang: '',
    rate: 1,
    pitch: 1,
    volume: 1,
    voice: null,
    onend: null,
    onerror: null,
    onpause: null,
    onresume: null,
    onmark: null,
    onboundary: null,
  } as unknown as FakeUtterance;
}

describe('AppNarrator', () => {
  it('requires explicit app mode and keeps system-reader mode silent', () => {
    const fake = createFakeSpeech();
    const narrator = new AppNarrator({ synthesis: fake.synthesis, utteranceFactory, idFactory: () => 'narration-1' });

    expect(narrator.announce('不應該播放')).toBeNull();
    expect(fake.synthesis.speak).not.toHaveBeenCalled();

    narrator.setMode('app');
    expect(narrator.announce('現在可以播放')).toBe('narration-1');
    expect(fake.synthesis.speak).toHaveBeenCalledOnce();
    expect(fake.spoken[0].lang).toBe('zh-TW');
    narrator.setMode('system');
    expect(fake.synthesis.cancel).toHaveBeenCalled();
    expect(narrator.snapshot.status).toBe('idle');
  });

  it('interrupts stale low-priority speech and supports pause, resume, and replay', () => {
    const fake = createFakeSpeech();
    const narrator = new AppNarrator({ mode: 'app', synthesis: fake.synthesis, utteranceFactory });
    narrator.announce('舊訊息', { priority: 1 });
    narrator.announce('重要狀態', { priority: 3 });

    expect(fake.synthesis.cancel).toHaveBeenCalled();
    expect(fake.spoken.map((item) => item.text)).toEqual(['舊訊息', '重要狀態']);
    expect(fake.active?.text).toBe('重要狀態');

    narrator.pause();
    expect(narrator.snapshot.status).toBe('paused');
    expect(fake.synthesis.pause).toHaveBeenCalledOnce();
    narrator.resume();
    expect(narrator.snapshot.status).toBe('speaking');
    expect(fake.synthesis.resume).toHaveBeenCalledOnce();

    fake.active?.onend?.(undefined as unknown as SpeechSynthesisEvent);
    narrator.replay();
    expect(fake.spoken.at(-1)?.text).toBe('重要狀態');
  });

  it('drops messages above the selected detail level before they reach the queue', () => {
    const fake = createFakeSpeech();
    const narrator = new AppNarrator({ mode: 'app', detail: 'brief', synthesis: fake.synthesis, utteranceFactory });

    expect(narrator.announce('詳細診斷', { detail: 'verbose' })).toBeNull();
    expect(narrator.snapshot.queueLength).toBe(0);
    expect(fake.synthesis.speak).not.toHaveBeenCalled();
  });
});
