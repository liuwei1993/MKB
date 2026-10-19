import { citationOrder, numberCitations } from './citations.ts'
import type { ArticleMeta, ChatTurn } from './history.ts'

// Inline marks can appear anywhere. Block marks only matter at the start of a list item.
const INLINE_MD = /[\\`*_[\]<]/g

function escapeMarkdownText(text: string): string {
  return text
    .replace(INLINE_MD, '\\$&')
    .replace(/^(#{1,6})(?=\s|$)/, '\\$1')
    .replace(/^[>*+-]/, '\\$&')
    .replace(/^(\d+)([.)])(?=\s)/, '$1\\$2')
}

function referenceTitle(article: ArticleMeta | undefined, pmid: string): string {
  const title = [article?.title_zh, article?.title]
    .map((part) => part?.replace(/\s+/g, ' ').trim())
    .find(Boolean)
  return escapeMarkdownText(title || `PMID:${pmid}`)
}

/** Question, answer, and the cited reference list shown under the answer. */
export function exportMarkdown(turn: Pick<ChatTurn, 'question' | 'answer' | 'articles'>): string {
  const body = `# ${turn.question}\n\n${numberCitations(turn.answer)}\n`
  const order = citationOrder(turn.answer)
  if (order.length === 0) return body
  const byPmid = new Map(turn.articles.map((article) => [article.pmid, article]))
  const lines = order.map((pmid, index) => {
    const title = referenceTitle(byPmid.get(pmid), pmid)
    const label = title === `PMID:${pmid}` ? title : `${title}（PMID:${pmid}）`
    return `${index + 1}. ${label}`
  })
  return `${body}\n参考文献 ${order.length} 篇\n\n${lines.join('\n')}\n`
}
