import { useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { linkifyCitations } from './citations'
import './DebugPage.css'

function extractAnswerMarkdown(outputText: string): string {
  const raw = outputText.trim()
  if (!raw) return ''
  try {
    const data = JSON.parse(raw) as { answer?: unknown }
    if (typeof data.answer === 'string') return data.answer
  } catch {
    // fall through: treat whole editor as markdown
  }
  return raw
}

type StepId =
  | 'understand'
  | 'search'
  | 'fulltext'
  | 'passages'
  | 'answer'
  | 'suggest'

type QueryTranslation = { query: string; zh: string }

type StepView = {
  id: StepId
  label: string
  status: string
  prompts: { system: string; user: string } | null
  input: unknown
  output: unknown
  warning?: string | null
}

type SessionView = {
  id: string
  question: string
  current_step: StepId
  status: string
  error: string | null
  steps_order: StepId[]
  steps_meta: { id: StepId; label: string }[]
  steps: Record<string, StepView>
  query_translations: QueryTranslation[]
}

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { detail: text }
  }
  if (!res.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data
        ? String((data as { detail: unknown }).detail)
        : text || res.statusText
    throw new Error(detail || `HTTP ${res.status}`)
  }
  return data as T
}

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export default function DebugPage() {
  const [question, setQuestion] = useState('')
  const [questionExpanded, setQuestionExpanded] = useState(true)
  const [session, setSession] = useState<SessionView | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [systemPrompt, setSystemPrompt] = useState('')
  const [userPrompt, setUserPrompt] = useState('')
  const [outputText, setOutputText] = useState('')
  const [queryRows, setQueryRows] = useState<QueryTranslation[]>([])
  const [previewOpen, setPreviewOpen] = useState(false)

  const current = session?.steps[session.current_step]
  const isLlmStep =
    session?.current_step === 'understand' ||
    session?.current_step === 'answer' ||
    session?.current_step === 'suggest'
  const previewMarkdown =
    session?.current_step === 'answer' ? extractAnswerMarkdown(outputText) : ''

  const syncEditors = (view: SessionView) => {
    const step = view.steps[view.current_step]
    setSystemPrompt(step?.prompts?.system || '')
    setUserPrompt(step?.prompts?.user || '')
    setOutputText(step?.output ? pretty(step.output) : '')
    const fromOutput =
      step?.output &&
      typeof step.output === 'object' &&
      step.output !== null &&
      'query_translations' in step.output
        ? (step.output as { query_translations?: QueryTranslation[] })
            .query_translations
        : null
    const translations =
      fromOutput ||
      view.query_translations ||
      (step?.input &&
      typeof step.input === 'object' &&
      step.input !== null &&
      'query_translations' in step.input
        ? (step.input as { query_translations?: QueryTranslation[] })
            .query_translations
        : null) ||
      []
    if (translations.length) {
      setQueryRows(translations.map((t) => ({ query: t.query, zh: t.zh || '' })))
    } else if (
      step?.output &&
      typeof step.output === 'object' &&
      step.output !== null &&
      'queries' in step.output &&
      Array.isArray((step.output as { queries: unknown }).queries)
    ) {
      setQueryRows(
        ((step.output as { queries: string[] }).queries || []).map((q) => ({
          query: q,
          zh: '',
        })),
      )
    } else {
      setQueryRows([])
    }
  }

  const applyView = (view: SessionView) => {
    setSession(view)
    syncEditors(view)
    setError(view.error)
  }

  const withBusy = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const startSession = () =>
    withBusy(async () => {
      const view = await api<SessionView>('/api/debug/sessions', {
        method: 'POST',
        body: JSON.stringify({ question: question.trim() }),
      })
      applyView(view)
      const ran = await api<SessionView>(`/api/debug/sessions/${view.id}/run`, {
        method: 'POST',
        body: JSON.stringify({}),
      })
      applyView(ran)
      setQuestionExpanded(false)
    })

  const runStep = () => {
    if (!session) return
    withBusy(async () => {
      const body: Record<string, unknown> = {}
      if (isLlmStep) {
        body.system_prompt = systemPrompt
        body.user_prompt = userPrompt
      }
      if (session.current_step === 'search' && queryRows.length) {
        body.overrides = { queries: queryRows.map((r) => r.query).filter(Boolean) }
      }
      if (session.current_step === 'understand' && queryRows.length === 0) {
        // prompts only
      }
      const view = await api<SessionView>(
        `/api/debug/sessions/${session.id}/run`,
        { method: 'POST', body: JSON.stringify(body) },
      )
      applyView(view)
    })
  }

  const saveOutput = () => {
    if (!session) return
    withBusy(async () => {
      let output: Record<string, unknown>
      if (
        session.current_step === 'understand' &&
        queryRows.length > 0
      ) {
        const base = outputText.trim()
          ? (JSON.parse(outputText) as Record<string, unknown>)
          : {}
        output = {
          ...base,
          queries: queryRows.map((r) => r.query).filter(Boolean),
          query_translations: queryRows,
        }
      } else {
        output = JSON.parse(outputText) as Record<string, unknown>
      }
      const view = await api<SessionView>(
        `/api/debug/sessions/${session.id}/output`,
        { method: 'PATCH', body: JSON.stringify({ output }) },
      )
      applyView(view)
    })
  }

  const nextStep = () => {
    if (!session) return
    withBusy(async () => {
      // Persist local query edits before leaving understand/search.
      if (
        (session.current_step === 'understand' || session.current_step === 'search') &&
        queryRows.length > 0 &&
        current?.output
      ) {
        if (session.current_step === 'understand') {
          const base = outputText.trim()
            ? (JSON.parse(outputText) as Record<string, unknown>)
            : {}
          await api(`/api/debug/sessions/${session.id}/output`, {
            method: 'PATCH',
            body: JSON.stringify({
              output: {
                ...base,
                queries: queryRows.map((r) => r.query).filter(Boolean),
                query_translations: queryRows,
              },
            }),
          })
        }
      }
      const advanced = await api<SessionView>(
        `/api/debug/sessions/${session.id}/advance`,
        { method: 'POST' },
      )
      applyView(advanced)
      if (
        advanced.status !== 'done' &&
        (!advanced.steps[advanced.current_step]?.output ||
          advanced.steps[advanced.current_step]?.status === 'pending' ||
          advanced.steps[advanced.current_step]?.status === 'stale')
      ) {
        const body: Record<string, unknown> = {}
        const step = advanced.steps[advanced.current_step]
        if (step?.prompts) {
          body.system_prompt = step.prompts.system
          body.user_prompt = step.prompts.user
        }
        const ran = await api<SessionView>(
          `/api/debug/sessions/${advanced.id}/run`,
          { method: 'POST', body: JSON.stringify(body) },
        )
        applyView(ran)
      }
    })
  }

  const retranslate = () => {
    if (!session) return
    withBusy(async () => {
      const view = await api<SessionView>(
        `/api/debug/sessions/${session.id}/translate-queries`,
        {
          method: 'POST',
          body: JSON.stringify({
            queries: queryRows.map((r) => r.query).filter(Boolean),
          }),
        },
      )
      applyView(view)
    })
  }

  const reset = () => {
    if (session) {
      void api(`/api/debug/sessions/${session.id}`, { method: 'DELETE' }).catch(
        () => undefined,
      )
    }
    setSession(null)
    setError(null)
    setSystemPrompt('')
    setUserPrompt('')
    setOutputText('')
    setQueryRows([])
    setQuestionExpanded(true)
  }

  const stepList = useMemo(() => session?.steps_meta || [], [session])

  return (
    <div className="debug-page">
      <header className="debug-header">
        <div className="debug-brand">
          <strong>MKB 调试</strong>
          <a href="/">返回问答</a>
        </div>
        <div className="debug-question">
          <button
            type="button"
            className="question-toggle"
            onClick={() => setQuestionExpanded((v) => !v)}
            aria-expanded={questionExpanded}
          >
            <span className="question-toggle-label">提问内容</span>
            <span className="question-toggle-preview">
              {question.trim()
                ? question.trim().replace(/\s+/g, ' ').slice(0, 80) +
                  (question.trim().length > 80 ? '…' : '')
                : '点击展开输入单轮提问…'}
            </span>
            <span className="question-toggle-icon">
              {questionExpanded ? '收起' : '展开'}
            </span>
          </button>
          {questionExpanded ? (
            <div className="debug-start">
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="输入单轮提问或粘贴多章节大纲…"
                disabled={busy || !!session}
              />
              {!session ? (
                <button
                  type="button"
                  className="primary"
                  disabled={busy || !question.trim()}
                  onClick={startSession}
                >
                  {busy ? '启动中…' : '开始'}
                </button>
              ) : (
                <button type="button" disabled={busy} onClick={reset}>
                  重置
                </button>
              )}
            </div>
          ) : (
            <div className="debug-start-collapsed">
              {!session ? (
                <button
                  type="button"
                  className="primary"
                  disabled={busy || !question.trim()}
                  onClick={startSession}
                >
                  {busy ? '启动中…' : '开始'}
                </button>
              ) : (
                <button type="button" disabled={busy} onClick={reset}>
                  重置
                </button>
              )}
            </div>
          )}
        </div>
      </header>

      {error ? <div className="debug-error">{error}</div> : null}

      {!session ? (
        <div className="debug-empty">输入问题后开始逐步调试检索流水线。</div>
      ) : (
        <div className="debug-body">
          <aside className="debug-steps">
            {stepList.map((meta, index) => {
              const step = session.steps[meta.id]
              const active = session.current_step === meta.id
              const status = step?.status || 'pending'
              return (
                <div
                  key={meta.id}
                  className={`debug-step-item${active ? ' active' : ''} status-${status}`}
                >
                  <span className="idx">{index + 1}</span>
                  <div>
                    <div className="label">{meta.label}</div>
                    <div className="status">{status}</div>
                  </div>
                </div>
              )
            })}
          </aside>

          <main className="debug-main">
            <div className="debug-toolbar">
              <div>
                当前：<strong>{current?.label || session.current_step}</strong>
                <span className="muted"> · {session.status}</span>
              </div>
            </div>

            {current?.warning ? (
              <div className="debug-warn">{current.warning}</div>
            ) : null}

            {isLlmStep ? (
              <section className="debug-panel">
                <h3>模型提示词</h3>
                <label>
                  System
                  <textarea
                    value={systemPrompt}
                    onChange={(e) => setSystemPrompt(e.target.value)}
                    rows={8}
                    disabled={busy}
                  />
                </label>
                <label>
                  User
                  <textarea
                    value={userPrompt}
                    onChange={(e) => setUserPrompt(e.target.value)}
                    rows={10}
                    disabled={busy}
                  />
                </label>
              </section>
            ) : null}

            {(session.current_step === 'understand' ||
              session.current_step === 'search') &&
            queryRows.length > 0 ? (
              <section className="debug-panel">
                <div className="panel-head">
                  <h3>检索式（英 / 中对照）</h3>
                  <button type="button" disabled={busy} onClick={retranslate}>
                    重新翻译检索式
                  </button>
                </div>
                <div className="query-list">
                  {queryRows.map((row, i) => (
                    <div className="query-row" key={`q-${i}`}>
                      <textarea
                        value={row.query}
                        rows={2}
                        disabled={busy}
                        onChange={(e) => {
                          const next = [...queryRows]
                          next[i] = { ...next[i], query: e.target.value }
                          setQueryRows(next)
                        }}
                      />
                      <div className="query-zh">{row.zh || '（尚无中文译文）'}</div>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            <section className="debug-panel">
              <h3>步骤输入</h3>
              <pre>{pretty(current?.input)}</pre>
            </section>

            <section className="debug-panel">
              <h3>步骤输出（可编辑 JSON）</h3>
              <textarea
                className="output-editor"
                value={outputText}
                onChange={(e) => setOutputText(e.target.value)}
                rows={16}
                disabled={busy || !current?.output}
                placeholder="运行本步后在此查看并编辑输出"
              />
              <div className="debug-actions output-actions">
                <button type="button" disabled={busy} onClick={runStep}>
                  {current?.output ? '重新生成' : '运行本步'}
                </button>
                <button
                  type="button"
                  disabled={busy || !current?.output}
                  onClick={saveOutput}
                >
                  保存输出
                </button>
                {session.current_step === 'answer' ? (
                  <button
                    type="button"
                    disabled={!previewMarkdown.trim()}
                    onClick={() => setPreviewOpen(true)}
                  >
                    预览
                  </button>
                ) : null}
                <button
                  type="button"
                  className="primary"
                  disabled={
                    busy || !current?.output || session.current_step === 'suggest'
                  }
                  onClick={nextStep}
                >
                  下一步
                </button>
              </div>
            </section>
          </main>
        </div>
      )}

      {previewOpen ? (
        <div
          className="debug-preview-backdrop"
          role="presentation"
          onClick={() => setPreviewOpen(false)}
        >
          <div
            className="debug-preview-modal"
            role="dialog"
            aria-modal="true"
            aria-label="回答预览"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="debug-preview-head">
              <h2>回答预览</h2>
              <button type="button" onClick={() => setPreviewOpen(false)}>
                关闭
              </button>
            </div>
            <div className="debug-preview-body md">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a({ href, children }) {
                    if (href?.startsWith('#cite-')) {
                      return <span className="cite-chip">{children}</span>
                    }
                    return (
                      <a href={href} target="_blank" rel="noreferrer">
                        {children}
                      </a>
                    )
                  },
                }}
              >
                {linkifyCitations(previewMarkdown)}
              </ReactMarkdown>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
