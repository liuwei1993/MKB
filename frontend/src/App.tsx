import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import './App.css'

type ArticleMeta = {
  pmid: string
  title: string
  journal: string
  year: string
  authors: string
  url: string
  url_label?: string
  has_abstract: boolean
  has_fulltext?: boolean
  pmcid?: string
  doi?: string
}

type RecentTurn = {
  question: string
  excerpt: string
  pmids: string[]
}

type ContextEnvelope = {
  summary: string
  recent: RecentTurn[]
}

type ChatTurn = {
  id: string
  question: string
  answer: string
  queries: string[]
  standalone: string
  relation: string
  retrieval: boolean | null
  articles: ArticleMeta[]
  status: string
  error: string
}

const EXAMPLES = [
  'SGLT2 抑制剂对心衰住院的影响',
  'GLP-1 受体激动剂与减重的证据',
  '阿司匹林一级预防心血管事件的获益与出血风险',
  '肺癌免疫治疗一线方案如何选择',
]

const EMPTY_CONTEXT: ContextEnvelope = { summary: '', recent: [] }

/** HTTP 非 localhost 下 crypto.randomUUID 不可用，需兜底 */
function newTurnId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch {
    /* insecure context */
  }
  return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 11)}`
}

function App() {
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [context, setContext] = useState<ContextEnvelope>(EMPTY_CONTEXT)
  const [loading, setLoading] = useState(false)
  const [citeTurnId, setCiteTurnId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const contextRef = useRef<ContextEnvelope>(EMPTY_CONTEXT)
  const askGen = useRef(0)
  const loadingRef = useRef(false)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const citeArticles = turns.find((t) => t.id === citeTurnId)?.articles

  useEffect(() => {
    contextRef.current = context
  }, [context])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns])

  const reset = useCallback(() => {
    askGen.current += 1
    abortRef.current?.abort()
    loadingRef.current = false
    contextRef.current = EMPTY_CONTEXT
    setTurns([])
    setContext(EMPTY_CONTEXT)
    setCiteTurnId(null)
    setQuestion('')
    setLoading(false)
  }, [])

  const ask = useCallback(async (q: string) => {
    const trimmed = q.trim()
    if (!trimmed || loadingRef.current) return

    abortRef.current?.abort()
    const gen = ++askGen.current
    const controller = new AbortController()
    abortRef.current = controller
    const alive = () => askGen.current === gen

    const id = newTurnId()
    loadingRef.current = true
    setLoading(true)
    setQuestion('')
    setTurns((prev) => [
      ...prev,
      {
        id,
        question: trimmed,
        answer: '',
        queries: [],
        standalone: '',
        relation: '',
        retrieval: null,
        articles: [],
        status: '提交中…',
        error: '',
      },
    ])

    const patch = (partial: Partial<ChatTurn>) => {
      if (!alive()) return
      setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...partial } : t)))
    }

    try {
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: trimmed,
          context: contextRef.current,
        }),
        signal: controller.signal,
      })

      if (!res.ok || !res.body) {
        throw new Error(`请求失败 (${res.status})`)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        if (!alive()) return
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          if (!alive()) return
          const line = part
            .split('\n')
            .find((l) => l.startsWith('data:'))
          if (!line) continue
          const payload = line.slice(5).trim()
          if (!payload) continue
          let event: Record<string, unknown>
          try {
            event = JSON.parse(payload)
          } catch {
            continue
          }
          const type = event.type as string
          if (type === 'status') {
            patch({ status: String(event.message || '') })
          } else if (type === 'queries') {
            patch({
              queries: (event.queries as string[]) || [],
              standalone: String(event.standalone_question || ''),
              relation: String(event.relation || ''),
              retrieval: Boolean(event.retrieval),
            })
          } else if (type === 'meta') {
            patch({
              articles: (event.articles as ArticleMeta[]) || [],
              status: `已检索 ${event.count ?? 0} 篇文献，正在生成回答…`,
            })
          } else if (type === 'token') {
            const piece = String(event.content || '')
            if (!alive()) return
            setTurns((prev) =>
              prev.map((t) =>
                t.id === id
                  ? { ...t, answer: t.answer + piece, status: '' }
                  : t,
              ),
            )
          } else if (type === 'context') {
            const next = event.context as ContextEnvelope
            if (next && alive()) {
              contextRef.current = next
              setContext(next)
            }
          } else if (type === 'error') {
            patch({ error: String(event.message || '未知错误'), status: '' })
          } else if (type === 'done') {
            patch({ status: '' })
          }
        }
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError' || !alive()) return
      patch({ error: (e as Error).message || '请求失败', status: '' })
    } finally {
      if (alive()) {
        loadingRef.current = false
        setLoading(false)
      }
    }
  }, [])

  return (
    <div className="app">
      <header className="brand">
        <h1>MKB</h1>
        <p>基于 PubMed 文献的医学知识问答</p>
        {turns.length > 0 && (
          <button type="button" className="new-chat" onClick={reset}>
            新对话
          </button>
        )}
      </header>

      {turns.length > 0 && (
        <div className="thread">
          {turns.map((turn) => (
            <article key={turn.id} className="turn">
              <div className="bubble user">{turn.question}</div>
              <div className="bubble assistant">
                {turn.status && <div className="status">{turn.status}</div>}
                {turn.error && <div className="error">{turn.error}</div>}
                {turn.relation === 'follow_up' &&
                  turn.standalone &&
                  turn.standalone !== turn.question && (
                    <p className="queries">理解为本轮问题：{turn.standalone}</p>
                  )}
                {turn.queries.length > 0 && (
                  <p className="queries">检索词：{turn.queries.join(' · ')}</p>
                )}
                {turn.retrieval === false && !turn.error && (
                  <p className="queries">本轮未重新检索文献</p>
                )}
                {turn.answer && (
                  <div className="md">
                    <ReactMarkdown>{turn.answer}</ReactMarkdown>
                  </div>
                )}
                {turn.articles.length > 0 && (
                  <button
                    type="button"
                    className="cite-open"
                    onClick={() => setCiteTurnId(turn.id)}
                  >
                    依据文献（{turn.articles.length}）
                  </button>
                )}
              </div>
            </article>
          ))}
          <div ref={bottomRef} />
        </div>
      )}

      {turns.length === 0 && (
        <div className="examples">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              disabled={loading}
              onClick={() => void ask(ex)}
            >
              {ex}
            </button>
          ))}
        </div>
      )}

      <div className="composer">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={
            turns.length > 0
              ? '继续追问，例如：那女性患者呢？或：把上一回答缩短'
              : '提出医学问题，例如：SGLT2 抑制剂对心衰住院的影响…'
          }
          rows={2}
          disabled={loading}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void ask(question)
            }
          }}
        />
        <button
          type="button"
          aria-label="发送"
          disabled={loading || !question.trim()}
          onClick={() => void ask(question)}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path
              d="M5 12h14M13 6l6 6-6 6"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>

      <footer className="footer">
        仅供科研/学习参考，不能替代临床诊疗。数据来源：PubMed / NCBI。
      </footer>
      {citeArticles && citeArticles.length > 0 && (
        <CitationDialog
          articles={citeArticles}
          onClose={() => setCiteTurnId(null)}
        />
      )}
    </div>
  )
}

function CitationDialog({
  articles,
  onClose,
}: {
  articles: ArticleMeta[]
  onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog || dialog.open) return
    dialog.showModal()
  }, [])

  const requestClose = () => {
    const dialog = ref.current
    if (dialog?.open) dialog.close()
    else onClose()
  }

  return (
    <dialog
      ref={ref}
      className="cite-dialog"
      aria-labelledby="cite-dialog-title"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) requestClose()
      }}
    >
      <div className="cite-dialog-head">
        <h2 id="cite-dialog-title">依据文献（{articles.length}）</h2>
        <button type="button" className="cite-dialog-close" onClick={requestClose}>
          关闭
        </button>
      </div>
      <ul className="citations">
        {articles.map((a) => (
          <li key={a.pmid}>
            <p className="title">{a.title}</p>
            <p className="meta">
              {[a.authors, a.journal, a.year].filter(Boolean).join(' · ')}
              {!a.has_abstract ? ' · 无摘要' : ''}
              {a.has_fulltext ? ' · 已用全文' : ''}
            </p>
            <a href={a.url} target="_blank" rel="noreferrer">
              {a.url_label || 'PubMed'} · PMID:{a.pmid}
            </a>
          </li>
        ))}
      </ul>
    </dialog>
  )
}

export default App
