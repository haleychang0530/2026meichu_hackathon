import { useEffect, useMemo, useState } from 'react';
import type { FrontendAdapter } from '../adapters/adapter';
import { AppShell } from '../components/AppShell';
import { ErrorState, LoadingState } from '../components/States';
import { StatusBanner } from '../components/StatusBanner';
import { navigateTo } from '../app/routing';
import {
  checkBrowserDevices,
  initialBrowserDeviceCheck,
  type BrowserCheckStatus,
  type BrowserDeviceCheck,
} from '../health/deviceReadiness';
import type { HealthStatus, SetupViewModel } from '../types/viewModels';

const statusLabels: Record<BrowserCheckStatus | HealthStatus, string> = {
  unknown: '尚未檢查',
  ready: '就緒',
  degraded: '降級運作',
  offline: '離線',
  recoverable_error: '可恢復錯誤',
};

interface CheckRow {
  readonly label: string;
  readonly status: BrowserCheckStatus | HealthStatus;
  readonly detail: string;
}

function CheckList({ rows }: { readonly rows: readonly CheckRow[] }) {
  return (
    <ul className="health-check-list">
      {rows.map((row) => (
        <li className={`health-check health-check-${row.status}`} key={row.label}>
          <span className="health-check-label">{row.label}</span>
          <strong>{statusLabels[row.status]}</strong>
          <span>{row.detail}</span>
        </li>
      ))}
    </ul>
  );
}

function serviceDetail(service: SetupViewModel['health']['services'][number]): string {
  const parts = [`裝置：${service.device}`];
  if (service.modelRevision) parts.push(`模型：${service.modelRevision}`);
  if (service.queueDepth !== undefined) parts.push(`佇列：${service.queueDepth}`);
  if (service.lastError) parts.push(service.lastError);
  return parts.join('；');
}

export function HealthPage({ adapter }: { readonly adapter: FrontendAdapter }) {
  const isMockRuntime = import.meta.env.VITE_DATA_MODE !== 'real';
  const [view, setView] = useState<SetupViewModel | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [deviceCheck, setDeviceCheck] = useState<BrowserDeviceCheck>(initialBrowserDeviceCheck);
  const [checkingDevices, setCheckingDevices] = useState(false);

  function load() {
    setError(null);
    setView(null);
    void adapter.getSetup().then(setView).catch(setError);
  }

  useEffect(load, [adapter]);

  async function runDeviceCheck(): Promise<void> {
    setCheckingDevices(true);
    try {
      setDeviceCheck(await checkBrowserDevices());
    } finally {
      setCheckingDevices(false);
    }
  }

  const serviceRows = useMemo<readonly CheckRow[]>(() => {
    if (!view) return [];
    return view.health.services.map((service) => ({
      label: service.service,
      status: service.status,
      detail: serviceDetail(service),
    }));
  }, [view]);

  const browserRows: readonly CheckRow[] = [
    { label: '相機', status: deviceCheck.camera, detail: deviceCheck.cameraCount ? `${deviceCheck.cameraCount} 個裝置` : '不讀取影像內容' },
    { label: '麥克風', status: deviceCheck.microphone, detail: deviceCheck.microphoneCount ? `${deviceCheck.microphoneCount} 個裝置` : '不保存錄音內容' },
    { label: '瀏覽器網路', status: deviceCheck.online, detail: 'localhost demo 可在網路中斷時使用 fixture/鍵盤備援' },
    { label: '安全媒體環境', status: deviceCheck.secureContext, detail: 'localhost 可使用瀏覽器媒體權限' },
  ];

  return (
    <AppShell currentLabel="系統狀態">
      <main id="main-content" className="page" tabIndex={-1}>
        <p className="eyebrow">STAGE 10 · RELEASE GATE</p>
        <h1 data-page-title tabIndex={-1}>展示健康檢查</h1>
        <p className="lead">一鍵展示前先確認筆電 Core、RAG、Speech、前端與外部 VLM 狀態；這裡只顯示健康 metadata，不會保存相機影像或學生錄音。</p>
        {!view && !error ? <LoadingState /> : null}
        {error ? <ErrorState error={error} onRetry={load} /> : null}
        {view ? (
          <>
            <StatusBanner health={view.health} />
            <section className="card" aria-labelledby="release-profile-heading">
              <h2 id="release-profile-heading">Release profile</h2>
              {isMockRuntime ? (
                <p className="runtime-note" role="status" aria-live="polite">
                  Mock adapter 已啟用：以下服務狀態是本機展示模擬，MI300 不會被呼叫；要驗證實際 Core／MI300 health，請用 real profile 啟動器。
                </p>
              ) : null}
              <CheckList rows={serviceRows} />
              <p className="runtime-note" role="status" aria-live="polite">
                CPU-only profile：ASR 與 TTS 使用筆電 CPU；NPU 是 disabled／未啟用狀態，不是本次 release gate。MI300 只由 Core Backend 透過內部 VLM contract 呼叫，瀏覽器不會直連。
              </p>
            </section>
            <section className="card" aria-labelledby="browser-check-heading">
              <h2 id="browser-check-heading">Camera／Mic 與瀏覽器能力</h2>
              <p>{deviceCheck.message}</p>
              <CheckList rows={browserRows} />
              <p className="form-help">上次檢查：{deviceCheck.checkedAt === new Date(0).toISOString() ? '尚未檢查' : new Date(deviceCheck.checkedAt).toLocaleString('zh-TW')}</p>
              <div className="button-row">
                <button className="button" type="button" onClick={() => void runDeviceCheck()} disabled={checkingDevices}>
                  {checkingDevices ? '檢查中……' : '檢查相機與麥克風'}
                </button>
                <button className="button secondary" type="button" onClick={load}>重新檢查服務</button>
              </div>
            </section>
            <section className="card" aria-labelledby="release-flow-heading">
              <h2 id="release-flow-heading">展示流程</h2>
              <p>啟動器會先檢查服務；操作者可從這裡直接進入正常、降級或 observer 流程。</p>
              <div className="button-grid release-actions">
                <button className="button" type="button" onClick={() => navigateTo('/setup')}>回到展示首頁</button>
                <button className="button secondary" type="button" onClick={() => navigateTo('/capture')}>拍攝／選擇教材</button>
                <button className="button secondary" type="button" onClick={() => navigateTo('/session/demo-session/student')}>學生模式</button>
                <button className="button secondary" type="button" onClick={() => navigateTo('/session/demo-session/observer')}>教師／家長 observer</button>
              </div>
            </section>
            <section className="card" aria-labelledby="fallback-heading">
              <h2 id="fallback-heading">故障備援話術</h2>
              <ul>
                <li>MI300 或 Core 不可用：使用明確標示的 cached lesson／fixture，不宣稱即時分析。</li>
                <li>ASR 不可用：切換鍵盤輸入；TTS 不可用：使用 App 旁白、螢幕閱讀器或核可預錄音檔。</li>
                <li>相機／麥克風被拒絕：使用檔案上傳、鍵盤與預錄素材完成展示。</li>
              </ul>
            </section>
          </>
        ) : null}
      </main>
    </AppShell>
  );
}
