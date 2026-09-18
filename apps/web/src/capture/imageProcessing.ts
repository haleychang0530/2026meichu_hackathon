import type { CaptureAsset, ImageQualityMetrics, LessonImageUpload } from '../types/viewModels';
import {
  assessImageQuality,
  DEFAULT_IMAGE_LIMITS,
  isSupportedImageType,
  type ImageQualityLimits,
} from './imageQuality';
import type { ImageQualityIssueCode } from '../types/viewModels';

export interface CropRect {
  /** Normalized coordinates in the decoded image. */
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface ImageProcessingOptions {
  readonly crop?: CropRect;
  readonly limits?: ImageQualityLimits;
  readonly jpegQuality?: number;
  readonly fileName?: string;
}

export class ImageProcessingError extends Error {
  readonly code: ImageQualityIssueCode | 'decode_failed' | 'compression_failed';

  constructor(
    code: ImageQualityIssueCode | 'decode_failed' | 'compression_failed',
    message: string,
    options?: { readonly cause?: unknown },
  ) {
    super(message, options);
    this.name = 'ImageProcessingError';
    this.code = code;
  }
}

interface DecodedImage {
  readonly width: number;
  readonly height: number;
  readonly source: CanvasImageSource;
  readonly close: () => void;
}

const FULL_IMAGE_CROP: CropRect = { x: 0, y: 0, width: 1, height: 1 };

export function normalizeCropRect(crop: CropRect = FULL_IMAGE_CROP): CropRect {
  const x = Math.min(1, Math.max(0, crop.x));
  const y = Math.min(1, Math.max(0, crop.y));
  const width = Math.min(1 - x, Math.max(0.01, crop.width));
  const height = Math.min(1 - y, Math.max(0.01, crop.height));
  return { x, y, width, height };
}

export function calculateOutputSize(
  sourceWidth: number,
  sourceHeight: number,
  crop: CropRect = FULL_IMAGE_CROP,
  maxDimension = DEFAULT_IMAGE_LIMITS.maxDimension,
): { readonly width: number; readonly height: number } {
  const normalized = normalizeCropRect(crop);
  const cropWidth = Math.max(1, Math.round(sourceWidth * normalized.width));
  const cropHeight = Math.max(1, Math.round(sourceHeight * normalized.height));
  const scale = Math.min(1, maxDimension / Math.max(cropWidth, cropHeight));
  return {
    width: Math.max(1, Math.round(cropWidth * scale)),
    height: Math.max(1, Math.round(cropHeight * scale)),
  };
}

function inferMimeType(source: Blob): string {
  const declared = source.type.toLowerCase();
  if (declared) return declared;
  const name = typeof (source as Blob & { readonly name?: unknown }).name === 'string'
    ? String((source as Blob & { readonly name?: unknown }).name).toLowerCase()
    : '';
  if (name.endsWith('.jpg') || name.endsWith('.jpeg')) return 'image/jpeg';
  if (name.endsWith('.png')) return 'image/png';
  if (name.endsWith('.webp')) return 'image/webp';
  return declared;
}

function baseFileName(source: Blob, requestedName?: string): string {
  const rawName = requestedName
    || (typeof (source as Blob & { readonly name?: unknown }).name === 'string'
      ? String((source as Blob & { readonly name?: unknown }).name)
      : 'lesson');
  const withoutPath = rawName.split(/[\\/]/).pop() || 'lesson';
  const stem = withoutPath.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
  return `${stem || 'lesson'}.jpg`;
}

async function decodeImage(source: Blob): Promise<DecodedImage> {
  if (typeof createImageBitmap === 'function') {
    try {
      // Drawing an orientation-aware bitmap onto a canvas removes EXIF while
      // preserving the visual orientation of the page.
      const bitmap = await createImageBitmap(source, { imageOrientation: 'from-image' });
      return {
        width: bitmap.width,
        height: bitmap.height,
        source: bitmap,
        close: () => bitmap.close(),
      };
    } catch {
      // Some browsers expose createImageBitmap but not the orientation option.
      // Fall through to the HTMLImageElement path.
    }
  }

  if (typeof URL === 'undefined' || typeof Image === 'undefined') {
    throw new ImageProcessingError('decode_failed', '目前瀏覽器無法讀取這張圖片。');
  }

  const objectUrl = URL.createObjectURL(source);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const element = new Image();
      element.onload = () => resolve(element);
      element.onerror = () => reject(new Error('image decode failed'));
      element.src = objectUrl;
    });
    return {
      width: image.naturalWidth || image.width,
      height: image.naturalHeight || image.height,
      source: image,
      close: () => URL.revokeObjectURL(objectUrl),
    };
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    throw new ImageProcessingError('decode_failed', '無法讀取這張圖片，請換一張教材照片。', { cause: error });
  }
}

function renderCrop(
  decoded: DecodedImage,
  crop: CropRect,
  width: number,
  height: number,
): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) throw new ImageProcessingError('compression_failed', '瀏覽器無法準備圖片上傳。');
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = 'high';
  const sourceX = Math.round(decoded.width * crop.x);
  const sourceY = Math.round(decoded.height * crop.y);
  const sourceWidth = Math.max(1, Math.round(decoded.width * crop.width));
  const sourceHeight = Math.max(1, Math.round(decoded.height * crop.height));
  context.drawImage(decoded.source, sourceX, sourceY, sourceWidth, sourceHeight, 0, 0, width, height);
  return canvas;
}

function canvasToBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new ImageProcessingError('compression_failed', '瀏覽器無法壓縮這張圖片。'));
    }, 'image/jpeg', quality);
  });
}

/** Sample enough pixels for a responsive quality check without retaining the source image. */
export function measureImageDataQuality(imageData: ImageData): ImageQualityMetrics {
  const { data, width, height } = imageData;
  const pixelCount = width * height;
  if (pixelCount === 0) return { meanLuminance: 0, darkPixelRatio: 1, brightPixelRatio: 0, sharpness: 0 };

  const step = Math.max(1, Math.ceil(Math.sqrt(pixelCount / 25_000)));
  let samples = 0;
  let luminanceSum = 0;
  let darkPixels = 0;
  let brightPixels = 0;
  let edgeSum = 0;
  let edgeSquaredSum = 0;
  let edgeSamples = 0;
  const lumaAt = (x: number, y: number): number => {
    const offset = (y * width + x) * 4;
    return 0.2126 * data[offset] + 0.7152 * data[offset + 1] + 0.0722 * data[offset + 2];
  };

  for (let y = 0; y < height; y += step) {
    for (let x = 0; x < width; x += step) {
      const luminance = lumaAt(x, y);
      samples += 1;
      luminanceSum += luminance;
      if (luminance < 40) darkPixels += 1;
      if (luminance > 225) brightPixels += 1;
      if (x > 0 && y > 0) {
        const edge = Math.abs(luminance - lumaAt(x - 1, y)) + Math.abs(luminance - lumaAt(x, y - 1));
        edgeSum += edge;
        edgeSquaredSum += edge * edge;
        edgeSamples += 1;
      }
    }
  }

  const edgeMean = edgeSamples ? edgeSum / edgeSamples : 0;
  const edgeVariance = edgeSamples ? Math.max(0, edgeSquaredSum / edgeSamples - edgeMean * edgeMean) : 0;
  return {
    meanLuminance: luminanceSum / samples,
    darkPixelRatio: darkPixels / samples,
    brightPixelRatio: brightPixels / samples,
    sharpness: edgeVariance,
  };
}

export async function captureVideoFrame(video: HTMLVideoElement): Promise<Blob> {
  if (!video.videoWidth || !video.videoHeight) {
    throw new ImageProcessingError('decode_failed', '相機尚未準備好，請稍候再拍照。');
  }
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const context = canvas.getContext('2d');
  if (!context) throw new ImageProcessingError('compression_failed', '瀏覽器無法擷取相機畫面。');
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvasToBlob(canvas, 0.94);
}

export async function prepareImageForUpload(
  source: Blob,
  options: ImageProcessingOptions = {},
): Promise<CaptureAsset> {
  const limits = options.limits ?? DEFAULT_IMAGE_LIMITS;
  const mimeType = inferMimeType(source);
  if (!isSupportedImageType(mimeType)) {
    throw new ImageProcessingError('unsupported_type', '請選擇 JPG、PNG 或 WebP 圖片。');
  }
  if (source.size > limits.maxInputBytes) {
    throw new ImageProcessingError('file_too_large', '原始圖片超過 20 MB，請先縮小圖片再上傳。');
  }

  const decoded = await decodeImage(source);
  try {
    const crop = normalizeCropRect(options.crop);
    const initialSize = calculateOutputSize(decoded.width, decoded.height, crop, limits.maxDimension);
    const jpegQuality = Math.min(0.95, Math.max(0.45, options.jpegQuality ?? 0.88));
    let scale = 1;
    let quality = jpegQuality;
    let outputBlob: Blob | null = null;
    let outputSize = initialSize;

    for (let attempt = 0; attempt < 10; attempt += 1) {
      outputSize = {
        width: Math.max(1, Math.round(initialSize.width * scale)),
        height: Math.max(1, Math.round(initialSize.height * scale)),
      };
      const canvas = renderCrop(decoded, crop, outputSize.width, outputSize.height);
      outputBlob = await canvasToBlob(canvas, quality);
      if (outputBlob.size <= limits.maxUploadBytes) break;
      if (quality > 0.52) {
        quality = Math.max(0.52, quality - 0.12);
      } else {
        scale *= 0.82;
        quality = jpegQuality;
      }
      outputBlob = null;
    }

    if (!outputBlob || outputBlob.size > limits.maxUploadBytes) {
      throw new ImageProcessingError('file_too_large', '圖片壓縮後仍太大，請改用較近距離或較小的照片。');
    }

    const qualityCanvas = renderCrop(decoded, crop, outputSize.width, outputSize.height);
    const qualityContext = qualityCanvas.getContext('2d');
    const metrics = qualityContext
      ? measureImageDataQuality(qualityContext.getImageData(0, 0, outputSize.width, outputSize.height))
      : undefined;
    const qualityReport = assessImageQuality({
      mimeType: 'image/jpeg',
      bytes: outputBlob.size,
      width: outputSize.width,
      height: outputSize.height,
      metrics,
    }, limits);
    const previewUrl = URL.createObjectURL(outputBlob);
    const upload: LessonImageUpload = {
      blob: outputBlob,
      fileName: baseFileName(source, options.fileName),
      mimeType: 'image/jpeg',
      width: outputSize.width,
      height: outputSize.height,
      sourceBytes: source.size,
      quality: qualityReport,
    };
    return { ...upload, previewUrl };
  } finally {
    decoded.close();
  }
}

export function releaseCaptureAsset(asset: CaptureAsset | null): void {
  if (!asset || typeof URL === 'undefined') return;
  URL.revokeObjectURL(asset.previewUrl);
}
