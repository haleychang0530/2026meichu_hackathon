import { Component, type ErrorInfo, type ReactNode } from 'react';

interface ErrorBoundaryProps { readonly children: ReactNode }
interface ErrorBoundaryState { readonly error: Error | null }

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('frontend-error-boundary', { code: 'FRONTEND_RENDER_ERROR', message: error.message, componentStack: info.componentStack });
  }

  render() {
    if (this.state.error) {
      return (
        <main className="page narrow" role="alert">
          <p className="eyebrow">FRONTEND_RENDER_ERROR</p>
          <h1>畫面需要重新載入</h1>
          <p>{this.state.error.message}</p>
          <button className="button" type="button" onClick={() => window.location.reload()}>重新載入</button>
        </main>
      );
    }
    return this.props.children;
  }
}
