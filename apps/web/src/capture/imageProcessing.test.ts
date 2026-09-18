import { describe, expect, it } from 'vitest';
import { calculateOutputSize, normalizeCropRect } from './imageProcessing';

describe('image processing geometry', () => {
  it('normalizes crop bounds without allowing an empty rectangle', () => {
    expect(normalizeCropRect({ x: -1, y: 0.4, width: 2, height: 0 })).toEqual({
      x: 0,
      y: 0.4,
      width: 1,
      height: 0.01,
    });
  });

  it('keeps the page aspect ratio while enforcing a maximum dimension', () => {
    expect(calculateOutputSize(6000, 4000, undefined, 4096)).toEqual({
      width: 4096,
      height: 2731,
    });
    expect(calculateOutputSize(6000, 4000, { x: 0.1, y: 0.1, width: 0.8, height: 0.8 }, 4096)).toEqual({
      width: 4096,
      height: 2731,
    });
  });
});
