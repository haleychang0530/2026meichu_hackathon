import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import type { CaptureAsset } from '../types/viewModels';
import { formatBytes, qualityStatusLabel } from './imageQuality';
import {
  captureVideoFrame,
  ImageProcessingError,
  prepareImageForUpload,
  releaseCaptureAsset,
} from './imageProcessing';
import type { CropRect } from './imageProcessing';
import { gimbalClient, previewFrame } from './gimbalClient';
import type { GimbalResult } from './gimbalClient';

interface CameraOption {
  readonly deviceId: string;
  readonly label: string;
}

export interface CameraCaptureProps {
  readonly disabled?: boolean;
  readonly onImageSelected: (asset: CaptureAsset | null) => void;
  /** Increment after an upload attempt so the short-lived preview is released. */
  readonly resetToken?: number;
}

type CameraStatus = 'idle' | 'starting' | 'ready' | 'permission_denied' | 'unavailable' | 'error';
type ImageSource = 'camera' | 'file';
type AlignmentStatus = 'idle' | 'starting' | 'testing' | 'aligning' | 'ready' | 'failed';
type PageBox = NonNullable<GimbalResult['box']>;

function targetLabel(box: PageBox): string {
  if (box.target === 'tablet') return '平板';
  if (box.target === 'paper' || (box.source === 'contour' && !box.target)) return '紙張';
  return '課本';
}

function cropDetectedBox(box: PageBox | null, crop?: CropRect): PageBox | null {
  if (!box || !crop) return box;
  const left = Math.max(box.x, crop.x);
  const top = Math.max(box.y, crop.y);
  const right = Math.min(box.x + box.width, crop.x + crop.width);
  const bottom = Math.min(box.y + box.height, crop.y + crop.height);
  if (right <= left || bottom <= top) return null;
  return {
    ...box,
    x: (left - crop.x) / crop.width,
    y: (top - crop.y) / crop.height,
    width: (right - left) / crop.width,
    height: (bottom - top) / crop.height,
  };
}

function mediaDevicesAvailable(): boolean {
  return typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia);
}

function cameraErrorMessage(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
      return '相機權限被拒絕；你仍可以用「上傳現有教材」從檔案上傳。';
    }
    if (error.name === 'NotFoundError' || error.name === 'OverconstrainedError') {
      return '找不到可用相機；請確認相機已連接，或改用上傳現有教材。';
    }
    if (error.name === 'NotReadableError') {
      return '相機目前被其他程式使用；請關閉其他視訊或會議視窗後再試。';
    }
  }
  return '相機目前無法使用；你仍可以用上傳現有教材。';
}

function processingErrorMessage(error: unknown): string {
  if (error instanceof ImageProcessingError) return error.message;
  if (error instanceof Error) return error.message;
  return '圖片處理失敗，請重新拍攝或選擇另一張圖片。';
}

