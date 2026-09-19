import { useEffect, useMemo, useRef, useState } from 'react';
import type { FrontendAdapter } from '../adapters/adapter';
import { asAdapterError } from '../adapters/errors';
import { AppShell } from '../components/AppShell';
import { StatusBanner } from '../components/StatusBanner';
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
} from '../speech/gateway';
import { promptToUtterance } from '../speech/mixedPrompt';
import {
  canAnswerInStudentInteractionGroup,
  getStudentInteractionGroup,
  showsNextInStudentInteractionGroup,
} from './studentInteractions';

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

const phaseHeadings: Record<TeachingPhase, string> = {
  introduction: '課程介紹',
  demonstration: '發音示範',
  read_aloud: '跟讀練習',
  comprehension: '理解練習',
  hint: '作答提示',
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
    return '回饋服務暫時受限，你仍可繼續回答。';
  }
  if (fallbacks.includes('asr_cpu')) {
    return '若語音辨識不準，可以修改文字或改用鍵盤。';
  }
  if (fallbacks.includes('tts_prerecorded')) {
    return '目前使用備援語音，你仍可繼續作答。';
  }
  return fallbacks.length ? '目前使用備援服務，你可以繼續或重試。' : null;
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
        setSessionMessage('已恢復目前進度。');
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
            if (!active) return;
            setStreamStatus(status);
            if (status === 'connected') {
              setSessionMessage((message) => (
                message === '連線中斷，正在重新連線。' ? '' : message
              ));
            }
          },
          onError: (streamError) => {
            if (!active) return;
            setStreamStatus('reconnecting');
            const normalized = asAdapterError(streamError);
            if (normalized.code === 'SESSION_NOT_FOUND') setError(streamError);
            else setSessionMessage('連線中斷，正在重新連線。');
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
          ? '目前無法播放實際語音，你仍可使用鍵盤回答。'
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
    const current = viewRef.current;
    if (
      !current
      || current.state === 'COMPLETE'
      || !canAnswerInStudentInteractionGroup(getStudentInteractionGroup(current.phase))
    ) return;
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
      setSessionMessage('辨識失敗；可以重錄，或在提供鍵盤回答的階段改用鍵盤。');
    } finally {
      setBusyLabel(null);
    }
  }

  async function beginKeyboardAnswer(): Promise<void> {
    const current = viewRef.current;
    if (
      !current
      || current.state === 'COMPLETE'
      || !canAnswerInStudentInteractionGroup(getStudentInteractionGroup(current.phase))
    ) return;
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
      setInputError('請先按目前階段提供的回答按鈕，再送出回答。');
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

  async function goToNextStep(): Promise<void> {
    if (transcriptMode) {
      setInputError('請先送出目前回答，再進入下一步。');
      transcriptRef.current?.focus();
      return;
    }
    const next = await runControl('next');
    if (!next) return;
    pendingTurnRef.current = null;
    setDraftTranscript('');
    setAsrDevice(undefined);
    setInputError('');
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

  const currentView = view;
  const interactionGroup = currentView
    ? currentView.state === 'COMPLETE'
      ? 'complete'
      : getStudentInteractionGroup(currentView.phase)
    : null;
  const canAnswerInCurrentPhase = canAnswerInStudentInteractionGroup(interactionGroup);
  const showNext = showsNextInStudentInteractionGroup(interactionGroup);
  const canBeginAnswer = Boolean(
    currentView
      && canAnswerInCurrentPhase
      && currentView.state !== 'COMPLETE'
      && currentView.health.status !== 'offline'
      && speechState !== 'TRANSCRIBING'
      && speechState !== 'EVALUATING'
      && !busyLabel,
  );
  const showTranscriptCard = Boolean(
    currentView
      && interactionGroup !== 'teaching'
      && interactionGroup !== 'complete'
      && (transcriptMode || draftTranscript),
  );
  const connectionMessage = streamStatus === 'reconnecting'
    ? '連線中斷，正在重新連線。'
    : streamStatus === 'connecting'
      ? '正在連線。'
      : null;
  const activeSpeechMessage = speechState === 'IDLE' ? null : speechStateLabels[speechState];
  const currentStatusMessage = busyLabel
    || connectionMessage
    || activeSpeechMessage
    || sessionMessage
    || currentView?.feedback
    || '';
  const studentHeading = currentView?.lessonTitle === '目前教材'
    ? phaseHeadings[currentView.phase]
    : currentView?.lessonTitle || '學習活動';
  const showSeparatePhase = Boolean(currentView && currentView.lessonTitle !== '目前教材');

  return (
    <AppShell currentLabel="學生模式">
      <main id="main-content" className="page" tabIndex={-1} aria-busy={Boolean(busyLabel)}>
        {!currentView && !error ? <LoadingState label="載入學生活動……" /> : null}
        {error ? <ErrorState error={error} onRetry={() => void refreshSnapshot()} showTechnicalDetails={false} /> : null}
        {speechError ? (
          <ErrorState
            error={speechError}
            showTechnicalDetails={false}
            onRetry={() => {
              setSpeechError(null);
              setSessionMessage('可以重錄；若目前階段提供鍵盤回答，也可以改用鍵盤。');
            }}
          />
        ) : null}
        {currentView ? (
          <>
            <StatusBanner health={currentView.health} />
            <section className="card student-card" aria-labelledby="student-heading">
              {showSeparatePhase ? <p className="phase-label">目前階段：{phaseLabels[currentView.phase]}</p> : null}
              <h1 id="student-heading" data-page-title tabIndex={-1}>{studentHeading}</h1>
              <p className="prompt">{currentView.prompt}</p>
              {interactionGroup !== 'complete' ? (
                <p className="live-message" role="status" aria-live="polite">{currentStatusMessage}</p>
              ) : null}
              {fallbackMessage(currentView.fallbacks) ? (
                <p className="fallback-message">{fallbackMessage(currentView.fallbacks)}</p>
              ) : null}
              {interactionGroup === 'complete' ? (
                <p className="completion-message" role="status" aria-live="polite">
                  {currentView.feedback || '本課完成。'}
                </p>
              ) : (
                <div className="button-grid" aria-label="目前可用操作">
                  <button className="button" type="button" disabled={Boolean(busyLabel) || speechState === 'SPEAKING'} onClick={() => void playPrompt()}>
                    播放提示
                  </button>
                  {interactionGroup === 'practice' ? (
                    <>
                      <button
                        className="button primary-large"
                        type="button"
                        disabled={speechState === 'LISTENING' ? Boolean(busyLabel) : !canBeginAnswer}
                        onClick={() => void (speechState === 'LISTENING' ? stopVoiceAnswer() : beginVoiceAnswer())}
                      >
                        {speechState === 'LISTENING' ? '停止錄音並辨識' : '回答這題（語音）'}
                      </button>
                      <button className="button secondary" type="button" disabled={!canBeginAnswer} onClick={() => void beginKeyboardAnswer()}>
                        鍵盤回答
                      </button>
                    </>
                  ) : null}
                  {interactionGroup === 'hint' ? (
                    <button
                      className="button primary-large"
                      type="button"
                      disabled={speechState === 'LISTENING' ? Boolean(busyLabel) : !canBeginAnswer}
                      onClick={() => void (speechState === 'LISTENING' ? stopVoiceAnswer() : beginVoiceAnswer())}
                    >
                      {speechState === 'LISTENING' ? '停止錄音並辨識' : '繼續回答'}
                    </button>
                  ) : null}
                  {showNext ? (
                    <button
                      className="button secondary"
                      type="button"
                      disabled={Boolean(busyLabel) || speechState !== 'IDLE'}
                      onClick={() => void goToNextStep()}
                    >
                      下一步
                    </button>
                  ) : null}
                </div>
              )}
            </section>

            {showTranscriptCard ? <section className="card transcript-card" aria-labelledby="transcript-heading">
              <h2 id="transcript-heading">確認回答</h2>
              <p>確認或修改後送出。</p>
              <label htmlFor="student-transcript">回答內容</label>
              <textarea
                id="student-transcript"
                ref={transcriptRef}
                rows={4}
                value={draftTranscript}
                onChange={(event) => setDraftTranscript(event.target.value)}
                disabled={Boolean(busyLabel) || currentView.state === 'COMPLETE'}
              />
              {inputError ? <p className="field-error" role="alert">{inputError}</p> : null}
              <div className="button-row">
                <button className="button primary-large" type="button" disabled={Boolean(busyLabel) || !draftTranscript.trim() || !transcriptMode || currentView.state === 'COMPLETE'} onClick={() => void submitDraft()}>
                  送出這個回答
                </button>
                <button className="button secondary" type="button" disabled={Boolean(busyLabel) || currentView.state === 'COMPLETE'} onClick={() => void rerecord()}>
                  清除並重錄
                </button>
              </div>
            </section> : null}

            <nav className="demo-mode-switch" aria-label="Demo 模式切換">
              <button className="button secondary" type="button" onClick={() => void switchToObserver()}>
                切換至教師／家長模式
              </button>
            </nav>
          </>
        ) : null}
      </main>
    </AppShell>
  );
}
