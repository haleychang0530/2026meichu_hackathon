import type { operations } from '../generated/api';

export type GimbalResult = operations['observeGimbal']['responses'][200]['content']['application/json'];

const coreBaseUrl = (import.meta.env.VITE_CORE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');

async function command(path: string, image?: Blob, signal?: AbortSignal): Promise<GimbalResult> {
  const body = image ? new FormData() : undefined;
  if (body && image) body.append('image', image, 'preview.jpg');
  const request = new AbortController();
  const cancel = () => request.abort();
  signal?.addEventListener('abort', cancel, { once: true });
  const timeout = window.setTimeout(cancel, path === 'start' ? 30_000 : 8_000);
  let response: Response;
  try {
    response = await fetch(`${coreBaseUrl}/api/gimbal/${path}`, { method: 'POST', body, signal: request.signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    if (request.signal.aborted) throw new Error('雲台服務逾時；可手動拍照。');
    throw new Error('無法連線本機 Core API；請確認後端已啟動。');
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener('abort', cancel);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { message?: string } | null;
    throw new Error(payload?.message || `雲台服務回覆 HTTP ${response.status}`);
  }
  return response.json() as Promise<GimbalResult>;
}

export const gimbalClient = {
  start: (signal?: AbortSignal) => command('start', undefined, signal),
  observe: (image: Blob, signal?: AbortSignal) => command('observe', image, signal),
  test: (signal?: AbortSignal) => command('test', undefined, signal),
  stop: () => command('stop'),
};

export function previewFrame(video: HTMLVideoElement): Promise<Blob> {
  if (!video.videoWidth || !video.videoHeight) {
    return Promise.reject(new Error('相機畫面尚未就緒。'));
  }
  const canvas = document.createElement('canvas');
  const scale = Math.min(1, 640 / video.videoWidth);
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  const context = canvas.getContext('2d');
  if (!context) return Promise.reject(new Error('無法讀取預覽畫面。'));
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('無法擷取預覽影格。'));
    }, 'image/jpeg', 0.7);
  });
}
