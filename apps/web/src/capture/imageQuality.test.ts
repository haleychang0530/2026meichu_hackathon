import { describe, expect, it } from 'vitest';
import { assessImageQuality, DEFAULT_IMAGE_LIMITS } from './imageQuality';

const baseInput = {
  mimeType: 'image/jpeg',
  bytes: 120_000,
  width: 1280,
  height: 720,
};

describe('assessImageQuality', () => {
  it('rejects unsupported files and dimensions that cannot preserve small text', () => {
    const report = assessImageQuality({
      ...baseInput,
      mimeType: 'image/gif',
      width: 320,
      height: 240,
    });

    expect(report.status).toBe('rejected');
    expect(report.issues.map((issue) => issue.code)).toEqual([
      'unsupported_type',
      'resolution_too_low',
    ]);
  });

  it('reports actionable blur and exposure warnings without blocking an explicit override', () => {
    const report = assessImageQuality({
      ...baseInput,
      metrics: {
        meanLuminance: 235,
        darkPixelRatio: 0,
        brightPixelRatio: 0.6,
        sharpness: 4,
      },
    });

    expect(report.status).toBe('warning');
    expect(report.issues.map((issue) => issue.code)).toEqual(['too_blurry', 'too_bright']);
    expect(report.issues.every((issue) => issue.severity === 'warning')).toBe(true);
  });

  it('accepts a bounded, well-exposed image', () => {
    const report = assessImageQuality({
      ...baseInput,
      bytes: DEFAULT_IMAGE_LIMITS.maxUploadBytes,
      metrics: {
        meanLuminance: 132,
        darkPixelRatio: 0.08,
        brightPixelRatio: 0.05,
        sharpness: 42,
      },
    });

    expect(report.status).toBe('good');
    expect(report.issues).toHaveLength(0);
  });
});