export function CameraCapture({ disabled = false, onImageSelected, resetToken }: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const operationRef = useRef(0);
  const processingOperationRef = useRef(0);
  const mountedRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pendingAssetRef = useRef<CaptureAsset | null>(null);
  const pendingSourceRef = useRef<ImageSource | null>(null);
  const resetTokenRef = useRef(resetToken);
  const alignmentRunRef = useRef(0);
  const alignmentAbortRef = useRef<AbortController | null>(null);
  const gimbalRequestedRef = useRef(false);
  const pendingStopRef = useRef<Promise<void> | null>(null);
  const [devices, setDevices] = useState<readonly CameraOption[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [cameraStatus, setCameraStatus] = useState<CameraStatus>('idle');
  const [cameraMessage, setCameraMessage] = useState('按下「開始預覽」後，瀏覽器才會申請相機權限。');
  const [pendingAsset, setPendingAsset] = useState<CaptureAsset | null>(null);
  const [pendingBox, setPendingBox] = useState<PageBox | null>(null);
  const [qualityOverride, setQualityOverride] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [processingMessage, setProcessingMessage] = useState('');
  const [cropPreset, setCropPreset] = useState<'full' | 'inset'>('full');
  const [alignmentStatus, setAlignmentStatus] = useState<AlignmentStatus>('idle');
  const [alignmentMessage, setAlignmentMessage] = useState('');
  const [alignmentResult, setAlignmentResult] = useState<GimbalResult | null>(null);
  const [lastAck, setLastAck] = useState<number | null>(null);

  const endAlignment = useCallback(async () => {
    alignmentRunRef.current += 1;
    alignmentAbortRef.current?.abort();
    alignmentAbortRef.current = null;
    if (gimbalRequestedRef.current) {
      gimbalRequestedRef.current = false;
      const stopping = gimbalClient.stop().then(() => undefined).catch(() => undefined);
      pendingStopRef.current = stopping;
      await stopping;
      if (pendingStopRef.current === stopping) pendingStopRef.current = null;
    } else if (pendingStopRef.current) {
      await pendingStopRef.current;
    }
  }, []);

  const stopPreview = useCallback(() => {
    void endAlignment();
    setAlignmentStatus('idle');
    setAlignmentResult(null);
    operationRef.current += 1;
    const stream = streamRef.current;
    streamRef.current = null;
    stream?.getTracks().forEach((track) => track.stop());
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraStatus('idle');
    setCameraMessage('預覽已停止；需要拍照時可重新開始預覽，也可以上傳現有教材。');
  }, [endAlignment]);

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    const allDevices = await navigator.mediaDevices.enumerateDevices();
    const cameras = allDevices
      .filter((device) => device.kind === 'videoinput')
      .map((device, index) => ({
        deviceId: device.deviceId,
        label: device.label || `Camera ${index + 1}`,
      }));
    setDevices(cameras);
    if (!selectedDeviceId && cameras[0]) setSelectedDeviceId(cameras[0].deviceId);
  }, [selectedDeviceId]);

  const startPreview = useCallback(async (deviceId?: string) => {
    await endAlignment();
    setAlignmentStatus('idle');
    setAlignmentResult(null);
    if (!mediaDevicesAvailable()) {
      setCameraStatus('unavailable');
      setCameraMessage('此瀏覽器沒有可用的相機介面；請使用檔案上傳。');
      return;
    }

    const operation = operationRef.current + 1;
    operationRef.current = operation;
    const previousStream = streamRef.current;
    streamRef.current = null;
    previousStream?.getTracks().forEach((track) => track.stop());
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraStatus('starting');
    setCameraMessage('正在申請相機權限……');

    const videoConstraints: MediaTrackConstraints = {
      width: { ideal: 1920 },
      height: { ideal: 1080 },
    };
    if (deviceId) videoConstraints.deviceId = { exact: deviceId };
    else videoConstraints.facingMode = { ideal: 'environment' };

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: videoConstraints, audio: false });
      if (operationRef.current !== operation) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      if (operationRef.current !== operation) {
        stream.getTracks().forEach((track) => track.stop());
        if (videoRef.current?.srcObject === stream) videoRef.current.srcObject = null;
        return;
      }
      setCameraStatus('ready');
      setCameraMessage('相機已就緒。按「自動尋找紙張／課本／平板」讓雲台小幅調整，再按拍照。');
      await refreshDevices();
      const actualDeviceId = stream.getVideoTracks()[0]?.getSettings().deviceId;
      if (actualDeviceId) setSelectedDeviceId(actualDeviceId);
    } catch (error) {
      if (operationRef.current !== operation) return;
      const stream = streamRef.current;
      streamRef.current = null;
      stream?.getTracks().forEach((track) => track.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
      setCameraStatus(error instanceof DOMException && (error.name === 'NotAllowedError' || error.name === 'SecurityError')
        ? 'permission_denied'
        : 'error');
      setCameraMessage(cameraErrorMessage(error));
    }
  }, [endAlignment, refreshDevices]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      operationRef.current += 1;
      processingOperationRef.current += 1;
      void endAlignment();
      const stream = streamRef.current;
      stream?.getTracks().forEach((track) => track.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
      releaseCaptureAsset(pendingAssetRef.current);
    };
  }, [endAlignment]);

  useEffect(() => {
    if (resetToken === undefined || resetToken === resetTokenRef.current) return;
    resetTokenRef.current = resetToken;
    stopPreview();
    releaseCaptureAsset(pendingAssetRef.current);
    pendingAssetRef.current = null;
    pendingSourceRef.current = null;
    setPendingAsset(null);
    setPendingBox(null);
    setQualityOverride(false);
    setProcessingMessage('分析工作已結束，預覽影像已清除；如需再試請重新拍攝或上傳現有教材。');
    onImageSelected(null);
  }, [onImageSelected, resetToken, stopPreview]);

  function replacePendingAsset(asset: CaptureAsset, source: ImageSource, box: PageBox | null): void {
    releaseCaptureAsset(pendingAsset);
    pendingAssetRef.current = asset;
    pendingSourceRef.current = source;
    setPendingAsset(asset);
    setPendingBox(box);
    setQualityOverride(false);
    setProcessingMessage('');
    onImageSelected(null);
  }

  async function prepareSource(source: Blob, origin: ImageSource, fileName?: string, crop?: CropRect, box: PageBox | null = null): Promise<void> {
    if (!crop) setCropPreset('full');
    // A new processing attempt invalidates any previously accepted asset so
    // CapturePage cannot submit an older image while this one is being prepared.
    onImageSelected(null);
    const processingOperation = processingOperationRef.current + 1;
    processingOperationRef.current = processingOperation;
    setProcessing(true);
    setProcessingMessage('正在校正方向、移除 EXIF 並壓縮圖片……');
    try {
      const asset = await prepareImageForUpload(source, { fileName, crop });
      if (!mountedRef.current || processingOperationRef.current !== processingOperation) {
        releaseCaptureAsset(asset);
        return;
      }
      replacePendingAsset(asset, origin, box);
    } catch (error) {
      if (mountedRef.current && processingOperationRef.current === processingOperation) {
        setProcessingMessage(processingErrorMessage(error));
      }
    } finally {
      if (mountedRef.current && processingOperationRef.current === processingOperation) setProcessing(false);
    }
  }

  async function startAlignment(): Promise<void> {
    if (cameraStatus !== 'ready' || !videoRef.current) return;
    setAlignmentStatus('starting');
    await endAlignment();
    if (!streamRef.current || !videoRef.current) return;
    const run = alignmentRunRef.current + 1;
    alignmentRunRef.current = run;
    const abort = new AbortController();
    alignmentAbortRef.current = abort;
    setAlignmentResult(null);
    setLastAck(null);
    setAlignmentStatus('starting');
    setAlignmentMessage('正在連線 ESP32 與本機視覺模型……');
    try {
      gimbalRequestedRef.current = true;
      const started = await gimbalClient.start(abort.signal);
      if (alignmentRunRef.current !== run) return;
      setAlignmentResult(started);
      setLastAck(started.sequence ?? null);
      setAlignmentStatus('testing');
      setAlignmentMessage('ESP32 收到測試指令，雲台正在上下左右小幅移動。');
      const tested = await gimbalClient.test(abort.signal);
      if (alignmentRunRef.current !== run) return;
      setAlignmentResult(tested);
      setLastAck(tested.sequence ?? null);
      setAlignmentStatus('aligning');
      for (let attempt = 0; attempt < 18; attempt += 1) {
        const video = videoRef.current;
        if (!video || alignmentRunRef.current !== run) return;
        const frame = await previewFrame(video);
        const result = await gimbalClient.observe(frame, abort.signal);
        if (alignmentRunRef.current !== run) return;
        setAlignmentResult(result);
        if (result.sequence != null) setLastAck(result.sequence);
        setAlignmentMessage(result.message);
        if (result.state === 'ready') {
          setAlignmentStatus('ready');
          return;
        }
        if (result.state === 'limit' || result.state === 'not_found') {
          setAlignmentStatus('failed');
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 350));
      }
      if (alignmentRunRef.current === run) {
        setAlignmentStatus('failed');
        setAlignmentMessage('對準時間已到；可以手動拍照，或調整紙張後重新對準。');
      }
    } catch (error) {
      if (alignmentRunRef.current !== run || abort.signal.aborted) return;
      setAlignmentStatus('failed');
      setAlignmentMessage(error instanceof Error ? error.message : '雲台對準失敗；可以手動拍照。');
    } finally {
      if (alignmentRunRef.current === run) alignmentAbortRef.current = null;
    }
  }

  async function capturePhoto(): Promise<void> {
    if (!videoRef.current || cameraStatus !== 'ready') return;
    const detectedBox = alignmentResult?.box ?? null;
    await endAlignment();
    if (!videoRef.current || cameraStatus !== 'ready') return;
    setProcessingMessage('');
    try {
      const frame = await captureVideoFrame(videoRef.current);
      if (!mountedRef.current) return;
      await prepareSource(frame, 'camera', 'camera-capture', undefined, detectedBox);
    } catch (error) {
      if (mountedRef.current) setProcessingMessage(processingErrorMessage(error));
    } finally {
      if (mountedRef.current) stopPreview();
    }
  }

  function recropPendingAsset(preset: 'full' | 'inset'): void {
    const source = pendingAssetRef.current?.blob;
    if (!source || processing) return;
    setCropPreset(preset);
    const crop: CropRect | undefined = preset === 'inset'
      ? { x: 0.03, y: 0.03, width: 0.94, height: 0.94 }
      : undefined;
    void prepareSource(source, pendingSourceRef.current || 'file', pendingAssetRef.current?.fileName, crop, cropDetectedBox(pendingBox, crop));
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>): void {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    stopPreview();
    setProcessingMessage('');
    void prepareSource(file, 'file', file.name);
  }

  function clearPendingAsset(): void {
    releaseCaptureAsset(pendingAsset);
    pendingAssetRef.current = null;
    pendingSourceRef.current = null;
    setPendingAsset(null);
    setPendingBox(null);
    setQualityOverride(false);
    setProcessingMessage('已清除照片，可以重新拍攝或上傳現有教材。');
    onImageSelected(null);
  }

  function acceptPendingAsset(): void {
    if (!pendingAsset || pendingAsset.quality.status === 'rejected') return;
    if (pendingAsset.quality.status === 'warning' && !qualityOverride) return;
    onImageSelected(pendingAsset);
    setProcessingMessage('照片已準備好；按下「開始分析教材」開始教材理解。');
  }

  const hasCamera = cameraStatus === 'ready' || cameraStatus === 'starting';
  const canAccept = pendingAsset
    && pendingAsset.quality.status !== 'rejected'
    && (pendingAsset.quality.status === 'good' || qualityOverride);

  return (
    <section className="card camera-card" aria-labelledby="camera-heading">
      <p className="eyebrow">01 · 拍攝或選擇教材</p>
      <h2 id="camera-heading">拍攝或選擇一頁教材</h2>
      <p>
        照片只會先送到筆電上的 Core Backend；前端不直接連線到 MI300。分析完成後由後端依隱私政策清除暫存影像。
      </p>
      <p className="camera-status" role="status" aria-live="polite">{cameraMessage}</p>
      {processingMessage ? <p className="camera-status" role="status" aria-live="polite">{processingMessage}</p> : null}

      <div className="camera-controls camera-preview-action" aria-label="教材來源操作">
        <button
          className="button"
          type="button"
          disabled={disabled}
          onClick={() => {
            if (hasCamera) stopPreview();
            else void startPreview(selectedDeviceId || undefined);
          }}
        >
          {hasCamera ? '停止預覽' : '開始預覽'}
        </button>
        <label className="button secondary file-button">
          上傳現有教材
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            disabled={disabled || processing}
            onChange={handleFileChange}
          />
        </label>
      </div>

      <div className="camera-preview-wrap">
        {hasCamera ? (
          <div className="camera-video-layer">
            <video
              ref={videoRef}
              className="camera-preview"
              playsInline
              muted
              aria-label="教材相機即時預覽"
            />
            {alignmentResult?.box ? (
              <div
                className={`gimbal-page-box ${alignmentResult.box.source === 'model' ? 'model' : 'contour'}`}
                style={{
                  left: `${alignmentResult.box.x * 100}%`,
                  top: `${alignmentResult.box.y * 100}%`,
                  width: `${alignmentResult.box.width * 100}%`,
                  height: `${alignmentResult.box.height * 100}%`,
                }}
                aria-hidden="true"
              />
            ) : null}
          </div>
        ) : (
          <div className="camera-placeholder" role="img" aria-label="尚未開始相機預覽">
            <strong>尚未開始預覽</strong>
            <span>也可以直接上傳預先拍好的教材圖片。</span>
          </div>
        )}
      </div>

      {cameraStatus === 'ready' ? (
        <>
          <p className="camera-status" role="status" aria-live="polite">
            {alignmentMessage || '先自動尋找紙張／課本／平板，再拍照。'}
            {alignmentResult?.pan != null && alignmentResult.tilt != null
              ? `（Z 軸 ${alignmentResult.pan}°、仰角 ${alignmentResult.tilt}°）`
              : ''}
            {lastAck != null ? ` ESP ACK #${lastAck}。` : ''}
            {alignmentResult?.box ? ` 已辨識${targetLabel(alignmentResult.box)}；來源：${alignmentResult.box.source === 'model' ? '輕量模型' : '輪廓判斷'}（${Math.round(alignmentResult.box.confidence * 100)}%）。` : ''}
          </p>
          <div className="camera-controls" aria-label="拍照操作">
            <button
              className="button"
              type="button"
              disabled={disabled || processing || alignmentStatus === 'starting' || alignmentStatus === 'testing' || alignmentStatus === 'aligning'}
              onClick={() => void startAlignment()}
            >
              {alignmentStatus === 'ready' || alignmentStatus === 'failed' ? '重新對準' : '自動尋找紙張／課本／平板'}
            </button>
            <button
              className="button"
              type="button"
              disabled={disabled || processing || !['ready', 'failed'].includes(alignmentStatus)}
              onClick={() => void capturePhoto()}
            >
              拍照
            </button>
          </div>
        </>
      ) : null}

      <div className="camera-device-row">
        <label htmlFor="camera-device">切換相機</label>
        <select
          id="camera-device"
          value={selectedDeviceId}
          disabled={disabled || devices.length < 2 || processing}
          onChange={(event) => {
            setSelectedDeviceId(event.target.value);
            void startPreview(event.target.value);
          }}
        >
          {devices.length === 0 ? <option value="">啟動預覽後列出相機</option> : null}
          {devices.map((device) => <option key={device.deviceId} value={device.deviceId}>{device.label}</option>)}
        </select>
      </div>

      {cameraStatus === 'permission_denied' || cameraStatus === 'unavailable' || cameraStatus === 'error' ? (
        <p className="camera-fallback" role="alert">相機不可用不會阻擋流程；請使用上方的檔案上傳備援。</p>
      ) : null}

      {pendingAsset ? (
        <section className="photo-review" aria-labelledby="photo-review-heading">
          <h3 id="photo-review-heading">檢查照片後再送出</h3>
          <div className="photo-review-grid">
            <div className="photo-preview-column">
              <div
                className="photo-preview-frame"
                style={{ maxWidth: `${24 * pendingAsset.width / pendingAsset.height}rem` }}
              >
                <img className="photo-preview" src={pendingAsset.previewUrl} alt="教材照片預覽，尚未送出分析" />
                {pendingBox ? (
                  <div
                    className="gimbal-page-box"
                    style={{
                      left: `${pendingBox.x * 100}%`,
                      top: `${pendingBox.y * 100}%`,
                      width: `${pendingBox.width * 100}%`,
                      height: `${pendingBox.height * 100}%`,
                    }}
                    aria-hidden="true"
                  />
                ) : null}
              </div>
              {pendingBox ? (
                <p className="photo-detection-caption">
                  已辨識{targetLabel(pendingBox)} · {pendingBox.source === 'model' ? '輕量模型' : '輪廓判斷'}（{Math.round(pendingBox.confidence * 100)}%）
                </p>
              ) : null}
            </div>
            <div>
              <p className={`quality-summary quality-${pendingAsset.quality.status}`} role="status">
                <strong>{qualityStatusLabel(pendingAsset.quality.status)}</strong>
                <br />{pendingAsset.width} × {pendingAsset.height} · {formatBytes(pendingAsset.blob.size)}
              </p>
              {pendingAsset.quality.issues.length ? (
                <ul className="quality-issues">
                  {pendingAsset.quality.issues.map((issue) => (
                    <li key={issue.code}>
                      <strong>{issue.message}</strong><br />{issue.suggestion}
                    </li>
                  ))}
                </ul>
              ) : <p>方向已校正，EXIF 已移除，且圖片已限制在可上傳大小內。</p>}
            </div>
          </div>
          {pendingAsset.quality.status === 'warning' ? (
            <label className="quality-override">
              <input type="checkbox" checked={qualityOverride} onChange={(event) => setQualityOverride(event.target.checked)} />
              我已確認文字仍可閱讀，仍要使用這張照片
            </label>
          ) : null}
          <div className="crop-control">
            <label htmlFor="crop-preset">裁切方式</label>
            <select
              id="crop-preset"
              value={cropPreset}
              disabled={disabled || processing}
              onChange={(event) => recropPendingAsset(event.target.value as 'full' | 'inset')}
            >
              <option value="full">保留完整頁面（建議）</option>
              <option value="inset">裁切四周 3% 空白邊界</option>
            </select>
            <span>完整頁面預設可避免裁掉台羅與小字；裁切後仍會重新檢查解析度。</span>
          </div>
          <div className="button-row">
            <button className="button" type="button" disabled={disabled || !canAccept} onClick={acceptPendingAsset}>
              {pendingAsset.quality.status === 'warning' ? '仍要使用此照片' : '使用此照片'}
            </button>
            <button className="button secondary" type="button" disabled={disabled || processing} onClick={clearPendingAsset}>
              重拍／重新選擇
            </button>
          </div>
        </section>
      ) : null}

      <p className="camera-note">若拒絕相機權限，檔案上傳仍可完成；取消或離開頁面時，相機串流與預覽網址會自動釋放。</p>
    </section>
  );
}
