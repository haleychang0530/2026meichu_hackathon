import { useEffect, useState } from 'react';
import type { FrontendAdapter } from '../adapters/adapter';
import { AppShell } from '../components/AppShell';
import { StatusBanner } from '../components/StatusBanner';
import { ErrorState, LoadingState } from '../components/States';
import type { ObserverSessionViewModel } from '../types/viewModels';
import { navigateTo } from '../app/routing';

export function ObserverPage({ adapter, sessionId }: { readonly adapter: FrontendAdapter; readonly sessionId: string }) {
  const [view, setView] = useState<ObserverSessionViewModel | null>(null);
  const [error, setError] = useState<unknown>(null);

  function load() {
    setError(null);
    setView(null);
    void adapter.getObserverSession(sessionId).then(setView).catch(setError);
  }

  useEffect(load, [adapter, sessionId]);

  return (
    <AppShell currentLabel="教師／家長模式">
      <main id="main-content" className="page" tabIndex={-1}>
        <p className="eyebrow">教師／家長模式 · {sessionId}</p>
        {!view && !error ? <LoadingState label="載入觀察摘要……" /> : null}
        {error ? <ErrorState error={error} onRetry={load} /> : null}
        {view ? (
          <>
            <StatusBanner health={view.health} />
            <section className="card" aria-labelledby="observer-heading">
              <p className="eyebrow">同一個 server-side session</p>
              <h1 id="observer-heading">{view.lessonTitle}</h1>
              <dl className="detail-list">
                <div><dt>逐字稿</dt><dd>{view.transcript}</dd></div>
                <div><dt>判定</dt><dd>{view.evaluation}</dd></div>
                <div><dt>回饋</dt><dd>{view.feedback}</dd></div>
                <div><dt>進度</dt><dd>{view.progressLabel}</dd></div>
              </dl>
            </section>
            <div className="two-column">
              <section className="card" aria-labelledby="latency-heading">
                <h2 id="latency-heading">延遲與 fallback</h2>
                <dl className="detail-list compact">
                  <div><dt>ASR</dt><dd>{view.latencyMs.asr === null ? '尚未量測' : `${view.latencyMs.asr} ms`}</dd></div>
                  <div><dt>Backend</dt><dd>{view.latencyMs.backend === null ? '尚未量測' : `${view.latencyMs.backend} ms`}</dd></div>
                  <div><dt>Total</dt><dd>{view.latencyMs.total === null ? '尚未量測' : `${view.latencyMs.total} ms`}</dd></div>
                  <div><dt>Fallback</dt><dd>{view.fallbacks.length ? view.fallbacks.join('、') : '無'}</dd></div>
                </dl>
              </section>
              <section className="card" aria-labelledby="observer-actions-heading">
                <h2 id="observer-actions-heading">操作</h2>
                <p>教師／家長模式可觀察進度；答案、信心與教師欄位不會進入 student view。</p>
                <div className="button-row">
                  <button className="button" type="button" onClick={() => navigateTo(`/session/${encodeURIComponent(sessionId)}/student`)}>回到學生模式</button>
                  <button className="button secondary" type="button" onClick={load}>重新整理摘要</button>
                </div>
              </section>
            </div>
          </>
        ) : null}
      </main>
    </AppShell>
  );
}
