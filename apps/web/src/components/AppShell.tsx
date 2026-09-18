import { useEffect, type FocusEvent, type MouseEvent, type ReactNode } from 'react';
import { navigateTo } from '../app/routing';
import { useNarration } from '../accessibility/NarrationProvider';
import type { NarrationDetail } from '../accessibility/narrator';

interface AppShellProps {
  readonly children: ReactNode;
  readonly currentLabel: string;
}

function handleInternalLink(event: MouseEvent<HTMLAnchorElement>, path: string): void {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  navigateTo(path);
}

function focusLabel(target: HTMLElement): string {
  const labelledBy = target.getAttribute('aria-labelledby');
  if (labelledBy) {
    const text = labelledBy
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent?.trim() || '')
      .filter(Boolean)
      .join(' ');
    if (text) return text;
  }
  const ariaLabel = target.getAttribute('aria-label')?.trim();
  if (ariaLabel) return ariaLabel;
  const id = target.getAttribute('id');
  if (id) {
    const label = document.querySelector<HTMLLabelElement>(`label[for="${CSS.escape(id)}"]`);
    if (label?.textContent?.trim()) return label.textContent.trim();
  }
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) {
    return target.getAttribute('placeholder')?.trim() || target.value || target.tagName;
  }
  return target.textContent?.replace(/\s+/g, ' ').trim().slice(0, 160) || target.tagName;
}

const detailLabels: Record<NarrationDetail, string> = {
  brief: '簡短',
  standard: '標準',
  verbose: '詳細',
};

function AccessibilityChoice() {
  const { chooseMode } = useNarration();
  return (
    <div className="accessibility-gate" role="dialog" aria-modal="true" aria-labelledby="accessibility-choice-heading">
      <section className="accessibility-choice">
        <p className="eyebrow">第一次使用設定</p>
        <h2 id="accessibility-choice-heading">請選擇一種朗讀方式</h2>
        <p>我們不會自動猜測你是否使用螢幕閱讀器。請明確選擇一種；之後可以在頁首重新設定。</p>
        <div className="button-row">
          <button className="button" type="button" onClick={() => chooseMode('system')}>
            使用系統螢幕閱讀器
          </button>
          <button className="button secondary" type="button" onClick={() => chooseMode('app')}>
            使用 App 旁白
          </button>
        </div>
      </section>
    </div>
  );
}

function NarrationControls() {
  const {
    mode,
    status,
    rate,
    detail,
    queueLength,
    lastText,
    available,
    stop,
    pause,
    resume,
    replay,
    setRate,
    setDetail,
    chooseMode,
  } = useNarration();
  if (mode !== 'app') return null;
  return (
    <section className="narration-panel" aria-labelledby="narration-heading">
      <div>
        <p className="eyebrow">App 旁白</p>
        <h2 id="narration-heading">中文 UI 朗讀控制</h2>
        <p role="status" aria-live="polite">
          {available ? `狀態：${status === 'speaking' ? '朗讀中' : status === 'paused' ? '已暫停' : '待機'}；佇列 ${queueLength} 段。` : '此瀏覽器沒有可用的 Web Speech voice；畫面文字仍完整保留。'}
        </p>
      </div>
      <div className="narration-controls" aria-label="App 旁白操作">
        <button className="button secondary" type="button" onClick={stop}>停止旁白</button>
        <button className="button secondary" type="button" onClick={status === 'paused' ? resume : pause} disabled={status === 'idle'}>
          {status === 'paused' ? '繼續旁白' : '暫停旁白'}
        </button>
        <button className="button secondary" type="button" onClick={replay} disabled={!lastText}>重播上一段</button>
        <label htmlFor="narration-rate">語速 {rate.toFixed(1)} 倍</label>
        <input id="narration-rate" type="range" min="0.5" max="2" step="0.1" value={rate} onChange={(event) => setRate(Number(event.target.value))} />
        <label htmlFor="narration-detail">提示詳細度</label>
        <select id="narration-detail" value={detail} onChange={(event) => setDetail(event.target.value as NarrationDetail)}>
          {Object.entries(detailLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <button className="button link-button" type="button" onClick={() => chooseMode('system')}>改用系統螢幕閱讀器</button>
      </div>
    </section>
  );
}

export function AppShell({ children, currentLabel }: AppShellProps) {
  const narration = useNarration();
  const runtimeLabel = import.meta.env.VITE_DATA_MODE === 'real'
    ? 'Real adapter · Core Backend is the source of truth'
    : 'Mock mode · keyboard, speech, and session recovery are simulated locally';

  useEffect(() => {
    if (narration.mode === 'app') {
      narration.announce(currentLabel, { priority: 3, key: 'page', interrupt: true });
    }
  }, [currentLabel, narration.mode]);

  function handleFocusCapture(event: FocusEvent<HTMLDivElement>): void {
    if (narration.mode !== 'app') return;
    const target = event.target;
    if (!(target instanceof HTMLElement) || target === event.currentTarget) return;
    narration.announce(focusLabel(target), { priority: 1, key: 'focus' });
  }

  return (
    <div className="app-shell" onFocusCapture={handleFocusCapture}>
      <header className="site-header">
        <a className="brand" href="/setup" onClick={(event) => handleInternalLink(event, '/setup')}>
          聽見母語
        </a>
        <nav aria-label="主要導覽">
          <a href="/setup" onClick={(event) => handleInternalLink(event, '/setup')}>設定</a>
          <a href="/capture" onClick={(event) => handleInternalLink(event, '/capture')}>教材</a>
          <span aria-current="page">{currentLabel}</span>
        </nav>
      </header>
      {narration.mode === null ? <AccessibilityChoice /> : <NarrationControls />}
      {children}
      <footer className="site-footer">{runtimeLabel}</footer>
    </div>
  );
}
