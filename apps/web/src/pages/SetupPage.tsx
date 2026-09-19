import { useEffect, useState } from 'react';
import type { FrontendAdapter } from '../adapters/adapter';
import { AppShell } from '../components/AppShell';
import { ErrorState, LoadingState } from '../components/States';
import type { SetupViewModel } from '../types/viewModels';
import { navigateTo } from '../app/routing';
import logoLarge from '../assets/logo_large.png';

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
    <AppShell currentLabel="首頁">
      <main id="main-content" className="page home-page" tabIndex={-1}>
        <section className="home-hero" aria-labelledby="home-heading">
          <div className="hero-copy">
            <p className="eyebrow">一頁教材，一段有聲的學習旅程</p>
            <h1 id="home-heading" data-page-title tabIndex={-1}>讓一頁台語教材，<br />變成可以聽、可以說的課程</h1>
            <p className="lead">把課文、圖片和活動轉成適合聽與說的教學，讓每個孩子都能用自己的節奏學習母語。</p>
            <div className="button-row">
              <button className="button primary-large" type="button" onClick={() => navigateTo('/capture')}>準備一頁教材 <span aria-hidden="true">→</span></button>
              {import.meta.env.VITE_DATA_MODE !== 'real' ? <button className="button secondary primary-large" type="button" onClick={() => navigateTo('/session/demo-session/student')}>體驗範例課程</button> : null}
            </div>
          </div>
          <div className="hero-art"><div className="hero-logo" role="img" aria-label="hear tAIgi 產品標誌" style={{ maskImage: `url(${logoLarge})`, WebkitMaskImage: `url(${logoLarge})` }} /></div>
        </section>
        {!view && !error ? <LoadingState /> : null}
        {error ? <ErrorState error={error} onRetry={load} /> : null}
        {view ? (
          <>
            <section className="home-steps" aria-label="使用步驟">
              <ol>
                <li className="step-card"><h2><span className="step-number">01</span> 準備教材</h2><p>拍下或選擇一頁教材，檢查影像是否清楚。</p></li>
                <li className="step-card"><h2><span className="step-number">02</span> 一起確認</h2><p>由教師或家長確認課文和適合的活動。</p></li>
                <li className="step-card"><h2><span className="step-number">03</span> 開始聽說</h2><p>孩子聽課文、回答問題，再收到清楚的回饋。</p></li>
              </ol>
            </section>
            <p className="home-note">{view.health.status === 'ready' ? '系統已準備好。' : '部分服務暫時無法使用；你可以查看系統狀態或使用範例課程。'}</p>
          </>
        ) : null}
      </main>
    </AppShell>
  );
}
