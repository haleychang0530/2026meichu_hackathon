import type { HealthSummaryView, HealthStatus } from '../types/viewModels';

const labels: Record<HealthStatus, string> = {
  ready: '就緒',
  degraded: '降級運作',
  offline: '離線',
  recoverable_error: '可恢復錯誤',
};

export function StatusBanner({ health }: { readonly health: HealthSummaryView }) {
  return (
    <section className={`status-banner status-${health.status}`} aria-labelledby="health-heading" role="region">
      <div>
        <p className="eyebrow">目前服務狀態</p>
        <h2 id="health-heading">{labels[health.status]}</h2>
        <p role="status" aria-live="polite">檢查時間：{new Date(health.checkedAt).toLocaleString('zh-TW')}</p>
      </div>
      <ul className="service-list">
        {health.services.map((service) => (
          <li key={service.service}>
            <strong>{service.service}</strong>：{labels[service.status]}（裝置：{service.device}）
            {service.modelRevision ? `；模型：${service.modelRevision}` : null}
            {service.queueDepth === undefined ? null : `；佇列：${service.queueDepth}`}
            {service.lastError ? <span className="service-error">；{service.lastError}</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
