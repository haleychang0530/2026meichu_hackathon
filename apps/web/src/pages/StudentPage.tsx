import { useEffect, useMemo, useRef, useState } from 'react';
import type { FrontendAdapter } from '../adapters/adapter';
import { asAdapterError } from '../adapters/errors';
import { AppShell } from '../components/AppShell';
import { ErrorState, LoadingState } from '../components/States';
import { useNarration } from '../accessibility/NarrationProvider';
import type {
  StudentAction,
  StudentSessionViewModel,
  TeachingPhase,
} from '../types/viewModels';
import { navigateTo } from '../app/routing';
import {
  createSpeechGatewayClient,
  type SpeechGatewayClient,
  type SpeechState,
  type SpeechUtterance,
} from '../speech/gateway';

const speechStateLabels: Record<SpeechState, string> = {
  IDLE: '待機',
  SPEAKING: '播放提示中',
  LISTENING: '聆聽中，請開始回答',
  TRANSCRIBING: '辨識中',
  EVALUATING: '準備送出回饋',
};

const phaseLabels: Record<TeachingPhase, string> = {
  introduction: '介紹',
  demonstration: '示範',
  read_aloud: '跟讀',
  comprehension: '理解活動',
  hint: '提示',
  review: '複習',
  complete: '完成',
};

type TranscriptMode = 'voice' | 'keyboard';
type PendingTurn = {
  readonly key: string;
  readonly transcript: string;
  readonly inputMode: TranscriptMode;
  readonly asrDevice?: 'cpu' | 'npu';
};

function promptToUtterance(prompt: string): SpeechUtterance {
  const text = prompt.trim() || '目前沒有可播放的提示。';
  return {
    schema_version: '0.1.0',
    id: 'utt_student_prompt',
    segments: [{
      lang: 'zh-TW',
      hanji: text,
      tailo_citation: null,
      poj_citation: null,
      zh_gloss: text,
      source: 'generated',
      pronunciation_status: 'needs_review',
    }],
    tts_provider: 'prerecorded',
    audio_url: null,
    audio_cache_key: null,
  };
}

