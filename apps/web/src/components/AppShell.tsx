import { useEffect, useRef, type FocusEvent, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import { navigateTo } from '../app/routing';
import { useNarration } from '../accessibility/NarrationProvider';
import type { NarrationDetail } from '../accessibility/narrator';
import basicIcon from '../assets/basic_icon.png';

interface AppShellProps {
  readonly children: ReactNode;
  readonly currentLabel: string;
  readonly headerActions?: ReactNode;
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
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstChoiceRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    firstChoiceRef.current?.focus();
    const main = document.querySelector<HTMLElement>('#main-content');
    const header = document.querySelector<HTMLElement>('.site-header');
    if (main) main.inert = true;
    if (header) header.inert = true;
    return () => {
      if (main) main.inert = false;
      if (header) header.inert = false;
    };
  }, []);
  function trapFocus(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'Tab') return;
    const buttons = dialogRef.current?.querySelectorAll<HTMLButtonElement>('button');
    if (!buttons?.length) return;
    if (event.shiftKey && document.activeElement === buttons[0]) {
      event.preventDefault();
      buttons[buttons.length - 1].focus();
    } else if (!event.shiftKey && document.activeElement === buttons[buttons.length - 1]) {
      event.preventDefault();
      buttons[0].focus();
    }
  }
  return (
    <div ref={dialogRef} className="accessibility-gate" role="dialog" aria-modal="true" aria-labelledby="accessibility-choice-heading" onKeyDown={trapFocus}>
      <section className="accessibility-choice">
        <p className="eyebrow">第一次使用設定</p>
        <h2 id="accessibility-choice-heading">請選擇一種朗讀方式</h2>
        <p>選擇適合你的朗讀方式，之後可在頁首調整。</p>
        <div className="button-row">
          <button ref={firstChoiceRef} className="button" type="button" onClick={() => chooseMode('system')}>
            使用 Narrator／NVDA
          </button>
          <button className="button secondary" type="button" onClick={() => chooseMode('app')}>
            使用內建旁白
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

export function AppShell({ children, currentLabel, headerActions }: AppShellProps) {
  const narration = useNarration();
  const isStudent = currentLabel === '學生模式';
  const runtimeLabel = import.meta.env.VITE_DATA_MODE === 'real'
    ? '即時服務模式'
    : '本機展示模式：課程與語音以範例資料模擬';

  useEffect(() => {
    if (narration.mode === 'app') {
      narration.announce(currentLabel, { priority: 3, key: 'page', interrupt: true });
    }
  }, [currentLabel, narration.mode]);

  useEffect(() => {
    if (narration.mode === null) return;
    requestAnimationFrame(() => document.querySelector<HTMLElement>('[data-page-title]')?.focus());
  }, [narration.mode]);

  function handleFocusCapture(event: FocusEvent<HTMLDivElement>): void {
    if (narration.mode !== 'app') return;
    const target = event.target;
    if (!(target instanceof HTMLElement) || target === event.currentTarget) return;
    narration.announce(focusLabel(target), { priority: 1, key: 'focus' });
  }

  return (
    <div className={`app-shell ${isStudent ? 'student-shell' : 'observer-shell'}`} onFocusCapture={handleFocusCapture}>
      <a className="skip-link" href="#main-content">跳到主要內容</a>
      <header className="site-header">
        <a className="brand" href="/setup" onClick={(event) => handleInternalLink(event, '/setup')}>
          <img className="brand-icon" src={basicIcon} alt="" />
          <span>hear tAIgi</span>
        </a>
        {isStudent ? headerActions || <span className="header-context">我的課程</span> : (
          <div className="header-navigation">
            <nav aria-label="主要導覽">
              <a href="/setup" aria-current={currentLabel === '首頁' ? 'page' : undefined} onClick={(event) => handleInternalLink(event, '/setup')}>首頁</a>
              <a href="/capture" aria-current={currentLabel === '教材' ? 'page' : undefined} onClick={(event) => handleInternalLink(event, '/capture')}>準備教材</a>
              <a href="/health" aria-current={currentLabel === '健康檢查' ? 'page' : undefined} onClick={(event) => handleInternalLink(event, '/health')}>系統狀態</a>
              {currentLabel === '教師／家長模式' ? <a href={window.location.pathname} aria-current="page">教師／家長</a> : null}
            </nav>
            {headerActions}
          </div>
        )}
      </header>
      {narration.mode === null ? <AccessibilityChoice /> : <NarrationControls />}
      {children}
      {!isStudent ? <footer className="site-footer"><details><summary>展示資訊</summary><p>{runtimeLabel}</p></details></footer> : null}
    </div>
  );
}
