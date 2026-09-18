import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import type { FrontendAdapter } from '../adapters/adapter';
import { asAdapterError } from '../adapters/errors';
import { useNarration } from '../accessibility/NarrationProvider';
import { AppShell } from '../components/AppShell';
import { StatusBanner } from '../components/StatusBanner';
import { ErrorState, LoadingState } from '../components/States';
import { navigateTo } from '../app/routing';
import type {
  LessonReviewPatch,
  ObserverAction,
  ObserverSessionViewModel,
  ObserverTurnView,
  SessionState,
  TeachingPhase,
} from '../types/viewModels';

const stateLabels: Record<SessionState, string> = {
  IDLE: '已暫停',
  SPEAKING: '等待播放',
  LISTENING: '聆聽回答',
  TRANSCRIBING: '辨識中',
  EVALUATING: '判定中',
  RECOVERABLE_ERROR: '可恢復錯誤',
  COMPLETE: '已完成',
};

const phaseLabels: Record<TeachingPhase, string> = {
  introduction: '介紹',
  demonstration: '示範',
  read_aloud: '跟讀',
  comprehension: '理解活動',
  hint: '提示',
  review: '複習',
  complete: '完成',
};

const actionLabels: Record<ObserverAction, string> = {
  skip: '跳過目前活動',
  redo: '讓學生重做',
  end: '結束教學回合',
  reset: '重設 demo session',
};

const resultLabels: Record<ObserverTurnView['result'], string> = {
  correct: '正確',
  partial: '部分完成',
  retry: '需要再試一次',
};

function formatRevision(value: string | null): string {
  return value || '未提供';
}

function confirmDangerousAction(action: ObserverAction): boolean {
  if (action !== 'end' && action !== 'reset') return true;
  if (typeof window === 'undefined' || typeof window.confirm !== 'function') return true;
  return window.confirm(
    action === 'reset'
      ? '重設會清除這個 demo session 的回合與熟悉度，確定要繼續嗎？'
      : '結束會停止目前教學回合，確定要繼續嗎？',
  );
}

function turnLabel(turn: ObserverTurnView): string {
  return `${turn.turnId} · ${resultLabels[turn.result]} · ${Math.round(turn.progress * 100)}%`;
}

