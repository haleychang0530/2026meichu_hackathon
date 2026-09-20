import { useId } from 'react';
import { asAdapterError } from '../adapters/errors';

export function LoadingState({ label = '資料載入中……' }: { readonly label?: string }) {
  return <p className="loading-state" role="status" aria-live="polite">{label}</p>;
}

export function ErrorState({
  error,
  onRetry,
  showTechnicalDetails = true,
}: {
  readonly error: unknown;
  readonly onRetry?: () => void;
  readonly showTechnicalDetails?: boolean;
}) {
  // Each rendered error region needs a unique name when multiple failures are visible together.
  const errorHeadingId = useId();
  const normalized = asAdapterError(error);
  return (
    <section className="error-state" role="alert" aria-labelledby={errorHeadingId}>
      <h2 id={errorHeadingId}>目前無法完成這個步驟</h2>
      <p>{normalized.message}</p>
      {showTechnicalDetails ? (
        <p className="error-meta">錯誤碼：{normalized.code}；fallback：{normalized.fallback || 'none'}</p>
      ) : null}
      {onRetry ? <button className="button secondary" type="button" onClick={onRetry}>重試</button> : null}
    </section>
  );
}

export function EmptyState({ message }: { readonly message: string }) {
  return <p className="empty-state" role="status">{message}</p>;
}
