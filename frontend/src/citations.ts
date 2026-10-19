const MARK_SOURCE =
  '\\[PMID\\s*[:：]\\s*(\\d{4,10})\\]|(?<!\\[)PMID\\s*[:：]\\s*(\\d{4,10})'

function mark(): RegExp {
  return new RegExp(MARK_SOURCE, 'gi')
}

export function citationOrder(text: string): string[] {
  const order: string[] = []
  for (const match of text.matchAll(mark())) {
    const pmid = match[1] || match[2]
    if (!pmid || order.includes(pmid)) continue
    order.push(pmid)
  }
  return order
}

function replaceMarks(text: string, format: (pmid: string, n: number) => string): string {
  const number = new Map(citationOrder(text).map((pmid, index) => [pmid, index + 1]))
  return text.replace(mark(), (full, bracketed: string | undefined, bare: string | undefined) => {
    const pmid = bracketed || bare
    const n = pmid ? number.get(pmid) : undefined
    if (!pmid || !n) return full
    return format(pmid, n)
  })
}

/** Turn PMID markers into markdown links whose text is the first-seen number. */
export function linkifyCitations(text: string): string {
  return replaceMarks(text, (pmid, n) => `[${n}](#cite-${pmid})`)
}

/** Turn PMID markers into plain [n] labels for a downloaded file. */
export function numberCitations(text: string): string {
  return replaceMarks(text, (_pmid, n) => `[${n}]`)
}