export function ObserverPage({ adapter, sessionId }: { readonly adapter: FrontendAdapter; readonly sessionId: string }) {
  const narration = useNarration();
  const [view, setView] = useState<ObserverSessionViewModel | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState('');
  const [busyAction, setBusyAction] = useState<ObserverAction | 'save' | null>(null);
  const [topic, setTopic] = useState('');
  const [sourceText, setSourceText] = useState('');
  const [accessibleActivity, setAccessibleActivity] = useState('');

  function load(): void {
    setError(null);
    setMessage('');
    setView(null);
    void adapter.getObserverSession(sessionId)
      .then((next) => {
        setView(next);
        setTopic(next.lesson.topic);
        setSourceText(next.lesson.sourceText);
        setAccessibleActivity(next.lesson.accessibleActivity);
      })
      .catch(setError);
  }

  useEffect(load, [adapter, sessionId]);

  async function saveLesson(patch: LessonReviewPatch, successMessage: string): Promise<void> {
    if (!view) return;
    setBusyAction('save');
    setError(null);
    try {
      const lesson = await adapter.reviewLesson(view.lessonId, patch);
      setView((current) => current ? {
        ...current,
        lesson,
        reviewStatus: lesson.reviewStatus,
      } : current);
      setMessage(successMessage);
      narration.announce(successMessage, { priority: 2, key: 'observer-message' });
    } catch (nextError) {
      setError(nextError);
    } finally {
      setBusyAction(null);
    }
  }

  async function saveLessonDraft(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    await saveLesson({
      topic: topic.trim(),
      sourceText: sourceText.trim(),
      accessibleActivity: accessibleActivity.trim(),
    }, '教材草稿已送回 Core Backend 驗證並儲存。');
  }

  async function approveLesson(): Promise<void> {
    await saveLesson({ reviewStatus: 'approved' }, '教材已批准；學生模式會使用這份 server-side Lesson。');
  }

  async function observerAction(action: ObserverAction): Promise<void> {
    if (!view || !confirmDangerousAction(action)) return;
    setBusyAction(action);
    setError(null);
    narration.stop();
    try {
      const next = await adapter.submitObserverAction(sessionId, action);
      setView(next);
      setTopic(next.lesson.topic);
      setSourceText(next.lesson.sourceText);
      setAccessibleActivity(next.lesson.accessibleActivity);
      const successMessage = action === 'end' && next.state !== 'COMPLETE'
        ? 'v0.1 尚無獨立結束端點；目前已安全暫停這個 session。'
        : `${actionLabels[action]}完成。`;
      setMessage(successMessage);
      narration.announce(successMessage, { priority: 3, key: 'observer-message', interrupt: true });
    } catch (nextError) {
      setError(nextError);
      const normalized = asAdapterError(nextError);
      setMessage(`控制未完成：${normalized.message}`);
      narration.announce(`控制未完成。${normalized.message}`, { priority: 3, key: 'observer-message', interrupt: true });
    } finally {
      setBusyAction(null);
    }
  }

  async function switchToStudent(): Promise<void> {
    narration.stop();
    navigateTo(`/session/${encodeURIComponent(sessionId)}/student`);
  }

  const canEditLesson = view?.lesson.reviewStatus === 'pending';
  const latestTurn = view?.turns.at(-1);

  return (
    <AppShell currentLabel="教師／家長模式">
      <main id="main-content" className="page observer-page" tabIndex={-1} aria-busy={busyAction !== null}>
        <p className="eyebrow">STAGE 09 · 教師／家長觀察</p>
        <h1 data-page-title tabIndex={-1}>觀察與介入</h1>
        <p className="lead">在同一筆 server-side session 上查看教材、引用、回合與健康狀態；學生模式不會收到這些教師／家長欄位。</p>
        {!view && !error ? <LoadingState label="載入觀察摘要、教材與服務狀態……" /> : null}
        {error ? <ErrorState error={error} onRetry={load} /> : null}
        {view ? (
          <>
            <StatusBanner health={view.health} />

            <section className="card observer-overview" aria-labelledby="observer-overview-heading">
              <p className="eyebrow">同一個 server-side session · {view.sessionId}</p>
              <h2 id="observer-overview-heading">{view.lesson.topic}</h2>
              <dl className="detail-list">
                <div><dt>Session 狀態</dt><dd>{stateLabels[view.state]}</dd></div>
                <div><dt>教學階段</dt><dd>{phaseLabels[view.phase]}</dd></div>
                <div><dt>進度</dt><dd>{view.completedTurns} 回合 · {Math.round(view.progress * 100)}%</dd></div>
                <div><dt>Lesson 審查</dt><dd>{view.lesson.reviewStatus}</dd></div>
                <div><dt>同步游標</dt><dd>revision {view.revision} · event {view.lastEventId}</dd></div>
              </dl>
              {message ? <p className="live-message" role="status" aria-live="polite">{message}</p> : null}
            </section>

            <section className="card" aria-labelledby="lesson-review-heading">
              <p className="eyebrow">教材審查</p>
              <h2 id="lesson-review-heading">待確認 Lesson</h2>
              <form onSubmit={(event) => void saveLessonDraft(event)}>
                <div className="form-field">
                  <label htmlFor="observer-topic">教材主題</label>
                  <input id="observer-topic" value={topic} onChange={(event) => setTopic(event.target.value)} disabled={!canEditLesson || busyAction !== null} />
                </div>
                <div className="form-field">
                  <label htmlFor="observer-source-text">教材文字</label>
                  <textarea id="observer-source-text" rows={3} value={sourceText} onChange={(event) => setSourceText(event.target.value)} disabled={!canEditLesson || busyAction !== null} />
                </div>
                <div className="form-field">
                  <label htmlFor="observer-accessible-activity">無障礙活動（不得直接洩漏答案）</label>
                  <textarea id="observer-accessible-activity" rows={4} value={accessibleActivity} onChange={(event) => setAccessibleActivity(event.target.value)} disabled={!canEditLesson || busyAction !== null} />
                </div>
                <p className="form-help">Core Backend 會再次執行 answer-leak、位置提示與 sighted-only clue 檢查；前端不自行改寫 canonical schema。</p>
                <div className="button-row">
                  <button className="button" type="submit" disabled={!canEditLesson || busyAction !== null}>儲存教材修改</button>
                  <button className="button primary-large" type="button" onClick={() => void approveLesson()} disabled={!canEditLesson || busyAction !== null}>批准 Lesson</button>
                  <button className="button secondary" type="button" onClick={() => void saveLesson({ reviewStatus: 'rejected' }, '教材已標記為需要退回修改。')} disabled={!canEditLesson || busyAction !== null}>退回修改</button>
                </div>
              </form>
            </section>

            <div className="two-column observer-columns">
              <section className="card" aria-labelledby="lesson-details-heading">
                <h2 id="lesson-details-heading">教材、目標與詞彙</h2>
                <dl className="detail-list">
                  <div><dt>場景</dt><dd>{view.lesson.scene}</dd></div>
                  <div><dt>原始活動</dt><dd>{view.lesson.originalActivity}</dd></div>
                  <div><dt>學習目標</dt><dd>{view.lesson.learningObjective}</dd></div>
                </dl>
                <div className="table-wrap">
                  <table>
                    <caption>教材詞彙、臺羅與中文義</caption>
                    <thead><tr><th scope="col">漢字</th><th scope="col">臺羅</th><th scope="col">意思</th><th scope="col">音檔 key</th></tr></thead>
                    <tbody>
                      {view.lesson.vocabulary.map((item) => (
                        <tr key={`${item.hanji}-${item.tailo}`}><th scope="row">{item.hanji}</th><td>{item.tailo}</td><td>{item.meaning}</td><td>{item.audioKey || '未提供'}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="card" aria-labelledby="citation-heading">
                <h2 id="citation-heading">Citation 與模型依據</h2>
                {view.evidence.length ? (
                  <ol className="citation-list">
                    {view.evidence.map((item) => <li key={`${item.sourceId}-${item.locator}`}><strong>{item.title}</strong><span>{item.excerpt}</span><small>{item.sourceId} · {item.locator}</small></li>)}
                  </ol>
                ) : <p className="empty-state">目前沒有可靠 citation；不可把無依據內容當成已驗證事實。</p>}
                <dl className="detail-list compact">
                  <div><dt>VLM revision</dt><dd>{formatRevision(view.vlmModelRevision)}</dd></div>
                  <div><dt>RAG revision</dt><dd>{formatRevision(view.ragIndexRevision)}</dd></div>
                  <div><dt>分析信心</dt><dd>{`${Math.round(view.lesson.confidence * 100)}%`}</dd></div>
                </dl>
                {view.answerEvidence.length ? <div className="teacher-only-note"><strong>教師檢視依據</strong><ul>{view.answerEvidence.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
              </section>
            </div>

            <section className="card" aria-labelledby="observer-controls-heading">
              <h2 id="observer-controls-heading">教師／家長控制</h2>
              <p>跳題與重做會沿用 Core Backend 的 session revision；結束與 reset 屬危險操作，必須明確確認。</p>
              <div className="button-row">
                {(['skip', 'redo', 'end', 'reset'] as const).map((action) => (
                  <button key={action} className={action === 'end' || action === 'reset' ? 'button danger' : 'button secondary'} type="button" disabled={busyAction !== null} onClick={() => void observerAction(action)}>
                    {busyAction === action ? '處理中……' : actionLabels[action]}
                  </button>
                ))}
              </div>
            </section>

            <section className="card" aria-labelledby="turns-heading">
              <h2 id="turns-heading">即時觀察與課後摘要</h2>
              {latestTurn ? <p className="live-message" role="status" aria-live="polite">最新回合：{turnLabel(latestTurn)}；逐字稿：{latestTurn.transcriptRaw}</p> : <p className="empty-state">尚未收到學生回答。</p>}
              <div className="turn-list">
                {view.turns.map((turn, index) => (
                  <article className="turn-item" key={turn.turnId} aria-labelledby={`turn-heading-${index}`}>
                    <h3 id={`turn-heading-${index}`}>{turnLabel(turn)}</h3>
                    <dl className="detail-list compact">
                      <div><dt>逐字稿</dt><dd>{turn.transcriptRaw}</dd></div>
                      <div><dt>正規化</dt><dd>{turn.transcriptNormalized}</dd></div>
                      <div><dt>回饋</dt><dd>{turn.feedback}</dd></div>
                      <div><dt>下一提示</dt><dd>{turn.nextPrompt}</dd></div>
                      <div><dt>延遲</dt><dd>ASR {turn.latencyMs.asr ?? '—'} ms · Backend {turn.latencyMs.backend} ms · TTS {turn.latencyMs.tts ?? '—'} ms · Total {turn.latencyMs.total} ms</dd></div>
                      <div><dt>裝置／fallback</dt><dd>{turn.asrDevice} · {turn.fallbacks.length ? turn.fallbacks.join('、') : '無'}</dd></div>
                    </dl>
                  </article>
                ))}
              </div>
              <div className="two-column summary-columns">
                <div>
                  <h3>提示歷程</h3>
                  {view.hintHistory.length ? <ul>{view.hintHistory.map((hint, index) => <li key={`${hint.turnId}-${index}`}>{hint.prompt}（{hint.feedback}）</li>)}</ul> : <p>尚未使用提示。</p>}
                </div>
                <div>
                  <h3>熟悉度與待複習</h3>
                  <ul>{view.familiarity.map((item) => <li key={item.concept}>{item.concept}：{item.status}</li>)}</ul>
                  <p>待複習：{view.conceptsToReview.length ? view.conceptsToReview.join('、') : '無'}</p>
                </div>
              </div>
            </section>

            <section className="card mode-switch" aria-labelledby="observer-switch-heading">
              <h2 id="observer-switch-heading">切換檢視</h2>
              <p>切換前會停止 App 旁白；學生與教師／家長模式仍讀取同一筆 session，頁面標題會接收焦點。</p>
              <button className="button" type="button" onClick={() => void switchToStudent()}>回到學生模式</button>
              <button className="button secondary" type="button" onClick={load} disabled={busyAction !== null}>重新整理觀察摘要</button>
            </section>
          </>
        ) : null}
      </main>
    </AppShell>
  );
}
