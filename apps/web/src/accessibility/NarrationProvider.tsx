import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  createNarratorController,
  type NarrationDetail,
  type NarrationMode,
  type NarrationOptions,
  type NarratorController,
  type NarratorSnapshot,
} from './narrator';

const STORAGE_KEY = 'hear-our-language.accessibility-mode';

export interface NarrationContextValue extends NarratorSnapshot {
  readonly chooseMode: (mode: Exclude<NarrationMode, null>) => void;
  readonly announce: (text: string, options?: NarrationOptions) => string | null;
  readonly stop: () => void;
  readonly pause: () => void;
  readonly resume: () => void;
  readonly replay: () => void;
  readonly setRate: (rate: number) => void;
  readonly setDetail: (detail: NarrationDetail) => void;
}

const NarrationContext = createContext<NarrationContextValue | null>(null);

function readStoredMode(): NarrationMode {
  if (typeof window === 'undefined') return null;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored === 'system' || stored === 'app' ? stored : null;
  } catch {
    return null;
  }
}

function persistMode(mode: NarrationMode): void {
  if (typeof window === 'undefined' || !mode) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // The visible choice remains authoritative even when storage is blocked.
  }
}

export function NarrationProvider({ children }: { readonly children: ReactNode }) {
  const [controller] = useState<NarratorController>(() => createNarratorController({ mode: readStoredMode() }));
  const [snapshot, setSnapshot] = useState<NarratorSnapshot>(controller.snapshot);
  const [mode, setMode] = useState<NarrationMode>(controller.snapshot.mode);

  useEffect(() => {
    const unsubscribe = controller.subscribe((next) => {
      setSnapshot(next);
      setMode(next.mode);
    });
    return () => {
      unsubscribe();
      controller.dispose();
    };
  }, [controller]);

  const chooseMode = useCallback((nextMode: Exclude<NarrationMode, null>) => {
    controller.setMode(nextMode);
    setMode(nextMode);
    persistMode(nextMode);
  }, [controller]);

  const value = useMemo<NarrationContextValue>(() => ({
    ...snapshot,
    mode,
    chooseMode,
    announce: (text, options) => controller.announce(text, options),
    stop: () => controller.stop(),
    pause: () => controller.pause(),
    resume: () => controller.resume(),
    replay: () => controller.replay(),
    setRate: (rate) => controller.setRate(rate),
    setDetail: (detail) => controller.setDetail(detail),
  }), [chooseMode, controller, mode, snapshot]);

  return <NarrationContext.Provider value={value}>{children}</NarrationContext.Provider>;
}

export function useNarration(): NarrationContextValue {
  const context = useContext(NarrationContext);
  if (!context) throw new Error('useNarration must be used inside NarrationProvider');
  return context;
}
