import { describe, expect, it } from 'vitest';
import { AdapterError, asAdapterError } from './errors';

describe('adapter errors', () => {
  it('normalizes an unknown client error without exposing payloads', () => {
    const error = asAdapterError(new Error('network unavailable'));
    expect(error).toBeInstanceOf(AdapterError);
    expect(error.code).toBe('CLIENT_ERROR');
    expect(error.retryable).toBe(true);
    expect(error.fallback).toBe('mock');
  });
});
