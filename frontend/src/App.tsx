import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { citationOrder, linkifyCitations } from './citations'
import { exportMarkdown } from './exportMarkdown'
import {
  IconChat,
  IconCheck,
  IconChevron,
  IconClose,
  IconCopy,
  IconDown,
  IconDownload,
  IconMic,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconSend,
  IconSpark,
  IconStop,
} from './icons'
import {
  carryEvidence,
  EMPTY_CONTEXT,
  loadSessions,
  saveSessions,
  SESSION_LIMIT,
  type ArticleMeta,
  type ChatTurn,
  type Passage,
  type Session,
} from './history'
import { pubTypeLabel } from './pubTypes'
import { contextAfterStop, type ContextEnvelope } from './stopContext'
import { postTitleBatch, runTitleTranslation, titleSlots } from './titleTranslation'
import './App.css'

const EXAMPLES = [
  'SGLT2 抑制剂对心衰住院的影响',
  'GLP-1 受体激动剂与减重的证据',
  '阿司匹林一级预防心血管事件的获益与出血风险',
  '肺癌免疫治疗一线方案如何选择',
  '二甲双胍对糖尿病前期的预防证据',
  '他汀用于心血管疾病一级预防的适用人群',
  'HPV 疫苗接种年龄与保护效果',
  '奥希替尼用于 EGFR 突变肺癌的证据',
]

const EXAMPLE_PAGE = 4
const HAN = /[\u4e00-\u9fff]/
const NEAR_BOTTOM_PX = 16
const USER_SCROLL_IDLE_MS = 300

const STEPS = [
  { key: 'understand', label: '问题分析' },
  { key: 'search', label: '循证检索' },
  { key: 'evidence', label: '证据整理' },
  { key: 'answer', label: '生成' },
] as const

type StepState = 'done' | 'active' | 'wait' | 'stopped'

type AskOptions = {
  context?: ContextEnvelope
  replaceTurnId?: string
}

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

function formatWhen(ts: number): string {
  const date = new Date(ts)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function needsTitleTranslation(title: string): boolean {
  const text = title.trim()
  return text.length > 0 && !HAN.test(text)
}

function mergeArticleTitles(prev: ArticleMeta[], incoming: ArticleMeta[]): ArticleMeta[] {
  const translated = new Map(
    prev.flatMap((article) => (article.title_zh ? [[article.pmid, article.title_zh] as const] : [])),
  )
  return incoming.map((article) => {
    const title_zh = article.title_zh || translated.get(article.pmid)
    return title_zh ? { ...article, title_zh } : article
  })
}

function phaseIndex(phase: string): number {
  if (phase === 'search') return 1
  if (phase === 'fulltext' || phase === 'passages') return 2
  if (phase === 'answer' || phase === 'done') return 3
  return 0
}

function stepState(
  index: number,
  current: number,
  loading: boolean,
  stopped: boolean,
  error: boolean,
): StepState {
  if (index < current) return 'done'
  if (index > current) return 'wait'
  if (stopped || error) return 'stopped'
  if (loading) return 'active'
  return 'done'
}

const SECTION_LABEL: Record<string, string> = {
  intro: '引言',
  methods: '方法',
  results: '结果',
  discuss: '讨论',
  abstract: '摘要',
  other: '其他',
}

function sourceLabel(source: string, section?: string): string {
  const base = source === 'fulltext' ? '全文' : '摘要'
  const sec = SECTION_LABEL[section || '']
  return sec ? `${base} · ${sec}` : base
}

function articleTitle(article: ArticleMeta | undefined): string {
  return article?.title?.trim() || '文献'
}

function articleLinkLabel(article: ArticleMeta): string {
  const doi = (article.doi || '')
    .trim()
    .replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '')
    .replace(/^doi:\s*/i, '')
  if (doi) return `DOI:${doi}`
  const pmc = (article.pmcid || '').trim()
  if (pmc) return /^pmc/i.test(pmc) ? pmc.toUpperCase() : `PMC${pmc}`
  return `PMID:${article.pmid}`
}

async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.left = '-9999px'
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand('copy')
    area.remove()
    return ok
  }
}

