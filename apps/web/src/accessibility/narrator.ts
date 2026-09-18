export type NarrationMode = 'system' | 'app' | null;
export type NarrationDetail = 'brief' | 'standard' | 'verbose';
export type NarrationStatus = 'idle' | 'speaking' | 'paused';

export interface NarrationOptions {
  readonly priority?: number;
  readonly key?: string;
  readonly interrupt?: boolean;
  readonly detail?: NarrationDetail;
}

export interface NarratorSnapshot {
  readonly mode: NarrationMode;
  readonly status: NarrationStatus;
  readonly rate: number;
  readonly detail: NarrationDetail;
  readonly queueLength: number;
  readonly currentText: string;
  readonly lastText: string;
  readonly available: boolean;
}

export interface NarratorController {
  readonly snapshot: NarratorSnapshot;
  subscribe(listener: (snapshot: NarratorSnapshot) => void): () => void;
  setMode(mode: NarrationMode): void;
  setRate(rate: number): void;
  setDetail(detail: NarrationDetail): void;
  announce(text: string, options?: NarrationOptions): string | null;
  stop(): void;
  pause(): void;
  resume(): void;
  replay(): void;
  dispose(): void;
}

interface QueueItem {
  readonly id: string;
  readonly text: string;
  readonly priority: number;
  readonly key?: string;
  readonly detail?: NarrationDetail;
  readonly sequence: number;
}

export interface NarratorControllerOptions {
  readonly mode?: NarrationMode;
  readonly rate?: number;
  readonly detail?: NarrationDetail;
  readonly synthesis?: SpeechSynthesis;
  readonly utteranceFactory?: (text: string) => SpeechSynthesisUtterance;
  readonly idFactory?: () => string;
}

const DETAIL_RANK: Record<NarrationDetail, number> = {
  brief: 0,
  standard: 1,
  verbose: 2,
};

function defaultSynthesis(): SpeechSynthesis | undefined {
  if (typeof window === 'undefined' || typeof window.speechSynthesis === 'undefined') return undefined;
  return window.speechSynthesis;
}

function defaultUtteranceFactory(text: string): SpeechSynthesisUtterance | null {
  if (typeof SpeechSynthesisUtterance === 'undefined') return null;
  return new SpeechSynthesisUtterance(text);
}

function clampRate(rate: number): number {
  if (!Number.isFinite(rate)) return 1;
  return Math.min(2, Math.max(0.5, Math.round(rate * 10) / 10));
}

