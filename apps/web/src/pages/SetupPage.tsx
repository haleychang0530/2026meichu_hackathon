import { useEffect, useState } from 'react';
import type { FrontendAdapter } from '../adapters/adapter';
import { AppShell } from '../components/AppShell';
import { StatusBanner } from '../components/StatusBanner';
import { ErrorState, LoadingState } from '../components/States';
import type { SetupViewModel } from '../types/viewModels';
import { navigateTo } from '../app/routing';

export function SetupPage({ adapter }: { readonly adapter: FrontendAdapter }) {
  const [view, setView] = useState<SetupViewModel | null>(null);
  const [error, setError] = useState<unknown>(null);

  function load() {
    setError(null);
    setView(null);
    void adapter.getSetup().then(setView).catch(setError);
  }

  useEffect(load, [adapter]);

  return (
    <AppShell currentLabel="設定">
      <main id="main-content" className="page" tabIndex={-1}>
        <p className="eyebrow">STAGE 02 · MOCK FRONTEND</p>
        <h1 data-page-title tabIndex={-1}>先聽見，再一起說</h1>
        <p className="lead">這個 Mock flow 先驗證學生與教師／家長兩種操作路徑；真正的 server-side session 仍由 Core Backend 提供。</p>
        {!view && !error ? <LoadingState /> : null}
        {error ? <ErrorState error={error} onRetry={load} /> : null}
        {view ? (
          <>
            <StatusBanner health={view.health} />
            <section className="card callout" aria-labelledby="setup-heading">
              <h2 id="setup-heading">{view.title}</h2>
              <p>{view.description}</p>
              <div className="button-row">
                <button className="button" type="button" onClick={() => navigateTo(view.nextRoute)}>選擇教材</button>
                <button className="button secondary" type="button" onClick={() => navigateTo('/session/demo-session/student')}>直接進入學生 Mock</button>
              </div>
            </section>
            <section className="card" aria-labelledby="state-heading">
              <h2 id="state-heading">狀態展示</h2>
              <p>可在網址加上 <code>?health=degraded</code>、<code>?health=offline</code> 或 <code>?health=recoverable_error</code> 驗證降級畫面。</p>
            </section>
          </>
        ) : null}
      </main>
    </AppShell>
  );
}
