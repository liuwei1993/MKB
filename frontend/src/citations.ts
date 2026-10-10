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

/** Turn PMID markers into markdown links whose text is the first-seen number. */
export function linkifyCitations(text: string): string {
  const order = citationOrder(text)
  const number = new Map(order.map((pmid, index) => [pmid, index + 1]))
  return text.replace(mark(), (full, bracketed: string | undefined, bare: string | undefined) => {
    const pmid = bracketed || bare
    const n = pmid ? number.get(pmid) : undefined
    if (!pmid || !n) return full
    return `[${n}](#cite-${pmid})`
  })
}
