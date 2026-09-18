import { useEffect, useRef, useState } from 'react';
import type { FrontendAdapter } from '../adapters/adapter';
import { AdapterError } from '../adapters/errors';
import { AppShell } from '../components/AppShell';
import { StatusBanner } from '../components/StatusBanner';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { CameraCapture } from '../capture/CameraCapture';
import { formatBytes, qualityStatusLabel } from '../capture/imageQuality';
import type { CaptureAsset, CaptureViewModel } from '../types/viewModels';
import { navigateTo } from '../app/routing';

const ANALYSIS_TIMEOUT_MS = 30_000;
type AnalysisStatus = 'idle' | 'uploading' | 'complete' | 'cancelled' | 'timed_out';

function providerModeMessage(mode: CaptureViewModel['providerMode']): string {
  if (mode === 'real') return '教材分析完成；Core Backend 已回傳即時分析結果。';
  if (mode === 'fixture-fallback') return 'MI300 暫時不可用；Core Backend 已回傳明確標示的 fixture fallback。';
  if (mode === 'fixture') return '目前使用明確標示的離線合成教材；這不是即時 VLM 分析結果。';
  return '目前使用前端 Mock 教材流程。';
}

export function CapturePage({ adapter }: { readonly adapter: FrontendAdapter }) {
  const [view, setView] = useState<CaptureViewModel | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [selectedImage, setSelectedImage] = useState<CaptureAsset | null>(null);
  const [analysisStatus, setAnalysisStatus] = useState<AnalysisStatus>('idle');
  const [analysisError, setAnalysisError] = useState<unknown>(null);
  const [analysisMessage, setAnalysisMessage] = useState('');
  const [cameraResetToken, setCameraResetToken] = useState(0);
  const analysisAbortRef = useRef<AbortController | null>(null);
  const timeoutRef = useRef<number | null>(null);
  const timedOutRef = useRef(false);

  function load() {
    setError(null);
    setView(null);
    void adapter.getCapture().then(setView).catch(setError);
  }

  useEffect(load, [adapter]);

  useEffect(() => () => {
    analysisAbortRef.current?.abort();
    if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current);
  }, []);

  function handleImageSelected(asset: CaptureAsset | null): void {
    setSelectedImage(asset);
    setAnalysisStatus('idle');
    setAnalysisError(null);
    setAnalysisMessage(asset ? '照片已準備好，請確認後送出。' : '');
  }

  async function useFixture(): Promise<void> {
    setError(null);
    setAnalysisError(null);
    setAnalysisMessage('正在載入明確標示的離線合成教材……');
    try {
      const fixture = await adapter.getCaptureFallback();
      setView(fixture);
      setAnalysisStatus('idle');
      setAnalysisMessage('目前使用離線合成教材；這不是即時 VLM 分析結果。');
    } catch (nextError) {
      setError(nextError);
      setAnalysisMessage('離線合成教材也無法載入。');
    }
  }

  async function analyzeSelectedImage(): Promise<void> {
    if (!selectedImage || analysisStatus === 'uploading') return;
    const imageToAnalyze = selectedImage;
    const controller = new AbortController();
    analysisAbortRef.current = controller;
    timedOutRef.current = false;
    setAnalysisStatus('uploading');
    setAnalysisError(null);
    setAnalysisMessage('正在送到筆電 Core Backend；影像品質與 VLM 回應仍會由後端再次驗證……');
    timeoutRef.current = window.setTimeout(() => {
      timedOutRef.current = true;
      controller.abort();
    }, ANALYSIS_TIMEOUT_MS);

    try {
      const result = await adapter.analyzeLesson(imageToAnalyze, controller.signal);
      if (controller.signal.aborted) return;
      setView(result);
      setAnalysisStatus('complete');
      setAnalysisMessage(providerModeMessage(result.providerMode));
    } catch (nextError) {
      if (controller.signal.aborted) {
        if (timedOutRef.current) {
          setAnalysisStatus('timed_out');
          setAnalysisError(new AdapterError({
            code: 'VLM_TIMEOUT',
            message: '教材分析逾時，沒有建立新的 lesson。你可以重試，或改用離線合成教材。',
            retryable: true,
            fallback: 'fixture_mode',
            request_id: null,
          }));
          setAnalysisMessage('分析逾時；照片仍只保留在本頁，尚未建立新的 lesson。');
        } else {
          setAnalysisStatus('cancelled');
          setAnalysisError(null);
          setAnalysisMessage('已取消教材分析，沒有建立新的 lesson。');
        }
      } else {
        setAnalysisStatus('idle');
        setAnalysisError(nextError);
        setAnalysisMessage('教材分析失敗；可以重試或切換到離線合成教材。');
      }
    } finally {
      if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
      if (analysisAbortRef.current === controller) analysisAbortRef.current = null;
      setSelectedImage(null);
      setCameraResetToken((token) => token + 1);
    }
  }

  function cancelAnalysis(): void {
    if (analysisStatus !== 'uploading') return;
    setAnalysisMessage('正在取消教材分析……');
    analysisAbortRef.current?.abort();
  }

  async function confirmLesson() {
    if (!view) return;
    setBusy(true);
    setError(null);
    try {
      const result = await adapter.confirmLesson(view.lessonId);
      navigateTo(`/session/${encodeURIComponent(result.sessionId)}/student`);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell currentLabel="教材">
      <main id="main-content" className="page" tabIndex={-1}>
        <p className="eyebrow">STAGE 03 · 教材擷取</p>
        <h1>選擇一頁教材</h1>
        {!view && !error ? <LoadingState label="載入教材入口……" /> : null}
        {error ? (
          <>
            <ErrorState error={error} onRetry={load} />
            <section className="card callout" aria-labelledby="offline-heading">
              <h2 id="offline-heading">先使用離線合成教材</h2>
              <p>Core Backend 尚未回應時，可以先用明確標示的 fixture 驗證鍵盤與雙模式流程。</p>
              <button className="button" type="button" onClick={() => void useFixture()}>使用離線合成教材</button>
            </section>
          </>
        ) : null}

        <CameraCapture
          disabled={analysisStatus === 'uploading'}
          onImageSelected={handleImageSelected}
          resetToken={cameraResetToken}
        />

        <section className="card" aria-labelledby="analysis-heading">
          <p className="eyebrow">Core Backend 唯一產品入口</p>
          <h2 id="analysis-heading">送出教材分析</h2>
          <p>送出前會在瀏覽器完成方向校正、EXIF 清理、有界壓縮與品質提示；Core Backend 完成驗證後才會呼叫後續 VLM。</p>
          {selectedImage ? (
            <p className="selected-upload" role="status">
              已選擇 {selectedImage.width} × {selectedImage.height} 的教材照片（{formatBytes(selectedImage.blob.size)}）；{qualityStatusLabel(selectedImage.quality.status)}。
            </p>
          ) : (
            <EmptyState message="請先在上方按「使用此照片」，再送出教材分析。" />
          )}
          {analysisMessage ? <p className="live-message" role="status" aria-live="polite">{analysisMessage}</p> : null}
          {analysisStatus === 'uploading' ? (
            <progress className="analysis-progress" aria-label="教材分析進度" />
          ) : null}
          <div className="button-row">
            <button
              className="button primary-large"
              type="button"
              disabled={!selectedImage || selectedImage.quality.status === 'rejected' || analysisStatus === 'uploading'}
              onClick={() => void analyzeSelectedImage()}
            >
              {analysisStatus === 'uploading' ? '分析中……' : '送至 Core Backend 分析'}
            </button>
            {analysisStatus === 'uploading' ? (
              <button className="button secondary" type="button" onClick={cancelAnalysis}>取消分析</button>
            ) : null}
          </div>
          {analysisError ? (
            <>
              <ErrorState
                error={analysisError}
                onRetry={() => {
                  setAnalysisError(null);
                  setAnalysisMessage('請重新拍攝或選擇教材圖片後再試。');
                }}
              />
              <button className="button secondary" type="button" onClick={() => void useFixture()}>改用離線合成教材</button>
            </>
          ) : null}
        </section>

        {view ? (
          <>
            <StatusBanner health={view.health} />
            <section className="card" aria-labelledby="lesson-heading">
              <p className="eyebrow">{view.reviewStatus === 'pending' ? '待確認' : view.reviewStatus}</p>
              <h2 id="lesson-heading">{view.title}</h2>
              <p>{view.description}</p>
              {view.images.length ? (
                <div className="image-grid">
                  {view.images.map((image) => (
                    <figure className="lesson-card" key={image.src}>
                      <img src={image.src} alt={image.alt} />
                      <figcaption>{image.label}</figcaption>
                    </figure>
                  ))}
                </div>
              ) : (
                <EmptyState message={view.canConfirm
                  ? '目前沒有可預覽的圖片，仍可使用這份教材建立 session。'
                  : '目前沒有可預覽的圖片；Core session 建立會在 Agent A Stage 08 接上。'} />
              )}
              <p className="analysis-provider" role="status">
                分析來源：{view.providerMode === 'real'
                  ? 'Core Backend real'
                  : view.providerMode === 'fixture-fallback'
                    ? 'Core Backend fixture fallback'
                    : view.providerMode === 'fixture'
                      ? 'Core Backend fixture'
                      : '前端 Mock'}
              </p>
              <div className="button-row">
                <button className="button" type="button" disabled={busy || !view.canConfirm} onClick={confirmLesson}>
                  {busy ? '建立 session……' : view.canConfirm ? '確認教材並開始' : '等待 Core session API'}
                </button>
                <button className="button secondary" type="button" onClick={() => navigateTo('/setup')}>返回設定</button>
              </div>
            </section>
          </>
        ) : null}
      </main>
    </AppShell>
  );
}
