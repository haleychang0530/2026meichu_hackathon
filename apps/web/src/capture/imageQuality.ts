import type {
  ImageQualityIssue,
  ImageQualityMetrics,
  ImageQualityReport,
  ImageQualityStatus,
  ImageQualityIssueCode,
} from '../types/viewModels';

export const SUPPORTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'] as const;

export interface ImageQualityLimits {
  /** Maximum size accepted before browser-side decoding. */
  readonly maxInputBytes: number;
  /** Maximum size of the bounded, compressed upload sent to Core Backend. */
  readonly maxUploadBytes: number;
  readonly minWidth: number;
  readonly minHeight: number;
  readonly maxDimension: number;
}

export const DEFAULT_IMAGE_LIMITS: ImageQualityLimits = {
  maxInputBytes: 20 * 1024 * 1024,
  maxUploadBytes: 8 * 1024 * 1024,
  minWidth: 640,
  minHeight: 480,
  maxDimension: 4096,
};

export interface ImageQualityInput {
  readonly mimeType: string;
  readonly bytes: number;
  readonly width: number;
  readonly height: number;
  readonly metrics?: ImageQualityMetrics;
}

const ISSUE_COPY: Record<ImageQualityIssueCode, { readonly message: string; readonly suggestion: string }> = {
  unsupported_type: {
    message: '這個檔案格式不能用來分析教材。',
    suggestion: '請選擇 JPG、PNG 或 WebP 圖片。',
  },
  file_too_large: {
    message: '圖片檔案太大，無法安全上傳。',
    suggestion: '請改用較小的圖片，或讓系統重新壓縮後再試一次。',
  },
  resolution_too_low: {
    message: '照片解析度太低，台羅或小字可能無法辨識。',
    suggestion: '請把課本移近、保持整頁平整，再重新拍攝。',
  },
  too_blurry: {
    message: '影像可能模糊。',
    suggestion: '請固定課本與相機，等對焦完成後再拍一次。',
  },
  too_dark: {
    message: '影像可能太暗。',
    suggestion: '請增加正面光線，並避開課本上的陰影。',
  },
  too_bright: {
    message: '影像可能過亮或有反光。',
    suggestion: '請稍微傾斜課本或移動光源，避免反光蓋住文字。',
  },
};

function addIssue(
  issues: ImageQualityIssue[],
  code: ImageQualityIssueCode,
  severity: ImageQualityIssue['severity'],
): void {
  issues.push({ code, severity, ...ISSUE_COPY[code] });
}

function statusFor(issues: readonly ImageQualityIssue[]): ImageQualityStatus {
  if (issues.some((issue) => issue.severity === 'blocking')) return 'rejected';
  return issues.length > 0 ? 'warning' : 'good';
}

export function isSupportedImageType(mimeType: string): boolean {
  return (SUPPORTED_IMAGE_TYPES as readonly string[]).includes(mimeType.toLowerCase());
}

/**
 * Validate the image after it has been decoded and bounded. Resolution and
 * transport limits are blocking; blur/exposure are actionable warnings that a
 * teacher may explicitly override. Core Backend still performs its own check.
 */
export function assessImageQuality(
  input: ImageQualityInput,
  limits: ImageQualityLimits = DEFAULT_IMAGE_LIMITS,
): ImageQualityReport {
  const issues: ImageQualityIssue[] = [];
  const mimeType = input.mimeType.toLowerCase();

  if (!isSupportedImageType(mimeType)) addIssue(issues, 'unsupported_type', 'blocking');
  if (input.bytes > limits.maxUploadBytes) addIssue(issues, 'file_too_large', 'blocking');
  if (input.width < limits.minWidth || input.height < limits.minHeight) {
    addIssue(issues, 'resolution_too_low', 'blocking');
  }

  if (input.metrics) {
    if (input.metrics.sharpness < 18) addIssue(issues, 'too_blurry', 'warning');
    if (input.metrics.meanLuminance < 48 || input.metrics.darkPixelRatio >= 0.45) {
      addIssue(issues, 'too_dark', 'warning');
    }
    if (input.metrics.meanLuminance > 218 || input.metrics.brightPixelRatio >= 0.45) {
      addIssue(issues, 'too_bright', 'warning');
    }
  }

  return {
    status: statusFor(issues),
    width: input.width,
    height: input.height,
    bytes: input.bytes,
    mimeType,
    issues,
    metrics: input.metrics,
  };
}

export function hasBlockingQualityIssue(report: ImageQualityReport): boolean {
  return report.status === 'rejected';
}

export function qualityStatusLabel(status: ImageQualityStatus): string {
  if (status === 'good') return '影像品質良好';
  if (status === 'warning') return '影像可以使用，但建議改善';
  return '影像需要重新準備';
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}
