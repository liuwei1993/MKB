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
  title_zh?: string
}

type RecentTurn = {
  question: string
  excerpt: string
  pmids: string[]
}

type ContextEnvelope = {
  summary: string
  recent: RecentTurn[]
  last_answer?: string
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
  titlesPending: boolean
  status: string
  error: string
  stopped: boolean
}

const EXAMPLES = [
  'SGLT2 抑制剂对心衰住院的影响',
  'GLP-1 受体激动剂与减重的证据',
  '阿司匹林一级预防心血管事件的获益与出血风险',
  '肺癌免疫治疗一线方案如何选择',
]

const EMPTY_CONTEXT: ContextEnvelope = { summary: '', recent: [], last_answer: '' }
const RECENT_MAX_TURNS = 3
const EXCERPT_MAX_CHARS = 500
const LAST_ANSWER_MAX_CHARS = 12000

function pmidsIn(text: string): string[] {
  const found: string[] = []
  const re = /PMID\s*[:：]?\s*(\d{4,10})/gi
  for (const match of text.matchAll(re)) {
    const pmid = match[1]
    if (!pmid || found.includes(pmid)) continue
    found.push(pmid)
    if (found.length >= 20) break
  }
  return found
}

/** 停止时服务端不会再下发 context，用已生成的文本补上这一轮。 */
function contextAfterStop(
  ctx: ContextEnvelope,
  turn: { question: string; answer: string },
): ContextEnvelope {
  const answer = turn.answer.trim()
  const excerpt = answer.slice(0, EXCERPT_MAX_CHARS)
  const last = ctx.recent.at(-1)
  if (last?.question === turn.question && last.excerpt === excerpt) return ctx
  return {
    summary: ctx.summary,
    recent: [
      ...ctx.recent,
      { question: turn.question, excerpt, pmids: pmidsIn(answer) },
    ].slice(-RECENT_MAX_TURNS),
    last_answer: answer ? answer.slice(0, LAST_ANSWER_MAX_CHARS) : ctx.last_answer,
  }
}

const HAN = /[\u4e00-\u9fff]/
const NEAR_BOTTOM_PX = 16
const USER_SCROLL_IDLE_MS = 300

function isNearAnchor(anchor: HTMLElement | null): boolean {
  if (!anchor) return false
  const delta = anchor.getBoundingClientRect().bottom - window.innerHeight
  return Math.abs(delta) <= NEAR_BOTTOM_PX
}

