import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  createLimiter,
  runTitleTranslation,
  type TitleSource,
} from './src/titleTranslation.ts'

function papers(count: number): TitleSource[] {
  return Array.from({ length: count }, (_, index) => ({
    pmid: String(10000000 + index),
    title: `English title ${index}`,
  }))
}

function abortError(): Error {
  const error = new Error('Aborted')
  error.name = 'AbortError'
  return error
}

describe('runTitleTranslation', () => {
  it('translates in small chunks and reports each chunk', async () => {
    const sizes: number[] = []
    const seen: string[] = []
    await runTitleTranslation({
      articles: papers(10),
      answer: () => '',
      signal: new AbortController().signal,
      limiter: createLimiter(2),
      fetchTitles: async (batch) => {
        sizes.push(batch.length)
        seen.push(...batch.map((item) => item.pmid))
        return Object.fromEntries(batch.map((item) => [item.pmid, `译${item.pmid}`]))
      },
      onTitles: () => {},
    })
    assert.deepEqual([...sizes].sort((a, b) => b - a), [8, 2])
    assert.equal(new Set(seen).size, 10)
  })

  it('asks for cited titles before the rest of the list', async () => {
    const cited = '10000009'
    const batches: string[][] = []
    await runTitleTranslation({
      articles: papers(10),
      answer: () => `[PMID:${cited}]`,
      signal: new AbortController().signal,
      limiter: createLimiter(1),
      chunkSize: 4,
      workers: 1,
      fetchTitles: async (batch) => {
        batches.push(batch.map((item) => item.pmid))
        return {}
      },
      onTitles: () => {},
    })
    assert.equal(batches[0][0], cited)
    assert.deepEqual(batches[0], [cited, '10000000', '10000001', '10000002'])
  })

  it('retries a failed chunk and still translates the others', async () => {
    const calls: string[] = []
    const got: string[] = []
    await runTitleTranslation({
      articles: papers(2),
      answer: () => '',
      signal: new AbortController().signal,
      limiter: createLimiter(1),
      chunkSize: 1,
      workers: 1,
      fetchTitles: async (batch) => {
        const pmid = batch[0].pmid
        calls.push(pmid)
        if (pmid === '10000000') throw new Error('down')
        return { [pmid]: '乙' }
      },
      onTitles: (titles) => got.push(...Object.keys(titles)),
    })
    assert.deepEqual(calls, ['10000000', '10000000', '10000001'])
    assert.deepEqual(got, ['10000001'])
  })

  it('does not start when already aborted', async () => {
    const controller = new AbortController()
    controller.abort()
    let calls = 0
    await runTitleTranslation({
      articles: papers(2),
      answer: () => '',
      signal: controller.signal,
      limiter: createLimiter(1),
      fetchTitles: async () => {
        calls += 1
        return {}
      },
      onTitles: () => {},
    })
    assert.equal(calls, 0)
  })

  it('stops when the request is aborted', async () => {
    const controller = new AbortController()
    let calls = 0
    await runTitleTranslation({
      articles: papers(3),
      answer: () => '',
      signal: controller.signal,
      limiter: createLimiter(1),
      chunkSize: 1,
      workers: 1,
      fetchTitles: async () => {
        calls += 1
        controller.abort()
        throw abortError()
      },
      onTitles: () => {},
    })
    assert.equal(calls, 1)
  })
})
