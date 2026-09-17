import { useEffect, useState } from 'react';
import type { FrontendAdapter } from '../adapters/adapter';
import { AppShell } from '../components/AppShell';
import { StatusBanner } from '../components/StatusBanner';
import { ErrorState, LoadingState } from '../components/States';
import type { StudentAction, StudentSessionViewModel } from '../types/viewModels';
import { navigateTo } from '../app/routing';

export function StudentPage({ adapter, sessionId }: { readonly adapter: FrontendAdapter; readonly sessionId: string }) {
  const [view, setView] = useState<StudentSessionViewModel | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    setError(null);
    setView(null);
    void adapter.getStudentSession(sessionId).then(setView).catch(setError);
  }

  useEffect(load, [adapter, sessionId]);

  async function act(action: StudentAction) {
    setBusy(true);
    setError(null);
    try {
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
              <div className="button-grid" aria-label="學生操作">
                <button className="button" type="button" disabled={busy} onClick={() => void act('listen')}>播放提示</button>
                <button className="button primary-large" type="button" disabled={busy || !view.canAnswer} onClick={() => void act('answer')}>開始／送出回答</button>
                <button className="button secondary" type="button" disabled={busy} onClick={() => void act('hint')}>取得提示</button>
                <button className="button secondary" type="button" disabled={busy} onClick={() => void act('pause')}>暫停</button>
              </div>
            </section>
            <section className="card mode-switch" aria-labelledby="switch-heading">
              <h2 id="switch-heading">切換檢視</h2>
              <p>Mock demo 的模式切換不會重設目前 session；正式版仍需先停止音訊再切換焦點。</p>
              <button className="button secondary" type="button" onClick={() => navigateTo(`/session/${encodeURIComponent(sessionId)}/observer`)}>開啟教師／家長模式</button>
            </section>
          </>
        ) : null}
      </main>
    </AppShell>
  );
}
