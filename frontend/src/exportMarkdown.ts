import { citationOrder } from './citations.ts'
import type { ArticleMeta, ChatTurn } from './history.ts'

// Keep titles as plain text in a Markdown preview: emphasis, links, and HTML tags.
const MARKDOWN_TEXT = /[\\`*_[\]<]/g

function escapeMarkdownText(text: string): string {
  return text.replace(MARKDOWN_TEXT, '\\$&')
}

function referenceTitle(article: ArticleMeta | undefined, pmid: string): string {
  const title = [article?.title_zh, article?.title]
    .map((part) => part?.replace(/\s+/g, ' ').trim())
    .find(Boolean)
  return escapeMarkdownText(title || `PMID:${pmid}`)
}

/** Question, answer, and the cited reference list shown under the answer. */
export function exportMarkdown(turn: Pick<ChatTurn, 'question' | 'answer' | 'articles'>): string {
  const body = `# ${turn.question}\n\n${turn.answer}\n`
  const order = citationOrder(turn.answer)
  if (order.length === 0) return body
  const byPmid = new Map(turn.articles.map((article) => [article.pmid, article]))
  const lines = order.map((pmid, index) => `${index + 1}. ${referenceTitle(byPmid.get(pmid), pmid)}`)
  return `${body}\n参考文献 ${order.length} 篇\n\n${lines.join('\n')}\n`
}
