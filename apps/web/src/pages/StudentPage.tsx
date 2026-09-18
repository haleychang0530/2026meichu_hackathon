import { useEffect, useMemo, useState } from 'react';
import type { FrontendAdapter } from '../adapters/adapter';
import { AppShell } from '../components/AppShell';
import { StatusBanner } from '../components/StatusBanner';
import { ErrorState, LoadingState } from '../components/States';
import type { StudentAction, StudentSessionViewModel } from '../types/viewModels';
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
  EVALUATING: '等待回饋',
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

export function StudentPage({
  adapter,
  sessionId,
  speechClient: providedSpeechClient,
}: {
  readonly adapter: FrontendAdapter;
  readonly sessionId: string;
  readonly speechClient?: SpeechGatewayClient;
}) {
  const [view, setView] = useState<StudentSessionViewModel | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [speechError, setSpeechError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const speechClient = useMemo(
    () => providedSpeechClient || createSpeechGatewayClient(),
    [providedSpeechClient],
  );
  const [speechState, setSpeechState] = useState<SpeechState>(speechClient.state);

  useEffect(() => {
    const unsubscribe = speechClient.subscribe(setSpeechState);
    return () => {
      unsubscribe();
      speechClient.dispose();
    };
  }, [speechClient]);

  function load() {
    setError(null);
    setView(null);
    void adapter.getStudentSession(sessionId).then(setView).catch(setError);
  }

  useEffect(load, [adapter, sessionId]);

  async function playPrompt() {
    setBusy(true);
    setError(null);
    setSpeechError(null);
    try {
      const nextView = await adapter.submitStudentAction(sessionId, 'listen');
      setView(nextView);
      // Keep the controls available during playback so starting a recording
      // can cancel TTS, as required by the half-duplex boundary.
      setBusy(false);
      await speechClient.play(promptToUtterance(nextView.prompt));
    } catch (nextError) {
      setSpeechError(nextError);
    } finally {
      setBusy(false);
    }
  }

  async function toggleAnswer() {
    setSpeechError(null);
    if (speechState === 'LISTENING') {
      setBusy(true);
      try {
        const transcript = await speechClient.stopRecording();
        const nextView = await adapter.submitStudentAnswer(sessionId, {
          schema_version: '0.1.0',
          transcript: transcript.text,
          input_mode: 'voice',
          asr_device: transcript.device,
        });
        setView(nextView);
        speechClient.markEvaluationComplete();
      } catch (nextError) {
        await speechClient.cancel();
        setSpeechError(nextError);
      } finally {
        setBusy(false);
      }
      return;
    }

    setBusy(true);
    try {
      await speechClient.startRecording('nan-TW');
    } catch (nextError) {
      setSpeechError(nextError);
    } finally {
      setBusy(false);
    }
  }

  async function control(action: Exclude<StudentAction, 'listen' | 'answer'>) {
    setBusy(true);
    setError(null);
    setSpeechError(null);
    try {
      await speechClient.cancel();
      setView(await adapter.submitStudentAction(sessionId, action));
    } catch (nextError) {
      setError(nextError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell currentLabel="學生模式">
      <main id="main-content" className="page" tabIndex={-1} aria-busy={busy}>
        <p className="eyebrow">學生模式 · {sessionId}</p>
        {!view && !error ? <LoadingState label="載入學生活動……" /> : null}
        {error ? <ErrorState error={error} onRetry={load} /> : null}
        {speechError ? <ErrorState error={speechError} /> : null}
        {view ? (
          <>
            <StatusBanner health={view.health} />
            <section className="card student-card" aria-labelledby="student-heading">
              <div className="progress-line"><span>{view.progressLabel}</span><span>{view.progressValue}%</span></div>
              <div className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={view.progressValue} aria-label="教學進度">
                <span style={{ width: `${view.progressValue}%` }} />
              </div>
              <h1 id="student-heading">{view.lessonTitle}</h1>
              <p className="prompt">{view.prompt}</p>
              <p className="live-message" role="status" aria-live="polite">{view.feedback}</p>
              <p className="speech-status" role="status" aria-live="polite">
                語音狀態：{speechStateLabels[speechState]}
              </p>
              <div className="button-grid" aria-label="學生操作">
                <button className="button" type="button" disabled={busy || speechState === 'SPEAKING'} onClick={() => void playPrompt()}>播放提示</button>
                <button
                  className="button primary-large"
                  type="button"
                  disabled={busy || !view.canAnswer || speechState === 'TRANSCRIBING' || speechState === 'EVALUATING'}
                  onClick={() => void toggleAnswer()}
                >
                  {speechState === 'LISTENING' ? '停止錄音並轉錄' : '開始回答'}
                </button>
                <button className="button secondary" type="button" disabled={busy} onClick={() => void control('hint')}>取得提示</button>
                <button className="button secondary" type="button" disabled={busy || speechState === 'IDLE'} onClick={() => void control('pause')}>停止音訊／暫停</button>
              </div>
            </section>
            <section className="card mode-switch" aria-labelledby="switch-heading">
              <h2 id="switch-heading">切換檢視</h2>
              <p>切換模式前會停止播放與錄音；目前語音預設使用 Mock，設定 <code>VITE_SPEECH_MODE=real</code> 可改接 localhost Speech Gateway。</p>
              <button className="button secondary" type="button" onClick={() => navigateTo(`/session/${encodeURIComponent(sessionId)}/observer`)}>開啟教師／家長模式</button>
            </section>
          </>
        ) : null}
      </main>
    </AppShell>
  );
}
