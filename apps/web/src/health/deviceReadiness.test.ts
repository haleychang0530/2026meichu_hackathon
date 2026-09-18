import { describe, expect, it } from 'vitest';
import { initialBrowserDeviceCheck } from './deviceReadiness';

describe('browser device readiness', () => {
  it('starts unknown and does not request permissions on page load', () => {
    const check = initialBrowserDeviceCheck();
    expect(check.camera).toBe('unknown');
    expect(check.microphone).toBe('unknown');
    expect(check.message).toContain('尚未檢查');
  });
});