function createOperationKey(prefix: string): string {
  const suffix = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${suffix}`;
}

function isRevisionConflict(error: unknown): boolean {
  return asAdapterError(error).code === 'SESSION_REVISION_CONFLICT';
}

function withPreservedTranscript(
  next: StudentSessionViewModel,
  previous: StudentSessionViewModel | null,
): StudentSessionViewModel {
  return next.transcript || !previous?.transcript
    ? next
    : { ...next, transcript: previous.transcript };
}

function fallbackMessage(fallbacks: readonly string[]): string | null {
  if (fallbacks.includes('mi300_offline')) {
    return 'MI300 暫時離線；目前使用筆電本機規則完成回饋，你可以繼續回答。';
  }
  if (fallbacks.includes('asr_cpu')) {
    return '目前使用筆電 CPU 語音辨識；若辨識不準，可以修改逐字稿或改用鍵盤。';
  }
  if (fallbacks.includes('tts_prerecorded')) {
    return '目前使用核可的預錄語音備援；你仍可重播提示或用鍵盤回答。';
  }
  return fallbacks.length ? '目前使用明確標示的降級路徑；你可以繼續或重試。' : null;
}

export function StudentPage({
  adapter,
  sessionId,
  speechClient: providedSpeechClient,
}: {
  readonly adapter: FrontendAdapter;
  readonly sessionId: string;
  readonly speechClient?: SpeechGatewayClient;
}) {
  const narration = useNarration();
  const [view, setView] = useState<StudentSessionViewModel | null>(null);
  const viewRef = useRef<StudentSessionViewModel | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [speechError, setSpeechError] = useState<unknown>(null);
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  const [sessionMessage, setSessionMessage] = useState('');
  const [streamStatus, setStreamStatus] = useState<'connecting' | 'connected' | 'reconnecting'>('connecting');
  const [draftTranscript, setDraftTranscriptState] = useState('');
  const draftTranscriptRef = useRef('');
  const [transcriptMode, setTranscriptMode] = useState<TranscriptMode | null>(null);
  const [asrDevice, setAsrDevice] = useState<'cpu' | 'npu' | undefined>(undefined);
  const [inputError, setInputError] = useState('');
  const transcriptRef = useRef<HTMLTextAreaElement | null>(null);
  const actionKeysRef = useRef(new Map<StudentAction, string>());
  const pendingTurnRef = useRef<PendingTurn | null>(null);
  const snapshotRequestRef = useRef<Promise<StudentSessionViewModel> | null>(null);
  const speechClient = useMemo(
    () => providedSpeechClient || createSpeechGatewayClient(),
    [providedSpeechClient],
  );
  const [speechState, setSpeechState] = useState<SpeechState>(speechClient.state);

  function commitView(next: StudentSessionViewModel): void {
    viewRef.current = next;
    setView(next);
  }

  function setDraftTranscript(value: string): void {
    draftTranscriptRef.current = value;
    setDraftTranscriptState(value);
    setInputError('');
    if (pendingTurnRef.current && pendingTurnRef.current.transcript !== value) {
      pendingTurnRef.current = null;
    }
  }

  async function refreshSnapshot(showError = true): Promise<StudentSessionViewModel> {
    if (snapshotRequestRef.current) return snapshotRequestRef.current;
    const request = adapter.getStudentSession(sessionId, { snapshot: true })
      .then((next) => {
        const merged = withPreservedTranscript(next, viewRef.current);
        commitView(merged);
        setSessionMessage('已從 Core Backend snapshot 恢復目前進度。');
        setError(null);
        return merged;
      })
      .catch((nextError) => {
        if (showError) setError(nextError);
        throw nextError;
      })
      .finally(() => {
        snapshotRequestRef.current = null;
      });
    snapshotRequestRef.current = request;
    return request;
  }

  useEffect(() => {
    const unsubscribe = speechClient.subscribe(setSpeechState);
    return () => {
      unsubscribe();
      void speechClient.cancel();
      narration.stop();
      speechClient.dispose();
    };
  }, [speechClient]);

  useEffect(() => {
    let active = true;
    let unsubscribe: () => void = () => undefined;
    setError(null);
    setView(null);
    viewRef.current = null;
    setStreamStatus('connecting');

    void adapter.getStudentSession(sessionId)
      .then((initial) => {
        if (!active) return;
        commitView(initial);
        unsubscribe = adapter.subscribeStudentSession(sessionId, {
          afterEventId: initial.lastEventId,
          onStatus: (status) => {
            if (active) setStreamStatus(status);
          },
          onError: (streamError) => {
            if (!active) return;
            setStreamStatus('reconnecting');
            const normalized = asAdapterError(streamError);
            if (normalized.code === 'SESSION_NOT_FOUND') setError(streamError);
            else setSessionMessage('即時進度連線中斷，正在以 snapshot 自動恢復。');
            void refreshSnapshot(false).catch(() => undefined);
          },
          onEvent: (event) => {
            if (!active || event.event_id <= (viewRef.current?.lastEventId ?? 0)) return;
            setStreamStatus('connected');
            void refreshSnapshot(false).catch(() => undefined);
          },
        });
      })
      .catch((nextError) => {
        if (active) setError(nextError);
      });

    return () => {
      active = false;
      unsubscribe();
    };
  }, [adapter, sessionId]);

  useEffect(() => {
    if (transcriptMode === 'keyboard') transcriptRef.current?.focus();
  }, [transcriptMode]);

  function actionKey(action: StudentAction): string {
    const existing = actionKeysRef.current.get(action);
    if (existing) return existing;
    const created = createOperationKey(`student-${action}`);
    actionKeysRef.current.set(action, created);
    return created;
  }

  function resolveActionError(nextError: unknown): void {
    if (isRevisionConflict(nextError)) {
      setSessionMessage('其他控制已更新教學進度，正在重新整理後再試。');
      void refreshSnapshot().catch(() => undefined);
    } else {
      setError(nextError);
    }
  }

  async function runControl(action: StudentAction): Promise<StudentSessionViewModel | null> {
    const current = viewRef.current;
    if (!current) return null;
    const key = actionKey(action);
    setBusyLabel(action === 'hint' ? '準備提示……' : action === 'next' ? '進入下一步……' : '更新教學狀態……');
    setError(null);
    setSpeechError(null);
    try {
      // Every control boundary first stops TTS, browser speech and recording.
      narration.stop();
      await speechClient.cancel();
      const next = await adapter.submitStudentAction(sessionId, action, {
        expectedRevision: current.revision,
        idempotencyKey: key,
      });
      actionKeysRef.current.delete(action);
      commitView(withPreservedTranscript(next, current));
      setSessionMessage(next.feedback);
      narration.announce(next.feedback, { priority: 2, key: 'student-feedback' });
      return next;
    } catch (nextError) {
      if (isRevisionConflict(nextError)) actionKeysRef.current.delete(action);
      resolveActionError(nextError);
      return null;
    } finally {
      setBusyLabel(null);
    }
  }

  async function playPrompt(): Promise<void> {
    const next = await runControl('listen');
    if (!next) return;
    try {
      setSessionMessage('提示播放中；播放結束後才會開啟麥克風。');
      await speechClient.play(promptToUtterance(next.prompt));
      setSessionMessage(
        speechClient.mode === 'mock'
          ? '目前是 mock 語音模式；這次只模擬播放狀態，不會產生實際聲音。請改用 -SpeechProfile cpu。'
          : '提示播放完成；你可以開始語音或鍵盤回答。',
      );
    } catch (nextError) {
      setSpeechError(nextError);
    }
  }

  async function recoverAfterMicrophoneFailure(): Promise<void> {
    const current = viewRef.current;
    if (!current || current.state !== 'LISTENING') return;
    try {
      const next = await adapter.submitStudentAction(sessionId, 'pause', {
        expectedRevision: current.revision,
        idempotencyKey: actionKey('pause'),
      });
      actionKeysRef.current.delete('pause');
      commitView(withPreservedTranscript(next, current));
    } catch {
      void refreshSnapshot(false).catch(() => undefined);
    }
  }

  async function beginVoiceAnswer(): Promise<void> {
    if (!viewRef.current || viewRef.current.state === 'COMPLETE') return;
    const next = await runControl('answer');
    if (!next || !next.canAnswer) return;
    setDraftTranscript('');
    setTranscriptMode('voice');
    setAsrDevice(undefined);
    setBusyLabel('啟用麥克風……');
    try {
      await speechClient.startRecording('nan-TW');
      setSessionMessage('正在聆聽；按停止錄音後會先顯示你的逐字稿。');
    } catch (nextError) {
      setSpeechError(nextError);
      setTranscriptMode(null);
      await recoverAfterMicrophoneFailure();
    } finally {
      setBusyLabel(null);
    }
  }

  async function stopVoiceAnswer(): Promise<void> {
    narration.stop();
    setBusyLabel('辨識回答……');
    setSpeechError(null);
    try {
      const transcript = await speechClient.stopRecording();
      speechClient.markEvaluationComplete();
      setDraftTranscript(transcript.text);
      setTranscriptMode('voice');
      setAsrDevice(transcript.device === 'npu' ? 'npu' : 'cpu');
      setSessionMessage('這是辨識到的你的回答；請確認、修改後再送出。');
    } catch (nextError) {
      speechClient.markEvaluationComplete();
      setSpeechError(nextError);
      setSessionMessage('辨識失敗；可以重錄或改用鍵盤輸入。');
    } finally {
      setBusyLabel(null);
    }
  }

  async function beginKeyboardAnswer(): Promise<void> {
    if (!viewRef.current || viewRef.current.state === 'COMPLETE') return;
    const next = await runControl('answer');
    if (!next || !next.canAnswer) return;
    setDraftTranscript('');
    setTranscriptMode('keyboard');
    setAsrDevice(undefined);
    setSessionMessage('請輸入你自己的回答；畫面不會提供標準答案。');
  }

  async function submitDraft(): Promise<void> {
    const transcript = draftTranscriptRef.current.trim();
    const current = viewRef.current;
    if (!current) return;
    if (!transcript) {
      setInputError('請先輸入或錄下一段回答。');
      transcriptRef.current?.focus();
      return;
    }
    const mode = transcriptMode;
    if (!mode) {
      setInputError('請先按「開始鍵盤回答」或「開始語音回答」，再送出回答。');
      transcriptRef.current?.focus();
      return;
    }
    const previous = pendingTurnRef.current;
    const pending = previous && previous.transcript === transcript && previous.inputMode === mode
      ? previous
      : {
          key: createOperationKey('student-turn'),
          transcript,
          inputMode: mode,
          asrDevice: mode === 'voice' ? asrDevice : undefined,
        };
    pendingTurnRef.current = pending;
    setBusyLabel('送出回答並等待回饋……');
    setError(null);
    setSpeechError(null);
    try {
      narration.stop();
      await speechClient.cancel();
      const next = await adapter.submitStudentAnswer(sessionId, {
        schema_version: '0.1.0',
        transcript,
        input_mode: mode,
        ...(pending.asrDevice ? { asr_device: pending.asrDevice } : {}),
      }, {
        expectedRevision: current.revision,
        idempotencyKey: pending.key,
      });
      pendingTurnRef.current = null;
      commitView(withPreservedTranscript(next, current));
      setDraftTranscript(next.transcript || transcript);
      setSessionMessage(next.feedback);
      narration.announce(next.feedback, { priority: 2, key: 'student-feedback' });
      setTranscriptMode(null);
    } catch (nextError) {
      if (isRevisionConflict(nextError)) pendingTurnRef.current = null;
      resolveActionError(nextError);
    } finally {
      setBusyLabel(null);
    }
  }

  async function rerecord(): Promise<void> {
    pendingTurnRef.current = null;
    setDraftTranscript('');
    setTranscriptMode(null);
    setSpeechError(null);
    await beginVoiceAnswer();
  }

  async function switchToObserver(): Promise<void> {
    narration.stop();
    await speechClient.cancel();
    navigateTo(`/session/${encodeURIComponent(sessionId)}/observer`);
  }

  async function returnToCapture(): Promise<void> {
    narration.stop();
    await speechClient.cancel();
    navigateTo('/capture');
  }

  const currentView = view;
  const canBeginAnswer = Boolean(
    currentView
      && currentView.state !== 'COMPLETE'
      && currentView.health.status !== 'offline'
      && speechState !== 'TRANSCRIBING'
      && speechState !== 'EVALUATING'
      && !busyLabel,
  );
  const streamLabel = streamStatus === 'connected'
    ? '即時進度已連線'
    : streamStatus === 'reconnecting'
      ? '即時進度斷線，正在重連並以 snapshot 恢復'
      : '正在連接即時進度';

  return (
    <AppShell currentLabel="學生模式">
      <main id="main-content" className="page" tabIndex={-1} aria-busy={Boolean(busyLabel)}>
        <div className="student-top-actions" aria-label="課程導覽">
          <button className="button secondary" type="button" onClick={() => void returnToCapture()}>返回上一頁</button>
          <button className="button secondary" type="button" onClick={() => void switchToObserver()}>教師／家長模式</button>
        </div>
        <p className="eyebrow">一起來聽台語、說台語</p>
        {!currentView && !error ? <LoadingState label="載入學生活動……" /> : null}
        {error ? <ErrorState error={error} onRetry={() => void refreshSnapshot()} /> : null}
        {speechError ? (
          <ErrorState
            error={speechError}
            onRetry={() => {
              setSpeechError(null);
              setSessionMessage('可以重錄，或改用下方鍵盤輸入。');
            }}
          />
        ) : null}
        {currentView ? (
          <>
            <section className="card student-card" aria-labelledby="student-heading">
              <div className="progress-line"><span>{currentView.progressLabel}</span><span>{currentView.progressValue}%</span></div>
              <div className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={currentView.progressValue} aria-label="教學進度">
                <span style={{ width: `${currentView.progressValue}%` }} />
              </div>
              <div className="student-status-grid" aria-label="目前教學狀態">
                <span>目前活動：{phaseLabels[currentView.phase]}</span>
                {streamStatus !== 'connected' ? <span>{streamLabel}</span> : null}
              </div>
              <h1 id="student-heading" data-page-title tabIndex={-1}>{currentView.lessonTitle}</h1>
              <p className="prompt">{currentView.prompt}</p>
              <p className="live-message" role="status" aria-live="polite">{sessionMessage || currentView.feedback}</p>
              {fallbackMessage(currentView.fallbacks) ? (
                <p className="fallback-message" role="status" aria-live="polite">{fallbackMessage(currentView.fallbacks)}</p>
              ) : null}
              {speechState !== 'IDLE' ? <p className="speech-status" role="status" aria-live="polite">{speechStateLabels[speechState]}</p> : null}
              <div className="button-grid" aria-label="學生操作">
                <button className="button" type="button" disabled={Boolean(busyLabel) || speechState === 'SPEAKING'} onClick={() => void playPrompt()}>
                  {currentView.phase === 'demonstration' ? '聽完整課文' : '播放／重播提示'}
                </button>
                <button
                  className="button primary-large"
                  type="button"
                  disabled={!canBeginAnswer && speechState !== 'LISTENING'}
                  onClick={() => void (speechState === 'LISTENING' ? stopVoiceAnswer() : beginVoiceAnswer())}
                >
                  {speechState === 'LISTENING' ? '停止並查看回答' : '開始語音回答'}
                </button>
                <button className="button secondary" type="button" disabled={!canBeginAnswer} onClick={() => void beginKeyboardAnswer()}>
                  開始鍵盤回答
                </button>
                <button className="button secondary" type="button" disabled={Boolean(busyLabel)} onClick={() => void runControl('hint')}>
                  取得提示
                </button>
                <button className="button secondary" type="button" disabled={Boolean(busyLabel) || currentView.state === 'COMPLETE'} onClick={() => void runControl(currentView.state === 'IDLE' ? 'resume' : 'pause')}>
                  {currentView.state === 'IDLE' ? '繼續活動' : '停止音訊／暫停'}
                </button>
                <button className="button secondary" type="button" disabled={Boolean(busyLabel) || currentView.state === 'COMPLETE'} onClick={() => void runControl('next')}>
                  下一步
                </button>
              </div>
              {busyLabel ? <p className="live-message" role="status" aria-live="polite">{busyLabel}</p> : null}
            </section>

            {(transcriptMode || draftTranscript) ? <section className="card transcript-card" aria-labelledby="transcript-heading">
              <h2 id="transcript-heading">你的回答</h2>
              <p>確認辨識結果，也可以直接修改文字。</p>
              <label htmlFor="student-transcript">你的逐字稿／回答</label>
              <textarea
                id="student-transcript"
                ref={transcriptRef}
                rows={4}
                value={draftTranscript}
                onChange={(event) => setDraftTranscript(event.target.value)}
                placeholder="請輸入你自己的回答"
                disabled={Boolean(busyLabel) || currentView.state === 'COMPLETE'}
              />
              {inputError ? <p className="field-error" role="alert">{inputError}</p> : null}
              <div className="button-row">
                <button className="button primary-large" type="button" disabled={Boolean(busyLabel) || !draftTranscript.trim() || !transcriptMode || currentView.state === 'COMPLETE'} onClick={() => void submitDraft()}>
                  送出回答
                </button>
                <button className="button secondary" type="button" disabled={Boolean(busyLabel) || currentView.state === 'COMPLETE'} onClick={() => void rerecord()}>
                  清除並重錄
                </button>
              </div>
            </section> : null}

          </>
        ) : null}
      </main>
    </AppShell>
  );
}