function createId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return `narration-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * A small, testable Web Speech queue for Chinese UI narration. Lesson audio
 * never enters this queue: the Student page cancels it before the local Speech
 * Gateway starts recording or playing Taiwanese content.
 */
export class AppNarrator implements NarratorController {
  private currentMode: NarrationMode;
  private currentStatus: NarrationStatus = 'idle';
  private currentRate: number;
  private currentDetail: NarrationDetail;
  private readonly synthesis?: SpeechSynthesis;
  private readonly utteranceFactory: (text: string) => SpeechSynthesisUtterance | null;
  private readonly idFactory: () => string;
  private readonly listeners = new Set<(snapshot: NarratorSnapshot) => void>();
  private queue: QueueItem[] = [];
  private current: QueueItem | null = null;
  private lastSpokenText = '';
  private sequence = 0;

  constructor(options: NarratorControllerOptions = {}) {
    this.currentMode = options.mode ?? null;
    this.currentRate = clampRate(options.rate ?? 1);
    this.currentDetail = options.detail ?? 'standard';
    this.synthesis = options.synthesis ?? defaultSynthesis();
    this.utteranceFactory = options.utteranceFactory
      ? (text) => options.utteranceFactory!(text)
      : defaultUtteranceFactory;
    this.idFactory = options.idFactory ?? createId;
  }

  get snapshot(): NarratorSnapshot {
    return {
      mode: this.currentMode,
      status: this.currentStatus,
      rate: this.currentRate,
      detail: this.currentDetail,
      queueLength: this.queue.length,
      currentText: this.current?.text ?? '',
      lastText: this.lastSpokenText,
      available: Boolean(this.synthesis && this.utteranceFactory('test')),
    };
  }

  subscribe(listener: (snapshot: NarratorSnapshot) => void): () => void {
    this.listeners.add(listener);
    listener(this.snapshot);
    return () => this.listeners.delete(listener);
  }

  setMode(mode: NarrationMode): void {
    if (mode === this.currentMode) return;
    if (mode !== 'app') this.stop();
    this.currentMode = mode;
    this.emit();
    if (mode === 'app') this.drain();
  }

  setRate(rate: number): void {
    this.currentRate = clampRate(rate);
    this.emit();
  }

  setDetail(detail: NarrationDetail): void {
    this.currentDetail = detail;
    this.queue = this.queue.filter((item) => !item.detail || DETAIL_RANK[item.detail] <= DETAIL_RANK[detail]);
    this.emit();
  }

  announce(text: string, options: NarrationOptions = {}): string | null {
    const normalized = text.replace(/\s+/g, ' ').trim();
    if (!normalized || this.currentMode !== 'app') return null;
    if (options.detail && DETAIL_RANK[options.detail] > DETAIL_RANK[this.currentDetail]) return null;

    const id = this.idFactory();
    const priority = options.priority ?? 1;
    const item: QueueItem = {
      id,
      text: normalized,
      priority,
      key: options.key,
      detail: options.detail,
      sequence: this.sequence++,
    };
    if (options.key) {
      this.queue = this.queue.filter((queued) => queued.key !== options.key);
    }
    if (options.interrupt || priority >= 3) {
      this.cancelCurrent();
      this.queue = this.queue.filter((queued) => queued.priority > priority);
    }
    this.queue.push(item);
    this.queue.sort((left, right) => right.priority - left.priority || left.sequence - right.sequence);
    this.emit();
    this.drain();
    return id;
  }

  stop(): void {
    this.cancelCurrent();
    this.queue = [];
    this.currentStatus = 'idle';
    this.emit();
  }

  pause(): void {
    if (this.currentStatus !== 'speaking') return;
    this.synthesis?.pause();
    this.currentStatus = 'paused';
    this.emit();
  }

  resume(): void {
    if (this.currentStatus !== 'paused') return;
    this.synthesis?.resume();
    this.currentStatus = 'speaking';
    this.emit();
  }

  replay(): void {
    if (!this.lastSpokenText || this.currentMode !== 'app') return;
    this.announce(this.lastSpokenText, { priority: 4, key: 'replay', interrupt: true });
  }

  dispose(): void {
    this.stop();
    this.listeners.clear();
  }

  private drain(): void {
    if (this.currentMode !== 'app' || this.currentStatus !== 'idle' || this.current || !this.queue.length) return;
    const next = this.queue.shift();
    if (!next) return;
    this.current = next;
    this.lastSpokenText = next.text;
    const utterance = this.utteranceFactory(next.text);
    if (!utterance || !this.synthesis) {
      this.finish(next.id);
      return;
    }
    utterance.lang = 'zh-TW';
    utterance.rate = this.currentRate;
    utterance.onend = () => this.finish(next.id);
    utterance.onerror = () => this.finish(next.id);
    this.currentStatus = 'speaking';
    this.emit();
    try {
      this.synthesis.speak(utterance);
    } catch {
      this.finish(next.id);
    }
  }

  private finish(id: string): void {
    if (this.current?.id !== id) return;
    this.current = null;
    this.currentStatus = 'idle';
    this.emit();
    this.drain();
  }

  private cancelCurrent(): void {
    this.current = null;
    this.currentStatus = 'idle';
    this.synthesis?.cancel();
  }

  private emit(): void {
    const snapshot = this.snapshot;
    this.listeners.forEach((listener) => listener(snapshot));
  }
}

export function createNarratorController(options: NarratorControllerOptions = {}): NarratorController {
  return new AppNarrator(options);
}
