export type AppRoute =
  | { readonly kind: 'setup' }
  | { readonly kind: 'health' }
  | { readonly kind: 'capture' }
  | { readonly kind: 'student'; readonly sessionId: string }
  | { readonly kind: 'observer'; readonly sessionId: string }
  | { readonly kind: 'not_found'; readonly path: string };

export function parseRoute(pathname: string): AppRoute {
  const path = pathname.replace(/\/+$/, '') || '/';
  if (path === '/' || path === '/setup') return { kind: 'setup' };
  if (path === '/health') return { kind: 'health' };
  if (path === '/capture') return { kind: 'capture' };
  const match = path.match(/^\/session\/([^/]+)\/(student|observer)$/);
  if (match) {
    return { kind: match[2] === 'student' ? 'student' : 'observer', sessionId: decodeURIComponent(match[1]) };
  }
  return { kind: 'not_found', path };
}

export function navigateTo(path: string): void {
  window.history.pushState({}, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}
