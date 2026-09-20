import { useEffect, useMemo, useState } from 'react';
import { createAdapter } from './adapters';
import { ErrorBoundary } from './components/ErrorBoundary';
import { navigateTo, parseRoute, type AppRoute } from './app/routing';
import { CapturePage } from './pages/CapturePage';
import { HealthPage } from './pages/HealthPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { ObserverPage } from './pages/ObserverPage';
import { SetupPage } from './pages/SetupPage';
import { StudentPage } from './pages/StudentPage';
import { NARRATION_FEATURE_ENABLED, NarrationProvider } from './accessibility/NarrationProvider';

export function App() {
  const adapter = useMemo(createAdapter, []);
  const [route, setRoute] = useState<AppRoute>(() => parseRoute(window.location.pathname));

  useEffect(() => {
    const onPopState = () => setRoute(parseRoute(window.location.pathname));
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    const titles: Record<AppRoute['kind'], string> = {
      setup: '首頁',
      health: '系統狀態',
      capture: '準備教材',
      student: '學生課程',
      observer: '教師／家長觀察',
      not_found: '找不到頁面',
    };
    document.title = `${titles[route.kind]}｜hear tAIgi`;
    if (!NARRATION_FEATURE_ENABLED) return;
    try {
      if (!window.localStorage.getItem('hear-our-language.accessibility-mode')) return;
    } catch {
      return;
    }
    const main = document.querySelector<HTMLElement>('#main-content');
    const pageTitle = main?.querySelector<HTMLElement>('[data-page-title]');
    (pageTitle || main)?.focus();
  }, [route]);

  let content;
  if (route.kind === 'setup') content = <SetupPage adapter={adapter} />;
  else if (route.kind === 'health') content = <HealthPage adapter={adapter} />;
  else if (route.kind === 'capture') content = <CapturePage adapter={adapter} />;
  else if (route.kind === 'student') content = <StudentPage adapter={adapter} sessionId={route.sessionId} />;
  else if (route.kind === 'observer') content = <ObserverPage adapter={adapter} sessionId={route.sessionId} />;
  else content = <NotFoundPage path={route.path} />;

  return <ErrorBoundary><NarrationProvider>{content}</NarrationProvider></ErrorBoundary>;
}

export { navigateTo };