function downloadName(question: string): string {
  const base = question.replace(/[\\/:*?"<>|\n\r]+/g, ' ').trim().slice(0, 40)
  return `${base || 'mkb'}.md`
}

function isNear(scroller: HTMLElement, anchor: HTMLElement): boolean {
  const delta = anchor.getBoundingClientRect().bottom - scroller.getBoundingClientRect().bottom
  return Math.abs(delta) <= NEAR_BOTTOM_PX
}

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 960px)').matches,
  )
  useEffect(() => {
    const media = window.matchMedia('(max-width: 960px)')
    const onChange = () => setNarrow(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  return narrow
}

function useThreadFollow(enabled: boolean, contentKey: string) {
  const threadRef = useRef<HTMLDivElement | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const followRef = useRef(true)
  const userScrollingRef = useRef(false)
  const sawUserScrollRef = useRef(false)
  const gestureStartRef = useRef(0)
  const lastScrollRef = useRef(0)
  const programmaticRef = useRef<number | null>(null)
  const idleRef = useRef<number | null>(null)
  const [away, setAway] = useState(false)

  const scrollToBottom = useCallback(() => {
    const scroller = threadRef.current
    const anchor = bottomRef.current
    if (!scroller || !anchor || userScrollingRef.current || !followRef.current) return
    if (isNear(scroller, anchor)) return
    const dest = scroller.scrollHeight - scroller.clientHeight
    programmaticRef.current = dest
    scroller.scrollTop = dest
  }, [])

  const stick = useCallback(() => {
    followRef.current = true
    userScrollingRef.current = false
    sawUserScrollRef.current = false
    programmaticRef.current = null
    if (idleRef.current != null) {
      window.clearTimeout(idleRef.current)
      idleRef.current = null
    }
    setAway(false)
    const scroller = threadRef.current
    if (!scroller) return
    const dest = Math.max(0, scroller.scrollHeight - scroller.clientHeight)
    programmaticRef.current = dest
    scroller.scrollTop = dest
  }, [])

  useEffect(() => {
    const scroller = threadRef.current
    if (!enabled || !scroller) return

    const clearIdle = () => {
      if (idleRef.current != null) {
        window.clearTimeout(idleRef.current)
        idleRef.current = null
      }
    }

    const armIdle = () => {
      clearIdle()
      idleRef.current = window.setTimeout(() => {
        idleRef.current = null
        const anchor = bottomRef.current
        const movedByPosition = Math.abs(scroller.scrollTop - gestureStartRef.current) > 2
        const hadUserScrollEvent = sawUserScrollRef.current
        const userMoved = hadUserScrollEvent || movedByPosition
        userScrollingRef.current = false
        sawUserScrollRef.current = false
        if (!userMoved) return
        if (!hadUserScrollEvent && anchor) followRef.current = isNear(scroller, anchor)
        setAway(!followRef.current)
        if (followRef.current) scrollToBottom()
      }, USER_SCROLL_IDLE_MS)
    }

    const beginSuppress = () => {
      if (!userScrollingRef.current) {
        gestureStartRef.current = scroller.scrollTop
        sawUserScrollRef.current = false
      }
      userScrollingRef.current = true
      armIdle()
    }

    const onScroll = () => {
      const y = scroller.scrollTop
      if (programmaticRef.current != null && Math.abs(y - programmaticRef.current) <= 2) {
        programmaticRef.current = null
        lastScrollRef.current = y
        return
      }
      programmaticRef.current = null
      const moved = Math.abs(y - lastScrollRef.current) > 2
      lastScrollRef.current = y
      if (!moved) return
      sawUserScrollRef.current = true
      userScrollingRef.current = true
      const anchor = bottomRef.current
      followRef.current = anchor ? isNear(scroller, anchor) : false
      setAway(!followRef.current)
      armIdle()
    }

    scroller.addEventListener('wheel', beginSuppress, { passive: true })
    scroller.addEventListener('touchmove', beginSuppress, { passive: true })
    scroller.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      scroller.removeEventListener('wheel', beginSuppress)
      scroller.removeEventListener('touchmove', beginSuppress)
      scroller.removeEventListener('scroll', onScroll)
      clearIdle()
    }
  }, [enabled, scrollToBottom])

  useEffect(() => {
    if (!enabled || userScrollingRef.current || !followRef.current) return
    scrollToBottom()
  }, [enabled, contentKey, scrollToBottom])

  return { threadRef, bottomRef, stick, away }
}

function AnswerBody({ text, onCite }: { text: string; onCite: (pmid: string) => void }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ href, children }) {
            if (href?.startsWith('#cite-')) {
              const pmid = decodeURIComponent(href.slice('#cite-'.length))
              return (
                <button type="button" className="cite-chip" onClick={() => onCite(pmid)}>
                  {children}
                </button>
              )
            }
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            )
          },
        }}
      >
        {linkifyCitations(text)}
      </ReactMarkdown>
    </div>
  )
}

