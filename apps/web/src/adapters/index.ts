import type { FrontendAdapter } from './adapter';
import { MockAdapter } from './mockAdapter';
import { RealAdapter } from './realAdapter';

export function createAdapter(): FrontendAdapter {
  return import.meta.env.VITE_DATA_MODE === 'real' ? new RealAdapter() : new MockAdapter();
}
