import { useEffect, useRef, type FocusEvent, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import { navigateTo } from '../app/routing';
import { NARRATION_FEATURE_ENABLED, useNarration } from '../accessibility/NarrationProvider';
import type { NarrationDetail } from '../accessibility/narrator';
import basicIcon from '../assets/basic_icon.png';

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

function isButtonTarget(target: HTMLElement): boolean {
  if (target instanceof HTMLButtonElement || target.getAttribute('role') === 'button') return true;
  return target instanceof HTMLInputElement && ['button', 'image', 'reset', 'submit'].includes(target.type);
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
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const background = Array.from(document.querySelectorAll<HTMLElement>('.app-shell > :not(.accessibility-gate)'));
    background.forEach((element) => { element.inert = true; });
    firstChoiceRef.current?.focus({ preventScroll: true });
    return () => {
      background.forEach((element) => { element.inert = false; });
      if (previousFocus?.isConnected) {
        previousFocus.focus({ preventScroll: true });
      } else {
        document.querySelector<HTMLElement>('[data-page-title]')?.focus({ preventScroll: true });
      }
    };
  }, []);

  function trapFocus(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key !== 'Tab') return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
      'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    ) || []).filter((element) => !element.hasAttribute('disabled') && !element.getAttribute('aria-hidden'));
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div ref={dialogRef} className="accessibility-gate" role="dialog" aria-modal="true" aria-labelledby="accessibility-choice-heading" aria-describedby="accessibility-choice-description" onKeyDown={trapFocus}>
      <section className="accessibility-choice">
        <p className="eyebrow">第一次使用設定</p>
        <h2 id="accessibility-choice-heading">請選擇一種朗讀方式</h2>
        <p id="accessibility-choice-description" className="accessibility-choice-description">如果你看不見畫面或需要鍵盤導覽，請優先使用系統螢幕閱讀器。瀏覽器的「朗讀」功能只能念出文字，不能完整取代螢幕閱讀器的焦點、按鈕和表單導覽。兩種模式都可以在之後切換。</p>
        <div className="button-row">
          <button ref={firstChoiceRef} className="button" type="button" aria-describedby="system-reader-choice-help" onClick={() => chooseMode('system')}>
            使用系統螢幕閱讀器（推薦）
          </button>
          <button className="button secondary" type="button" aria-describedby="app-narration-choice-help" onClick={() => chooseMode('app')}>
            使用內建網頁旁白
          </button>
        </div>
        <div className="accessibility-choice-help">
          <p id="system-reader-choice-help"><strong>系統螢幕閱讀器：</strong>例如 Windows Narrator、NVDA 或 macOS VoiceOver；網站不會再播放另一套 UI 旁白。</p>
          <p id="app-narration-choice-help"><strong>內建網頁旁白：</strong>使用瀏覽器的 Web Speech 語音念中文介面，適合沒有螢幕閱讀器時的展示或備援。</p>
        </div>
      </section>
    </div>
  );
}

function SystemReaderNotice() {
  const { chooseMode } = useNarration();

  return (
    <section className="narration-panel system-reader-panel" aria-labelledby="system-reader-heading">
      <div>
        <p className="eyebrow">系統螢幕閱讀器</p>
        <p id="system-reader-heading" className="narration-panel-title">已停用內建旁白，避免重複朗讀</p>
        <p>請使用 Narrator、NVDA 或 VoiceOver 讀取這個網頁。瀏覽器「朗讀」可以作為快速聆聽，但不會取代螢幕閱讀器的焦點和表單導覽。</p>
      </div>
      <div className="narration-controls" role="group" aria-label="系統螢幕閱讀器操作">
        <button className="button secondary" type="button" onClick={() => chooseMode('app')}>改用內建網頁旁白</button>
      </div>
    </section>
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
        <p id="narration-heading" className="narration-panel-title">中文 UI 朗讀控制</p>
        <p role="status" aria-live="polite">
          {available ? `狀態：${status === 'speaking' ? '朗讀中' : status === 'paused' ? '已暫停' : '待機'}；佇列 ${queueLength} 段。` : '此瀏覽器沒有可用的 Web Speech voice；畫面文字仍完整保留。'}
        </p>
      </div>
      <div className="narration-controls" role="group" aria-label="App 旁白操作">
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
  const isStudentView = currentLabel === '學生模式';
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
    requestAnimationFrame(() => document.querySelector<HTMLElement>('[data-page-title]')?.focus({ preventScroll: true }));
  }, [narration.mode]);

  function handleFocusCapture(event: FocusEvent<HTMLDivElement>): void {
    const target = event.target;
    if (!(target instanceof HTMLElement) || target === event.currentTarget) return;
    if (!isButtonTarget(target)) return;
    const label = focusLabel(target);
    if (!label || label === target.tagName) return;
    narration.announceFocus(label);
  }

  return (
    <div className={`app-shell ${isStudentView ? 'student-shell' : 'observer-shell'}`} onFocusCapture={handleFocusCapture}>
      <a className="skip-link" href="#main-content">跳到主要內容</a>
      <header className="site-header">
        <a className="brand" href="/setup" onClick={(event) => handleInternalLink(event, '/setup')}>
          <img className="brand-icon" src={basicIcon} alt="" />
          <span>hear tAIgi</span>
        </a>
        {isStudentView ? (
          <span className="header-context" aria-current="page">我的課程</span>
        ) : (
          <nav aria-label="主要導覽">
            <a href="/setup" aria-current={currentLabel === '首頁' ? 'page' : undefined} onClick={(event) => handleInternalLink(event, '/setup')}>首頁</a>
            <a href="/capture" aria-current={currentLabel === '準備教材' ? 'page' : undefined} onClick={(event) => handleInternalLink(event, '/capture')}>準備教材</a>
            <a href="/health" aria-current={currentLabel === '系統狀態' ? 'page' : undefined} onClick={(event) => handleInternalLink(event, '/health')}>系統狀態</a>
            {currentLabel === '教師／家長模式' ? <a href={window.location.pathname} aria-current="page">教師／家長</a> : null}
          </nav>
        )}
      </header>
      {NARRATION_FEATURE_ENABLED
        ? narration.mode === null ? <AccessibilityChoice /> : narration.mode === 'app' ? <NarrationControls /> : <SystemReaderNotice />
        : null}
      {children}
      {isStudentView ? null : <footer className="site-footer"><details><summary>展示資訊</summary><p>{runtimeLabel}</p></details></footer>}
    </div>
  );
}
