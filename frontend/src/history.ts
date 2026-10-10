import type { ContextEnvelope } from './stopContext'

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

function normalizeTurn(value: unknown): ChatTurn | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Partial<ChatTurn>
  if (typeof raw.id !== 'string' || typeof raw.question !== 'string') return null
  const answer = typeof raw.answer === 'string' ? raw.answer : ''
  const phase = typeof raw.phase === 'string' && raw.phase ? raw.phase : 'done'
  const error = typeof raw.error === 'string' ? raw.error : ''
  let stopped = Boolean(raw.stopped)
  if (!stopped && !error && phase !== 'done' && phase !== 'answer') stopped = true
  if (!stopped && !error && phase === 'answer' && !answer) stopped = true
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
    articles: Array.isArray(raw.articles) ? raw.articles : [],
    passages: Array.isArray(raw.passages) ? raw.passages : [],
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
  return {
    id: raw.id,
    title: raw.title,
    updatedAt: typeof raw.updatedAt === 'number' ? raw.updatedAt : Date.now(),
    turns,
    context: asContext(raw.context),
  }
}

/** Rephrase turns are not re-retrieved; keep the previous turn's evidence. */
export function carryEvidence(turns: ChatTurn[], turnId: string): ChatTurn[] {
  const prior = [...turns].reverse().find((turn) => turn.id !== turnId)
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