function nestedScrollerConsumes(target: EventTarget | null, deltaY: number): boolean {
  if (!(target instanceof Element)) return false
  let node: Element | null = target
  while (node && node !== document.body && node !== document.documentElement) {
    if (node instanceof HTMLElement) {
      const overflowY = getComputedStyle(node).overflowY
      const canScroll =
        (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') &&
        node.scrollHeight > node.clientHeight + 1
      if (canScroll) {
        if (deltaY < 0 && node.scrollTop > 0) return true
        if (deltaY > 0 && node.scrollTop + node.clientHeight < node.scrollHeight - 1) return true
      }
    }
    node = node.parentElement
  }
  return false
}

function needsTitleTranslation(title: string): boolean {
  const text = title.trim()
  return text.length > 0 && !HAN.test(text)
}

function mergeArticleTitles(prev: ArticleMeta[], incoming: ArticleMeta[]): ArticleMeta[] {
  const translated = new Map(
    prev.flatMap((a) => (a.title_zh ? [[a.pmid, a.title_zh] as const] : [])),
  )
  return incoming.map((a) => {
    const title_zh = a.title_zh || translated.get(a.pmid)
    return title_zh ? { ...a, title_zh } : a
  })
}

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
  const turnsRef = useRef<ChatTurn[]>([])
  const draftRef = useRef<{ id: string; question: string; answer: string } | null>(null)
  const answerCommittedRef = useRef(false)
  const askGen = useRef(0)
  const loadingRef = useRef(false)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const followBottomRef = useRef(true)
  const userPinnedRef = useRef(true)
  const gestureStartedNearRef = useRef(true)
  const userScrollingRef = useRef(false)
  const gestureStartYRef = useRef(0)
  const programmaticRef = useRef(false)
  const scrollIdleRef = useRef<number | null>(null)
  const citeTurn = turns.find((t) => t.id === citeTurnId)

  const scrollToBottom = useCallback(() => {
    const anchor = bottomRef.current
    if (!anchor || isNearAnchor(anchor)) return
    const before = window.scrollY
    programmaticRef.current = true
    anchor.scrollIntoView({ behavior: 'auto', block: 'end' })
    if (Math.abs(window.scrollY - before) <= 1) {
      programmaticRef.current = false
      return
    }
    requestAnimationFrame(() => {
      programmaticRef.current = false
    })
  }, [])

  const stickToBottom = useCallback(() => {
    followBottomRef.current = true
    userPinnedRef.current = true
    userScrollingRef.current = false
    if (scrollIdleRef.current != null) {
      window.clearTimeout(scrollIdleRef.current)
      scrollIdleRef.current = null
    }
  }, [])

  turnsRef.current = turns

  useEffect(() => {
    contextRef.current = context
  }, [context])

  useEffect(() => {
    const armIdle = () => {
      if (scrollIdleRef.current != null) window.clearTimeout(scrollIdleRef.current)
      scrollIdleRef.current = window.setTimeout(() => {
        scrollIdleRef.current = null
        userScrollingRef.current = false
        const moved = Math.abs(window.scrollY - gestureStartYRef.current) > 2
        followBottomRef.current = moved
          ? userPinnedRef.current
          : gestureStartedNearRef.current
        if (followBottomRef.current) scrollToBottom()
      }, USER_SCROLL_IDLE_MS)
    }

    const beginGesture = () => {
      if (userScrollingRef.current) return
      gestureStartYRef.current = window.scrollY
      gestureStartedNearRef.current = isNearAnchor(bottomRef.current)
      userScrollingRef.current = true
    }

    const rememberPin = () => {
      const near = isNearAnchor(bottomRef.current)
      userPinnedRef.current = near
      if (!near) followBottomRef.current = false
    }

    const onWheel = (event: WheelEvent) => {
      if (nestedScrollerConsumes(event.target, event.deltaY)) return
      beginGesture()
      armIdle()
      requestAnimationFrame(() => {
        if (!userScrollingRef.current) return
        if (Math.abs(window.scrollY - gestureStartYRef.current) <= 2) return
        rememberPin()
      })
    }

    const onTouchMove = (event: TouchEvent) => {
      if (nestedScrollerConsumes(event.target, -1) || nestedScrollerConsumes(event.target, 1)) return
      beginGesture()
      armIdle()
    }

    const onScroll = () => {
      if (programmaticRef.current) return
      beginGesture()
      rememberPin()
      armIdle()
    }

    window.addEventListener('wheel', onWheel, { passive: true })
    window.addEventListener('touchmove', onTouchMove, { passive: true })
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('wheel', onWheel)
      window.removeEventListener('touchmove', onTouchMove)
      window.removeEventListener('scroll', onScroll)
      if (scrollIdleRef.current != null) window.clearTimeout(scrollIdleRef.current)
    }
  }, [scrollToBottom])

  useEffect(() => {
    if (userScrollingRef.current || !followBottomRef.current) return
    scrollToBottom()
  }, [turns, scrollToBottom])

  const reset = useCallback(() => {
    askGen.current += 1
    abortRef.current?.abort()
    draftRef.current = null
    loadingRef.current = false
    stickToBottom()
    contextRef.current = EMPTY_CONTEXT
    setTurns([])
    setContext(EMPTY_CONTEXT)
    setCiteTurnId(null)
    setQuestion('')
    setLoading(false)
  }, [stickToBottom])

  const ask = useCallback(async (q: string) => {
    const trimmed = q.trim()
    if (!trimmed || loadingRef.current) return

    abortRef.current?.abort()
    stickToBottom()
    const gen = ++askGen.current
    const controller = new AbortController()
    abortRef.current = controller
    const alive = () => askGen.current === gen

    const id = newTurnId()
    draftRef.current = { id, question: trimmed, answer: '' }
    answerCommittedRef.current = false
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
        titlesPending: false,
        status: '提交中…',
        error: '',
        stopped: false,
      },
    ])

    const applyTitles = (titles: Record<string, string>) => {
      setTurns((prev) =>
        prev.map((t) => {
          if (t.id !== id) return t
          return {
            ...t,
            titlesPending: false,
            articles: t.articles.map((a) => {
              const zh = titles[a.pmid]?.trim()
              if (!zh || zh === a.title || !HAN.test(zh)) return a
              return { ...a, title_zh: zh }
            }),
          }
        }),
      )
    }

    const requestTitleTranslations = (items: ArticleMeta[]) => {
      void (async () => {
        try {
          const res = await fetch('/api/translate-titles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              articles: items.map((a) => ({ pmid: a.pmid, title: a.title })),
            }),
          })
          if (!res.ok) {
            applyTitles({})
            return
          }
          const data = (await res.json()) as { titles?: Record<string, string> }
          applyTitles(data.titles ?? {})
        } catch {
          applyTitles({})
        }
      })()
    }

    let titleTranslationStarted = false

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
            const incoming = (event.articles as ArticleMeta[]) || []
            const startTranslate = !titleTranslationStarted
            if (startTranslate) titleTranslationStarted = true
            const english = incoming.filter((a) => needsTitleTranslation(a.title))
            setTurns((prev) =>
              prev.map((t) => {
                if (t.id !== id) return t
                return {
                  ...t,
                  articles: mergeArticleTitles(t.articles, incoming),
                  status: `已检索 ${event.count ?? 0} 篇文献，正在生成回答…`,
                  titlesPending:
                    startTranslate && english.length > 0 ? true : t.titlesPending,
                }
              }),
            )
            if (startTranslate && english.length > 0) {
              requestTitleTranslations(english)
            }
          } else if (type === 'token') {
            const piece = String(event.content || '')
            if (!alive()) return
            if (draftRef.current?.id === id) draftRef.current.answer += piece
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
              answerCommittedRef.current = true
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
      if (!alive()) return
      if ((e as Error).name === 'AbortError') return
      patch({ error: (e as Error).message || '请求失败', status: '' })
    } finally {
      if (alive()) {
        loadingRef.current = false
        setLoading(false)
      }
    }
  }, [stickToBottom])

  const stop = useCallback(() => {
    if (!loadingRef.current) return
    const draft = draftRef.current
    const last = turnsRef.current.at(-1)
    askGen.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    draftRef.current = null
    loadingRef.current = false
    setLoading(false)
    if (!last || last.error || last.stopped || !draft || draft.id !== last.id) return
    if (answerCommittedRef.current) {
      setTurns((prev) =>
        prev.map((t) => (t.id === last.id ? { ...t, status: '' } : t)),
      )
      return
    }
    const next = contextAfterStop(contextRef.current, draft)
    contextRef.current = next
    setContext(next)
    setTurns((prev) =>
      prev.map((t) => (t.id === last.id ? { ...t, status: '', stopped: true } : t)),
    )
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
                {turn.stopped && <p className="stopped">已停止生成</p>}
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
          className={loading ? 'stop' : undefined}
          aria-label={loading ? '停止生成' : '发送'}
          disabled={!loading && !question.trim()}
          onClick={() => (loading ? stop() : void ask(question))}
        >
          {loading ? (
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
              <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M5 12h14M13 6l6 6-6 6"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </button>
      </div>

      <footer className="footer">
        仅供科研/学习参考，不能替代临床诊疗。数据来源：PubMed / NCBI。
      </footer>
      {citeTurn && citeTurn.articles.length > 0 && (
        <CitationDialog
          articles={citeTurn.articles}
          translating={citeTurn.titlesPending}
          onClose={() => setCiteTurnId(null)}
        />
      )}
    </div>
  )
}

function CitationDialog({
  articles,
  translating,
  onClose,
}: {
  articles: ArticleMeta[]
  translating: boolean
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
        <h2 id="cite-dialog-title">
          依据文献（{articles.length}）
          {translating && <span className="cite-translating">正在翻译标题…</span>}
        </h2>
        <button type="button" className="cite-dialog-close" onClick={requestClose}>
          关闭
        </button>
      </div>
      <ul className="citations">
        {articles.map((a) => (
          <li key={a.pmid}>
            {a.title_zh && <p className="title-zh">{a.title_zh}</p>}
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
