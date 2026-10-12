import { citationOrder } from './citations.ts'

export const TITLE_CHUNK = 8
export const TITLE_WORKERS = 2

export type TitleSource = {
  pmid: string
  title: string
}

export type TitleLimiter = {
  acquire: () => Promise<void>
  release: () => void
}

export function createLimiter(limit: number): TitleLimiter {
  let active = 0
  const waiters: Array<() => void> = []
  return {
    async acquire() {
      if (active < limit) {
        active += 1
        return
      }
      await new Promise<void>((resolve) => {
        waiters.push(resolve)
      })
    },
    release() {
      const next = waiters.shift()
      if (next) {
        next()
        return
      }
      active = Math.max(0, active - 1)
    },
  }
}

export const titleSlots = createLimiter(TITLE_WORKERS)

function isAbort(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

function takeChunk(
  queue: TitleSource[],
  started: Set<string>,
  answer: string,
  signal: AbortSignal,
  chunkSize: number,
): TitleSource[] {
  if (signal.aborted) return []
  const rank = new Map(citationOrder(answer).map((pmid, index) => [pmid, index]))
  const rest = queue.filter((article) => !started.has(article.pmid))
  rest.sort((a, b) => (rank.get(a.pmid) ?? 1_000_000) - (rank.get(b.pmid) ?? 1_000_000))
  const chunk = rest.slice(0, chunkSize)
  for (const article of chunk) started.add(article.pmid)
  return chunk
}

async function loadChunk(
  chunk: TitleSource[],
  signal: AbortSignal,
  fetchTitles: (batch: TitleSource[], signal: AbortSignal) => Promise<Record<string, string>>,
): Promise<Record<string, string>> {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      return await fetchTitles(chunk, signal)
    } catch (error) {
      if (isAbort(error) || signal.aborted) throw error
    }
  }
  return {}
}

export async function runTitleTranslation({
  articles,
  answer,
  signal,
  limiter,
  fetchTitles,
  onTitles,
  chunkSize = TITLE_CHUNK,
  workers = TITLE_WORKERS,
}: {
  articles: TitleSource[]
  answer: () => string
  signal: AbortSignal
  limiter: TitleLimiter
  fetchTitles: (batch: TitleSource[], signal: AbortSignal) => Promise<Record<string, string>>
  onTitles: (titles: Record<string, string>) => void
  chunkSize?: number
  workers?: number
}): Promise<void> {
  const queue: TitleSource[] = []
  const seen = new Set<string>()
  for (const article of articles) {
    const pmid = article.pmid.trim()
    const title = article.title.trim()
    if (!pmid || seen.has(pmid)) continue
    seen.add(pmid)
    queue.push({ pmid, title })
  }
  if (queue.length === 0) return

  const started = new Set<string>()
  const workerCount = Math.min(workers, Math.ceil(queue.length / chunkSize))

  const worker = async () => {
    while (!signal.aborted) {
      const chunk = takeChunk(queue, started, answer(), signal, chunkSize)
      if (chunk.length === 0) return
      await limiter.acquire()
      try {
        if (signal.aborted) return
        const titles = await loadChunk(chunk, signal, fetchTitles)
        if (Object.keys(titles).length > 0) onTitles(titles)
      } catch (error) {
        if (isAbort(error) || signal.aborted) return
      } finally {
        limiter.release()
      }
    }
  }

  await Promise.all(Array.from({ length: workerCount }, () => worker()))
}

export async function postTitleBatch(
  articles: TitleSource[],
  signal: AbortSignal,
): Promise<Record<string, string>> {
  const res = await fetch('/api/translate-titles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({ articles }),
  })
  if (!res.ok) throw new Error(`translate ${res.status}`)
  const data = (await res.json()) as { titles?: unknown }
  const titles = data.titles
  if (!titles || typeof titles !== 'object' || Array.isArray(titles)) return {}
  const out: Record<string, string> = {}
  for (const [pmid, value] of Object.entries(titles)) {
    if (typeof value === 'string' && value.trim()) out[pmid] = value
  }
  return out
}
