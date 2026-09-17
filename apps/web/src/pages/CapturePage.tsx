import { useEffect, useState } from 'react';
import type { FrontendAdapter } from '../adapters/adapter';
import { AppShell } from '../components/AppShell';
import { StatusBanner } from '../components/StatusBanner';
import { ErrorState, LoadingState } from '../components/States';
import type { CaptureViewModel } from '../types/viewModels';
import { navigateTo } from '../app/routing';

export function CapturePage({ adapter }: { readonly adapter: FrontendAdapter }) {
  const [view, setView] = useState<CaptureViewModel | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    setError(null);
    setView(null);
    void adapter.getCapture().then(setView).catch(setError);
  }

  useEffect(load, [adapter]);

  async function confirmLesson() {
    if (!view) return;
    setBusy(true);
    setError(null);
    try {
      const result = await adapter.confirmLesson(view.lessonId);
      navigateTo(`/session/${encodeURIComponent(result.sessionId)}/student`);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell currentLabel="教材">
      <main id="main-content" className="page" tabIndex={-1}>
        <p className="eyebrow">教材確認</p>
        <h1>選擇一頁教材</h1>
        {!view && !error ? <LoadingState label="載入合成教材……" /> : null}
        {error ? <ErrorState error={error} onRetry={load} /> : null}
        {view ? (
          <>
            <StatusBanner health={view.health} />
            <section className="card" aria-labelledby="lesson-heading">
              <p className="eyebrow">{view.reviewStatus === 'pending' ? '待確認' : view.reviewStatus}</p>
              <h2 id="lesson-heading">{view.title}</h2>
              <p>{view.description}</p>
              <div className="image-grid">
                {view.images.map((image) => (
                  <figure className="lesson-card" key={image.src}>
                    <img src={image.src} alt={image.alt} />
                    <figcaption>{image.label}</figcaption>
                  </figure>
                ))}
              </div>
              <div className="button-row">
                <button className="button" type="button" disabled={busy} onClick={confirmLesson}>
                  {busy ? '建立 session……' : '確認教材並開始'}
                </button>
                <button className="button secondary" type="button" onClick={() => navigateTo('/setup')}>返回設定</button>
              </div>
            </section>
          </>
        ) : null}
      </main>
    </AppShell>
  );
}
