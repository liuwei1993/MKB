export type RecentTurn = {
  question: string
  excerpt: string
  pmids: string[]
}

export type ContextEnvelope = {
  summary: string
  recent: RecentTurn[]
  last_answer?: string
}

const RECENT_MAX_TURNS = 3
const SUMMARY_MAX_CHARS = 800
const EXCERPT_MAX_CHARS = 500
const LAST_ANSWER_MAX_CHARS = 12000
const QUESTION_MAX_CHARS = 4000

function clip(text: string, limit: number): string {
  const value = text.trim()
  if (value.length <= limit) return value
  if (limit <= 1) return value.slice(0, limit)
  return `${value.slice(0, limit - 1)}…`
}

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

/** Same fallback as pipeline.naive_summary when the oldest turn cannot be folded by the model. */
function naiveSummary(summary: string, turn: RecentTurn): string {
  const pmids = turn.pmids.join(',')
  let bit = `用户：${turn.question}；回答：${turn.excerpt}`
  if (pmids) bit += `；PMID：${pmids}`
  const joined = summary ? `${summary}\n${bit}` : bit
  return clip(joined, SUMMARY_MAX_CHARS)
}

/** 停止时服务端不会再下发 context，用已生成的文本补上这一轮。 */
export function contextAfterStop(
  ctx: ContextEnvelope,
  turn: { question: string; answer: string },
): ContextEnvelope {
  const answer = turn.answer.trim()
  if (!answer) return ctx
  const added: RecentTurn = {
    question: clip(turn.question, QUESTION_MAX_CHARS),
    excerpt: clip(answer, EXCERPT_MAX_CHARS),
    pmids: pmidsIn(answer),
  }
  let summary = ctx.summary
  let recent = ctx.recent
  if (recent.length >= RECENT_MAX_TURNS) {
    summary = naiveSummary(summary, recent[0])
    recent = recent.slice(1)
  }
  return {
    summary,
    recent: [...recent, added],
    last_answer: clip(answer, LAST_ANSWER_MAX_CHARS),
  }
}
