import { AppShell } from '../components/AppShell';
import { navigateTo } from '../app/routing';

export function NotFoundPage({ path }: { readonly path: string }) {
  return (
    <AppShell currentLabel="找不到頁面">
      <main className="page narrow" tabIndex={-1}>
        <p className="eyebrow">404</p>
        <h1 data-page-title tabIndex={-1}>找不到這個頁面</h1>
        <p>目前路徑：<code>{path}</code></p>
        <button className="button" type="button" onClick={() => navigateTo('/setup')}>回到設定</button>
      </main>
    </AppShell>
  );
}
