export type BrowserCheckStatus = 'unknown' | 'ready' | 'degraded' | 'offline';

export interface BrowserDeviceCheck {
  readonly camera: BrowserCheckStatus;
  readonly microphone: BrowserCheckStatus;
  readonly online: BrowserCheckStatus;
  readonly secureContext: BrowserCheckStatus;
  readonly cameraCount: number;
  readonly microphoneCount: number;
  readonly message: string;
  readonly checkedAt: string;
}

export function initialBrowserDeviceCheck(): BrowserDeviceCheck {
  return {
    camera: 'unknown',
    microphone: 'unknown',
    online: 'unknown',
    secureContext: 'unknown',
    cameraCount: 0,
    microphoneCount: 0,
    message: '尚未檢查相機與麥克風；按下檢查後才會請求瀏覽器權限。',
    checkedAt: new Date(0).toISOString(),
  };
}

function permissionFailureStatus(error: unknown): BrowserCheckStatus {
  if (error instanceof DOMException && error.name === 'NotFoundError') return 'offline';
  if (error instanceof DOMException && error.name === 'NotAllowedError') return 'degraded';
  return 'degraded';
}

export async function checkBrowserDevices(): Promise<BrowserDeviceCheck> {
  const checkedAt = new Date().toISOString();
  const online: BrowserCheckStatus = typeof navigator.onLine === 'boolean'
    ? (navigator.onLine ? 'ready' : 'degraded')
    : 'unknown';
  const secureContext: BrowserCheckStatus = window.isSecureContext || ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
    ? 'ready'
    : 'degraded';

  if (!navigator.mediaDevices?.getUserMedia || !navigator.mediaDevices.enumerateDevices) {
    return {
      camera: 'offline',
      microphone: 'offline',
      online,
      secureContext,
      cameraCount: 0,
      microphoneCount: 0,
      message: '此瀏覽器不支援相機／麥克風檢查；可使用鍵盤與離線素材完成展示。',
      checkedAt,
    };
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    stream.getTracks().forEach((track) => track.stop());
  } catch (error) {
    const status = permissionFailureStatus(error);
    const devices = await navigator.mediaDevices.enumerateDevices().catch(() => []);
    const cameraCount = devices.filter((device) => device.kind === 'videoinput').length;
    const microphoneCount = devices.filter((device) => device.kind === 'audioinput').length;
    return {
      camera: cameraCount > 0 ? status : 'offline',
      microphone: microphoneCount > 0 ? status : 'offline',
      online,
      secureContext,
      cameraCount,
      microphoneCount,
      message: status === 'degraded'
        ? '瀏覽器拒絕或暫時無法使用媒體權限；不保存任何影像或錄音。'
        : '找不到可用的相機或麥克風；可使用檔案上傳與鍵盤備援。',
      checkedAt,
    };
  }

  const devices = await navigator.mediaDevices.enumerateDevices();
  const cameraCount = devices.filter((device) => device.kind === 'videoinput').length;
  const microphoneCount = devices.filter((device) => device.kind === 'audioinput').length;
  return {
    camera: cameraCount > 0 ? 'ready' : 'offline',
    microphone: microphoneCount > 0 ? 'ready' : 'offline',
    online,
    secureContext,
    cameraCount,
    microphoneCount,
    message: cameraCount > 0 && microphoneCount > 0
      ? '相機與麥克風能力檢查完成；測試串流已立即停止且未保存。'
      : '只找到部分媒體裝置；可使用鍵盤、檔案上傳或預錄音訊備援。',
    checkedAt,
  };
}
