import { contextAfterStop, type ContextEnvelope } from './stopContext.ts'

export const STORAGE_KEY = 'mkb.sessions.v1'
export const SESSION_LIMIT = 30

export const EMPTY_CONTEXT: ContextEnvelope = {
  summary: '',
  recent: [],
  last_answer: '',
}

export type ArticleMeta = {
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
  pub_types?: string[]
}

export type Passage = {
  pmid: string
  source: string
  text: string
  section?: string
}

export type ChatTurn = {
  id: string
  question: string
  answer: string
  queries: string[]
  standalone: string
  relation: string
  retrieval: boolean | null
  articles: ArticleMeta[]
  passages: Passage[]
  suggestions: string[]
  titlesPending: boolean
  status: string
  phase: string
  error: string
  stopped: boolean
  contextBefore: ContextEnvelope
}

export type Session = {
  id: string
  title: string
  updatedAt: number
  turns: ChatTurn[]
  context: ContextEnvelope
}

function asContext(value: unknown): ContextEnvelope {
  if (!value || typeof value !== 'object') return EMPTY_CONTEXT
  const raw = value as Partial<ContextEnvelope>
  return {
    summary: typeof raw.summary === 'string' ? raw.summary : '',
    recent: Array.isArray(raw.recent) ? raw.recent : [],
    last_answer: typeof raw.last_answer === 'string' ? raw.last_answer : '',
  }
}

function storedArticles(value: unknown): ArticleMeta[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is ArticleMeta => {
    if (!item || typeof item !== 'object') return false
    return typeof (item as ArticleMeta).pmid === 'string'
  })
}

function storedPassages(value: unknown): Passage[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is Passage => {
    if (!item || typeof item !== 'object') return false
    const passage = item as Passage
    return typeof passage.pmid === 'string' && typeof passage.text === 'string'
  })
}

function normalizeTurn(value: unknown): ChatTurn | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Partial<ChatTurn>
  if (typeof raw.id !== 'string' || typeof raw.question !== 'string') return null
  const answer = typeof raw.answer === 'string' ? raw.answer : ''
  const phase = typeof raw.phase === 'string' && raw.phase ? raw.phase : 'done'
  const error = typeof raw.error === 'string' ? raw.error : ''
  // A finished turn always stores phase "done". Anything else was saved mid-stream.
  const stopped = Boolean(raw.stopped) || (!error && phase !== 'done')
  return {
    id: raw.id,
    question: raw.question,
    answer,
    queries: Array.isArray(raw.queries)
      ? raw.queries.filter((item): item is string => typeof item === 'string')
      : [],
    standalone: typeof raw.standalone === 'string' ? raw.standalone : '',
    relation: typeof raw.relation === 'string' ? raw.relation : '',
    retrieval: typeof raw.retrieval === 'boolean' ? raw.retrieval : null,
    articles: storedArticles(raw.articles),
    passages: storedPassages(raw.passages),
    suggestions: Array.isArray(raw.suggestions)
      ? raw.suggestions.filter((item): item is string => typeof item === 'string')
      : [],
    titlesPending: false,
    status: '',
    phase,
    error,
    stopped,
    contextBefore: asContext(raw.contextBefore),
  }
}

function normalizeSession(value: unknown): Session | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Partial<Session>
  if (typeof raw.id !== 'string' || typeof raw.title !== 'string' || !Array.isArray(raw.turns)) {
    return null
  }
  const turns = raw.turns.map(normalizeTurn).filter((turn): turn is ChatTurn => turn !== null)
  return foldStoppedTail({
    id: raw.id,
    title: raw.title,
    updatedAt: typeof raw.updatedAt === 'number' ? raw.updatedAt : Date.now(),
    turns,
    context: asContext(raw.context),
  })
}

/** A reload mid-answer never runs the in-page Stop path, so fold that answer here. */
function foldStoppedTail(session: Session): Session {
  const last = session.turns.at(-1)
  const answer = last?.answer.trim() ?? ''
  if (!last?.stopped || !answer) return session
  const current = session.context.last_answer ?? ''
  const prefix = current.replace(/…$/, '')
  if (prefix && answer.startsWith(prefix)) return session
  return { ...session, context: contextAfterStop(session.context, last) }
}

/** Rephrase turns are not re-retrieved; keep the previous turn's evidence. */
export function carryEvidence(turns: ChatTurn[], turnId: string): ChatTurn[] {
  const index = turns.findIndex((turn) => turn.id === turnId)
  if (index <= 0) return turns
  const prior = [...turns.slice(0, index)].reverse().find((turn) => turn.articles.length > 0)
  if (!prior) return turns
  return turns.map((turn) =>
    turn.id === turnId
      ? { ...turn, articles: prior.articles, passages: prior.passages }
      : turn,
  )
}

export function loadSessions(): Session[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const data: unknown = JSON.parse(raw)
    if (!Array.isArray(data)) return []
    return data
      .map(normalizeSession)
      .filter((session): session is Session => session !== null)
      .slice(0, SESSION_LIMIT)
  } catch {
    return []
  }
}

export function saveSessions(sessions: Session[]) {
  const payload = sessions.slice(0, SESSION_LIMIT).map((session) => ({
    ...session,
    turns: session.turns.map((turn) => ({ ...turn, titlesPending: false })),
  }))
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
  } catch {
    try {
      const lighter = payload.map((session) => ({
        ...session,
        turns: session.turns.map((turn) => ({ ...turn, passages: [] })),
      }))
      localStorage.setItem(STORAGE_KEY, JSON.stringify(lighter))
    } catch {
      /* storage full */
    }
  }
}