function PhaseStepper({ turn, loading }: { turn: ChatTurn; loading: boolean }) {
  const [open, setOpen] = useState(true)
  const current = phaseIndex(turn.phase)
  const finished = !loading && !turn.error && !turn.stopped && turn.phase === 'done'
  const head = finished ? '循证思考完成' : turn.stopped ? '已停止' : turn.error ? '出错了' : '循证思考中'

  return (
    <div>
      <button type="button" className="steps-head" onClick={() => setOpen((value) => !value)}>
        <IconChevron className={open ? 'chev open' : 'chev'} />
        {head}
      </button>
      {open && (
        <ol className="steps">
          {STEPS.map((step, index) => {
            const skipped =
              turn.retrieval === false && (step.key === 'search' || step.key === 'evidence')
            const state = skipped
              ? 'skip'
              : stepState(index, current, loading, turn.stopped, Boolean(turn.error))
            const suffix =
              state === 'done' ? '完成' : state === 'active' ? '中' : state === 'skip' ? '（未进行）' : ''
            const detail =
              state === 'active' && loading
                ? turn.status || (step.key === 'answer' ? '正在生成回答…' : '')
                : ''
            return (
              <li key={step.key} className={state}>
                <span className={`mark ${state}`}>
                  {state === 'done' && <IconCheck />}
                  {state === 'stopped' && <IconClose />}
                </span>
                <div>
                  <div>
                    {step.label}
                    {suffix}
                  </div>
                  {detail && (
                    <div className="step-detail" aria-live="polite">
                      {detail}
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}

function citedRows(turn: ChatTurn) {
  const order = citationOrder(turn.answer)
  const byPmid = new Map(turn.articles.map((article) => [article.pmid, article]))
  return order.map((pmid, index) => ({
    pmid,
    number: index + 1,
    article: byPmid.get(pmid),
  }))
}

function RefCard({
  turnId,
  pmid,
  number,
  article,
  passages,
  active,
  translating,
  onToggle,
}: {
  turnId: string
  pmid: string
  number?: number
  article?: ArticleMeta
  passages: Passage[]
  active: boolean
  translating: boolean
  onToggle: (pmid: string) => void
}) {
  const label = article ? pubTypeLabel(article.pub_types) : ''
  const retracted = (article?.pub_types ?? []).some(
    (item) => item.trim() === 'Retracted Publication',
  )
  const cites = passages.length
  const showPending =
    translating && !article?.title_zh && needsTitleTranslation(article?.title || '')
  return (
    <article id={`ref-${turnId}-${pmid}`} className={active ? 'ref-card active' : 'ref-card'}>
      <div className="ref-kicker">
        {number != null && <span>{number}.</span>}
        {label && (
          <span className={retracted ? 'pmid-badge retracted' : 'pmid-badge'}>{label}</span>
        )}
      </div>
      <p className="title">{articleTitle(article)}</p>
      {article?.title_zh && <p className="title-zh">{article.title_zh}</p>}
      {showPending && <p className="title-zh title-zh-pending">翻译中…</p>}
      {article ? (
        <p className="meta">
          {[article.journal, article.year, article.authors].filter(Boolean).join(' · ')}
          {article.has_fulltext ? ' · 已用全文' : ''}
        </p>
      ) : (
        <p className="meta">未出现在本次检索结果中</p>
      )}
      {article && (
        <a href={article.url} target="_blank" rel="noreferrer">
          {articleLinkLabel(article)}
        </a>
      )}
      <div className="expand-row">
        <button type="button" className="linkish" onClick={() => onToggle(pmid)}>
          {cites > 0 ? `${cites} 处引用` : '引用'}
          <IconChevron className={active ? 'chev open' : 'chev'} />
          {active ? '收起' : '展开引用'}
        </button>
      </div>
      {active && passages.length > 0 &&
        passages.map((passage, index) => (
          <blockquote key={`${passage.source}-${index}`} className="passage">
            <span>{sourceLabel(passage.source, passage.section)}</span>
            <p>{passage.text}</p>
          </blockquote>
        ))}
      {active && passages.length === 0 && <p className="passage-empty">本轮没有留下可展开的段落。</p>}
    </article>
  )
}

function ReferenceList({
  turn,
  activePmid,
  onToggle,
}: {
  turn: ChatTurn
  activePmid: string
  onToggle: (pmid: string) => void
}) {
  const cited = citedRows(turn)
  const citedIds = new Set(cited.map((item) => item.pmid))
  const uncited = turn.articles.filter((article) => !citedIds.has(article.pmid))
  const passagesFor = (pmid: string) => turn.passages.filter((passage) => passage.pmid === pmid)

  return (
    <div className="ref-scroll">
      {cited.length > 0 && (
        <section className="ref-group">
          <h3>引用文献</h3>
          {cited.map((item) => (
            <RefCard
              key={item.pmid}
              turnId={turn.id}
              pmid={item.pmid}
              number={item.number}
              article={item.article}
              passages={passagesFor(item.pmid)}
              active={activePmid === item.pmid}
              translating={turn.titlesPending}
              onToggle={onToggle}
            />
          ))}
        </section>
      )}
      {uncited.length > 0 && (
        <section className="ref-group">
          <h3>{cited.length > 0 ? '已检索未引用' : '已检索文献'}</h3>
          {uncited.map((article) => (
            <RefCard
              key={article.pmid}
              turnId={turn.id}
              pmid={article.pmid}
              article={article}
              passages={passagesFor(article.pmid)}
              active={activePmid === article.pmid}
              translating={turn.titlesPending}
              onToggle={onToggle}
            />
          ))}
        </section>
      )}
    </div>
  )
}

function ReferenceDialog({
  turn,
  activePmid,
  onToggle,
  onClose,
}: {
  turn: ChatTurn
  activePmid: string
  onToggle: (pmid: string) => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current
    if (!dialog || dialog.open) return
    dialog.showModal()
  }, [])

  return (
    <dialog
      ref={ref}
      className="cite-dialog"
      aria-labelledby="cite-dialog-title"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          if (ref.current?.open) ref.current.close()
          else onClose()
        }
      }}
    >
      <div className="cite-dialog-head">
        <h2 id="cite-dialog-title">
          参考文献（{turn.articles.length}）
          {turn.titlesPending && <span className="cite-translating">正在翻译标题…</span>}
        </h2>
        <button
          type="button"
          className="cite-dialog-close"
          aria-label="关闭"
          onClick={() => {
            if (ref.current?.open) ref.current.close()
            else onClose()
          }}
        >
          <IconClose />
        </button>
      </div>
      <ReferenceList turn={turn} activePmid={activePmid} onToggle={onToggle} />
    </dialog>
  )
}

function ComposerBox({
  question,
  loading,
  placeholder,
  onChange,
  onSubmit,
  onStop,
}: {
  question: string
  loading: boolean
  placeholder: string
  onChange: (value: string) => void
  onSubmit: () => void
  onStop: () => void
}) {
  return (
    <div className="composer">
      <textarea
        value={question}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        rows={3}
        disabled={loading}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            if (!loading) onSubmit()
          }
        }}
      />
      <div className="composer-tools">
        <button type="button" className="mic" disabled aria-label="语音输入暂未开放" title="语音输入暂未开放">
          <IconMic />
        </button>
        <button
          type="button"
          className={loading ? 'send stop' : 'send'}
          aria-label={loading ? '停止生成' : '发送'}
          disabled={!loading && !question.trim()}
          onClick={() => (loading ? onStop() : onSubmit())}
        >
          {loading ? <IconStop /> : <IconSend />}
        </button>
      </div>
    </div>
  )
}

function App() {
  const [sessions, setSessions] = useState<Session[]>(() => loadSessions())
  const [activeId, setActiveId] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [examplePage, setExamplePage] = useState(0)
  const [panelOpen, setPanelOpen] = useState(false)
  const [citeFocus, setCiteFocus] = useState<{ turnId: string; pmid: string } | null>(null)
  const [expandedRefs, setExpandedRefs] = useState<Record<string, boolean>>({})
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const narrow = useNarrow()

  const active = sessions.find((session) => session.id === activeId) ?? null
  const turns = active?.turns ?? []
  const contentKey = turns.map((turn) => `${turn.id}:${turn.answer.length}:${turn.status}`).join('|')
  const { threadRef, bottomRef, stick, away } = useThreadFollow(turns.length > 0, contentKey)

  const abortRef = useRef<AbortController | null>(null)
  const titleAbortRef = useRef(new Map<string, AbortController>())
  const contextRef = useRef<ContextEnvelope>(EMPTY_CONTEXT)
  const sessionsRef = useRef(sessions)
  const turnsRef = useRef(turns)
  const activeIdRef = useRef<string | null>(activeId)
  const draftRef = useRef<{ id: string; question: string; answer: string } | null>(null)
  const answerCommittedRef = useRef(false)
  const askGen = useRef(0)
  const loadingRef = useRef(false)
  const latestArticleTurnId = [...turns].reverse().find((turn) => turn.articles.length > 0)?.id ?? ''
  const [trackedArticleTurn, setTrackedArticleTurn] = useState('')
  if (latestArticleTurnId !== trackedArticleTurn) {
    setTrackedArticleTurn(latestArticleTurnId)
    if (latestArticleTurnId) {
      setCiteFocus((prev) =>
        prev?.turnId === latestArticleTurnId ? prev : { turnId: latestArticleTurnId, pmid: '' },
      )
      if (!narrow) setPanelOpen(true)
    }
  }

  useEffect(() => {
    sessionsRef.current = sessions
    turnsRef.current = turns
    activeIdRef.current = activeId
  })

  useEffect(() => {
    const timer = window.setTimeout(() => saveSessions(sessions), 400)
    return () => window.clearTimeout(timer)
  }, [sessions])

  useEffect(() => {
    const save = () => saveSessions(sessionsRef.current)
    window.addEventListener('beforeunload', save)
    return () => window.removeEventListener('beforeunload', save)
  }, [])

  useEffect(() => {
    if (!panelOpen || !citeFocus?.pmid) return
    document.getElementById(`ref-${citeFocus.turnId}-${citeFocus.pmid}`)?.scrollIntoView({
      block: 'nearest',
    })
  }, [panelOpen, citeFocus])

  const patchSession = useCallback(
    (sessionId: string, turnId: string, partial: Partial<ChatTurn>, context?: ContextEnvelope) => {
      setSessions((prev) =>
        prev.map((session) => {
          if (session.id !== sessionId) return session
          return {
            ...session,
            updatedAt: Date.now(),
            context: context ?? session.context,
            turns: session.turns.map((turn) => (turn.id === turnId ? { ...turn, ...partial } : turn)),
          }
        }),
      )
    },
    [],
  )

  const stop = useCallback(() => {
    if (!loadingRef.current) return
    const draft = draftRef.current
    const sessionId = activeIdRef.current
    const last = turnsRef.current.at(-1)
    askGen.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    draftRef.current = null
    loadingRef.current = false
    setLoading(false)
    if (!sessionId || !last || last.error || last.stopped || !draft || draft.id !== last.id) return
    if (answerCommittedRef.current) {
      patchSession(sessionId, last.id, { status: '', phase: 'done' })
      return
    }
    const next = contextAfterStop(contextRef.current, draft)
    contextRef.current = next
    patchSession(sessionId, last.id, { status: '', stopped: true }, next)
  }, [patchSession])

  const ask = useCallback(
    async (q: string, options?: AskOptions) => {
      const trimmed = q.trim()
      if (!trimmed || loadingRef.current) return

      abortRef.current?.abort()
      if (options?.replaceTurnId) titleAbortRef.current.get(options.replaceTurnId)?.abort()
      stick()
      const gen = ++askGen.current
      const controller = new AbortController()
      abortRef.current = controller
      const alive = () => askGen.current === gen
      const contextBefore = structuredClone(options?.context ?? contextRef.current)
      contextRef.current = contextBefore

      let sessionId = activeIdRef.current
      const creating = !sessionId
      if (!sessionId) sessionId = newTurnId()
      activeIdRef.current = sessionId
      setActiveId(sessionId)

      const turnId = newTurnId()
      const turn: ChatTurn = {
        id: turnId,
        question: trimmed,
        answer: '',
        queries: [],
        standalone: '',
        relation: '',
        retrieval: null,
        articles: [],
        passages: [],
        suggestions: [],
        titlesPending: false,
        status: '提交中…',
        phase: 'understand',
        error: '',
        stopped: false,
        contextBefore,
      }
      draftRef.current = { id: turnId, question: trimmed, answer: '' }
      answerCommittedRef.current = false
      loadingRef.current = true
      setLoading(true)
      setQuestion('')

      setSessions((prev) => {
        let next = prev
        if (creating || !prev.some((session) => session.id === sessionId)) {
          const title = trimmed.replace(/\s+/g, ' ').slice(0, 42)
          next = [
            {
              id: sessionId!,
              title,
              updatedAt: Date.now(),
              turns: [],
              context: contextBefore,
            },
            ...prev,
          ].slice(0, SESSION_LIMIT)
        }
        return next.map((session) => {
          if (session.id !== sessionId) return session
          const kept = options?.replaceTurnId
            ? session.turns.filter((item) => item.id !== options.replaceTurnId)
            : session.turns
          return {
            ...session,
            updatedAt: Date.now(),
            context: contextBefore,
            turns: [...kept, turn],
          }
        })
      })

      const mergeTitleMap = (titles: Record<string, string>) => {
        setSessions((prev) =>
          prev.map((session) => {
            if (session.id !== sessionId) return session
            return {
              ...session,
              turns: session.turns.map((item) => {
                if (item.id !== turnId) return item
                let changed = false
                const articles = item.articles.map((article) => {
                  const raw = titles[article.pmid]
                  const zh = typeof raw === 'string' ? raw.trim() : ''
                  if (!zh || zh === article.title || zh === article.title_zh || !HAN.test(zh)) return article
                  changed = true
                  return { ...article, title_zh: zh }
                })
                return changed ? { ...item, articles } : item
              }),
            }
          }),
        )
      }

      const setTitlesPending = (pending: boolean) => {
        setSessions((prev) =>
          prev.map((session) => {
            if (session.id !== sessionId) return session
            return {
              ...session,
              turns: session.turns.map((item) =>
                item.id === turnId && item.titlesPending !== pending ? { ...item, titlesPending: pending } : item,
              ),
            }
          }),
        )
      }

      const requestTitleTranslations = (items: ArticleMeta[]) => {
        titleAbortRef.current.get(turnId)?.abort()
        const titleAbort = new AbortController()
        titleAbortRef.current.set(turnId, titleAbort)
        // 不跟回答共用 AbortController：停止生成或接着追问时，这一轮已开始的翻译仍写回。
        void runTitleTranslation({
          articles: items,
          answer: () =>
            sessionsRef.current
              .find((session) => session.id === sessionId)
              ?.turns.find((item) => item.id === turnId)?.answer ?? '',
          signal: titleAbort.signal,
          limiter: titleSlots,
          fetchTitles: postTitleBatch,
          onTitles: mergeTitleMap,
        }).finally(() => {
          if (titleAbortRef.current.get(turnId) !== titleAbort) return
          titleAbortRef.current.delete(turnId)
          setTitlesPending(false)
        })
      }

      let titleTranslationStarted = false
      let sawDone = false
      let sawError = false
      const patch = (partial: Partial<ChatTurn>, context?: ContextEnvelope) => {
        if (!alive()) return
        patchSession(sessionId!, turnId, partial, context)
      }

      try {
        const res = await fetch('/api/ask', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: trimmed, context: contextBefore }),
          signal: controller.signal,
        })
        if (!res.ok || !res.body) throw new Error(`请求失败 (${res.status})`)

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) buffer += decoder.decode()
          else {
            if (!alive()) return
            buffer += decoder.decode(value, { stream: true })
          }
          const parts = buffer.split('\n\n')
          buffer = done ? '' : parts.pop() || ''
          const pending = done ? parts.filter((part) => part.trim()) : parts
          for (const part of pending) {
            if (!alive()) return
            const line = part.split('\n').find((item) => item.startsWith('data:'))
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
              const partial: Partial<ChatTurn> = { status: String(event.message || '') }
              if (typeof event.phase === 'string' && event.phase) partial.phase = event.phase
              patch(partial)
            } else if (type === 'queries') {
              const retrieval = Boolean(event.retrieval)
              const queryPatch: Partial<ChatTurn> = {
                queries: (event.queries as string[]) || [],
                standalone: String(event.standalone_question || ''),
                relation: String(event.relation || ''),
                retrieval,
                phase: retrieval ? 'search' : 'passages',
              }
              const knownTurns =
                sessionsRef.current.find((session) => session.id === sessionId)?.turns ?? []
              const carried = retrieval
                ? []
                : (carryEvidence(knownTurns, turnId).find((item) => item.id === turnId)?.articles ?? [])
              if (!alive()) return
              setSessions((prev) =>
                prev.map((session) => {
                  if (session.id !== sessionId) return session
                  const nextTurns = retrieval ? session.turns : carryEvidence(session.turns, turnId)
                  return {
                    ...session,
                    updatedAt: Date.now(),
                    turns: nextTurns.map((item) => (item.id === turnId ? { ...item, ...queryPatch } : item)),
                  }
                }),
              )
              const untranslated = carried.filter(
                (article) => needsTitleTranslation(article.title) && !article.title_zh,
              )
              if (untranslated.length > 0) {
                patch({ titlesPending: true })
                requestTitleTranslations(untranslated)
              }
            } else if (type === 'meta') {
              const incoming = (event.articles as ArticleMeta[]) || []
              const startTranslate = !titleTranslationStarted
              if (startTranslate) titleTranslationStarted = true
              const english = incoming.filter((article) => needsTitleTranslation(article.title))
              if (!alive()) return
              setSessions((prev) =>
                prev.map((session) => {
                  if (session.id !== sessionId) return session
                  return {
                    ...session,
                    updatedAt: Date.now(),
                    turns: session.turns.map((item) => {
                      if (item.id !== turnId) return item
                      return {
                        ...item,
                        articles: mergeArticleTitles(item.articles, incoming),
                        titlesPending:
                          startTranslate && english.length > 0 ? true : item.titlesPending,
                      }
                    }),
                  }
                }),
              )
              if (startTranslate && english.length > 0) requestTitleTranslations(english)
            } else if (type === 'passages') {
              const items = Array.isArray(event.items) ? (event.items as Passage[]) : []
              patch({ passages: items })
            } else if (type === 'token') {
              const piece = String(event.content || '')
              if (!alive()) return
              if (draftRef.current?.id === turnId) draftRef.current.answer += piece
              setSessions((prev) =>
                prev.map((session) => {
                  if (session.id !== sessionId) return session
                  return {
                    ...session,
                    updatedAt: Date.now(),
                    turns: session.turns.map((item) =>
                      item.id === turnId
                        ? { ...item, answer: item.answer + piece, status: '', phase: 'answer' }
                        : item,
                    ),
                  }
                }),
              )
            } else if (type === 'suggestions') {
              const questions = Array.isArray(event.questions)
                ? event.questions.filter((item): item is string => typeof item === 'string').slice(0, 3)
                : []
              patch({ suggestions: questions })
            } else if (type === 'context') {
              const next = event.context as ContextEnvelope
              if (next && alive()) {
                answerCommittedRef.current = true
                contextRef.current = next
                patch({}, next)
              }
            } else if (type === 'error') {
              sawError = true
              patch({ error: String(event.message || '未知错误'), status: '' })
            } else if (type === 'done') {
              sawDone = true
              patch({ status: '', phase: 'done' })
            }
          }
          if (done) break
        }
        if (alive() && !sawDone && !sawError) {
          patch({ stopped: true, status: '' })
        }
      } catch (error) {
        if (!alive()) return
        if ((error as Error).name === 'AbortError') return
        patch({ error: (error as Error).message || '请求失败', status: '' })
      } finally {
        if (alive()) {
          loadingRef.current = false
          setLoading(false)
        }
      }
    },
    [patchSession, stick],
  )

  const newChat = useCallback(() => {
    if (loadingRef.current) stop()
    activeIdRef.current = null
    setActiveId(null)
    contextRef.current = EMPTY_CONTEXT
    setQuestion('')
    setPanelOpen(false)
    setCiteFocus(null)
    stick()
  }, [stick, stop])

  const openSession = useCallback(
    (id: string) => {
      const switching = activeIdRef.current !== id
      if (!switching) return
      if (loadingRef.current) stop()
      const session = sessionsRef.current.find((item) => item.id === id)
      if (!session) return
      activeIdRef.current = id
      setActiveId(id)
      contextRef.current = session.context
      setQuestion('')
      stick()
    },
    [stick, stop],
  )

  const removeSession = useCallback(
    (id: string) => {
      const removed = sessionsRef.current.find((session) => session.id === id)
      removed?.turns.forEach((turn) => titleAbortRef.current.get(turn.id)?.abort())
      if (loadingRef.current && activeIdRef.current === id) stop()
      setSessions((prev) => prev.filter((session) => session.id !== id))
      if (activeIdRef.current === id) {
        activeIdRef.current = null
        setActiveId(null)
        contextRef.current = EMPTY_CONTEXT
        setPanelOpen(false)
        setCiteFocus(null)
      }
    },
    [stop],
  )

  const focusCitation = (turnId: string, pmid: string) => {
    setCiteFocus({ turnId, pmid })
    setPanelOpen(true)
  }

  const panelTurn =
    turns.find((turn) => turn.id === citeFocus?.turnId && turn.articles.length > 0) ??
    [...turns].reverse().find((turn) => turn.articles.length > 0) ??
    null
  const showAside = panelOpen && !narrow && Boolean(panelTurn)
  const showDialog = panelOpen && narrow && Boolean(panelTurn)
  const shownExamples = Array.from(
    { length: EXAMPLE_PAGE },
    (_, index) => EXAMPLES[(examplePage * EXAMPLE_PAGE + index) % EXAMPLES.length],
  )
  const copyTurn = async (turn: ChatTurn) => {
    const text = `# ${turn.question}\n\n${turn.answer}\n`
    if (!(await writeClipboard(text))) return
    setCopiedId(turn.id)
    window.setTimeout(() => setCopiedId((current) => (current === turn.id ? null : current)), 1600)
  }

  const downloadTurn = (turn: ChatTurn) => {
    const blob = new Blob([exportMarkdown(turn)], {
      type: 'text/markdown;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = downloadName(turn.question)
    link.click()
    URL.revokeObjectURL(url)
  }

  const placeholder =
    turns.length > 0
      ? '继续追问，例如：那女性患者呢？或：把上一回答缩短'
      : '文献调研、前沿进展、用药指导、诊断评估...在此提问快速获取答案'

  return (
    <div className="shell">
      <div className="main">
        {turns.length > 0 && (
          <div className="main-bar">
            <div className="main-title">{active?.title}</div>
            <button type="button" className="new-chat" onClick={newChat}>
              <IconPlus />
              <span>新对话</span>
            </button>
          </div>
        )}

        {turns.length === 0 ? (
          <div className="hero">
            <div className="greet">
              <h1>
                Hi~我是 <span>MKB</span>
                <IconSpark className="greet-spark" />
              </h1>
              <p>你的专业医学 AI 助手</p>
            </div>
            <ComposerBox
              question={question}
              loading={loading}
              placeholder={placeholder}
              onChange={setQuestion}
              onSubmit={() => void ask(question)}
              onStop={stop}
            />
            {sessions.length > 0 && (
              <section className="history-card" aria-label="历史记录">
                <div className="history-label">历史记录</div>
                <ul className="history">
                  {sessions.map((session) => (
                    <li key={session.id} className="history-item">
                      <button type="button" className="history-open" onClick={() => openSession(session.id)}>
                        <span className="history-title">{session.title}</span>
                        <span className="history-time">{formatWhen(session.updatedAt)}</span>
                      </button>
                      <button
                        type="button"
                        className="history-delete"
                        aria-label={`删除 ${session.title}`}
                        onClick={() => removeSession(session.id)}
                      >
                        <IconClose />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <section className="ask-card">
              <div className="ask-head">
                <strong>可以这么问</strong>
                <button
                  type="button"
                  onClick={() =>
                    setExamplePage((page) => (page + 1) % Math.ceil(EXAMPLES.length / EXAMPLE_PAGE))
                  }
                >
                  <IconRefresh />
                  换一批
                </button>
              </div>
              <div className="ask-list">
                {shownExamples.map((example) => (
                  <button
                    key={example}
                    type="button"
                    className="ask-item"
                    disabled={loading}
                    onClick={() => void ask(example)}
                  >
                    {example}
                  </button>
                ))}
              </div>
            </section>
          </div>
        ) : (
          <div className="thread-wrap">
            <div className="thread" ref={threadRef}>
              {turns.map((turn, index) => {
                const turnLoading = loading && index === turns.length - 1
                const idle = !turnLoading
                const cited = citedRows(turn)
                const visibleRefs = expandedRefs[turn.id] ? cited : cited.slice(0, 4)
                const topic =
                  turn.relation === 'rephrase' ? turn.question : turn.standalone || turn.question
                return (
                  <article key={turn.id} className="turn">
                    <div className="bubble user">{turn.question}</div>
                    <div className="bubble assistant">
                      <PhaseStepper turn={turn} loading={turnLoading} />
                      {turn.relation === 'follow_up' &&
                        turn.standalone &&
                        turn.standalone !== turn.question && (
                          <p className="queries">理解为本轮问题：{turn.standalone}</p>
                        )}
                      {turn.retrieval === false && !turn.error && (
                        <p className="queries">本轮未重新检索文献</p>
                      )}
                      {turn.error && <div className="error">{turn.error}</div>}
                      {turn.answer && (
                        <AnswerBody text={turn.answer} onCite={(pmid) => focusCitation(turn.id, pmid)} />
                      )}
                      {turn.stopped && <p className="stopped">已停止生成</p>}
                      {cited.length > 0 && (
                        <div className="ref-inline">
                          <h3>参考文献 {cited.length} 篇</h3>
                          <ol>
                            {visibleRefs.map((item) => (
                              <li key={item.pmid}>
                                {item.article?.title_zh || articleTitle(item.article)}
                              </li>
                            ))}
                          </ol>
                          {cited.length > 4 && (
                            <button
                              type="button"
                              className="linkish"
                              onClick={() =>
                                setExpandedRefs((prev) => ({ ...prev, [turn.id]: !prev[turn.id] }))
                              }
                            >
                              {expandedRefs[turn.id] ? '收起' : '展开全部'}
                            </button>
                          )}
                        </div>
                      )}
                      {turn.articles.length > 0 && (
                        <button type="button" className="cite-open" onClick={() => focusCitation(turn.id, '')}>
                          参考文献（{turn.articles.length}）
                        </button>
                      )}
                      {idle && turn.answer && (
                        <div className="icon-actions">
                          {index === turns.length - 1 && (
                            <button
                              type="button"
                              className="icon-btn"
                              aria-label="重新生成"
                              disabled={loading}
                              onClick={() =>
                                void ask(turn.question, {
                                  context: turn.contextBefore,
                                  replaceTurnId: turn.id,
                                })
                              }
                            >
                              <IconRefresh />
                            </button>
                          )}
                          <button type="button" className="icon-btn" aria-label="下载" onClick={() => downloadTurn(turn)}>
                            <IconDownload />
                          </button>
                          <button
                            type="button"
                            className="icon-btn"
                            aria-label={copiedId === turn.id ? '已复制' : '复制'}
                            onClick={() => void copyTurn(turn)}
                          >
                            <IconCopy />
                          </button>
                        </div>
                      )}
                      {idle && index === turns.length - 1 && turn.answer && (
                        <div className="next-block">
                          <p className="next-label">
                            <IconSpark />
                            下一步建议
                          </p>
                          <button
                            type="button"
                            className="next-card"
                            disabled={loading}
                            onClick={() => void ask(`请围绕「${topic}」补充尚未引用的文献证据`)}
                          >
                            <span>
                              <strong>找更多文献</strong>
                              <span>更多证据验证观点</span>
                            </span>
                            <IconSearch />
                          </button>
                        </div>
                      )}
                      {idle && turn.suggestions.length > 0 && (
                        <div className="suggest-block">
                          <p className="suggest-label">
                            <IconChat />
                            继续问
                          </p>
                          <div className="suggests">
                            {turn.suggestions.map((item) => (
                              <button
                                key={item}
                                type="button"
                                className="suggest"
                                disabled={loading}
                                onClick={() => void ask(item)}
                              >
                                {item}
                                <IconChevron />
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </article>
                )
              })}
              <div ref={bottomRef} />
            </div>
            {away && (
              <button type="button" className="jump" aria-label="回到底部" onClick={stick}>
                <IconDown />
              </button>
            )}
          </div>
        )}

        {turns.length > 0 && (
          <div className="composer-dock">
            <ComposerBox
              question={question}
              loading={loading}
              placeholder={placeholder}
              onChange={setQuestion}
              onSubmit={() => void ask(question)}
              onStop={stop}
            />
          </div>
        )}
        <p className="footer">MKB 基于文献作答，生成内容供参考，不能替代临床诊疗。</p>
      </div>

      {showAside && panelTurn && (
        <aside className="refs">
          <div className="refs-head">
            <h2>
              参考文献（{panelTurn.articles.length}）
              {panelTurn.titlesPending && <span className="cite-translating">正在翻译标题…</span>}
            </h2>
            <button type="button" className="refs-close" aria-label="关闭参考文献" onClick={() => setPanelOpen(false)}>
              <IconClose />
            </button>
          </div>
          <ReferenceList
            turn={panelTurn}
            activePmid={citeFocus?.turnId === panelTurn.id ? citeFocus.pmid : ''}
            onToggle={(pmid) =>
              setCiteFocus((prev) =>
                prev?.turnId === panelTurn.id && prev.pmid === pmid
                  ? { turnId: panelTurn.id, pmid: '' }
                  : { turnId: panelTurn.id, pmid },
              )
            }
          />
        </aside>
      )}

      {showDialog && panelTurn && (
        <ReferenceDialog
          turn={panelTurn}
          activePmid={citeFocus?.turnId === panelTurn.id ? citeFocus.pmid : ''}
          onToggle={(pmid) =>
            setCiteFocus((prev) =>
              prev?.turnId === panelTurn.id && prev.pmid === pmid
                ? { turnId: panelTurn.id, pmid: '' }
                : { turnId: panelTurn.id, pmid },
            )
          }
          onClose={() => setPanelOpen(false)}
        />
      )}
    </div>
  )
}

export default App
