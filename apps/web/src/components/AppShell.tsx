import type { ReactNode, MouseEvent } from 'react';
import { navigateTo } from '../app/routing';

interface AppShellProps {
  readonly children: ReactNode;
  readonly currentLabel: string;
}

function handleInternalLink(event: MouseEvent<HTMLAnchorElement>, path: string): void {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  navigateTo(path);
}

export function AppShell({ children, currentLabel }: AppShellProps) {
  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/setup" onClick={(event) => handleInternalLink(event, '/setup')}>
          聽見母語
        </a>
        <nav aria-label="主要導覽">
          <a href="/setup" onClick={(event) => handleInternalLink(event, '/setup')}>設定</a>
          <a href="/capture" onClick={(event) => handleInternalLink(event, '/capture')}>教材</a>
          <span aria-current="page">{currentLabel}</span>
        </nav>
      </header>
      {children}
      <footer className="site-footer">Mock mode · server-side session remains the future source of truth</footer>
    </div>
  );
}
