import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { carryEvidence, loadSessions, STORAGE_KEY, type ChatTurn } from './src/history.ts'

function turn(id: string, articles: ChatTurn['articles'] = []): ChatTurn {
  return {
    id,
    question: id,
    answer: '',
    queries: [],
    standalone: '',
    relation: '',
    retrieval: null,
    articles,
    passages: articles.map((article) => ({
      pmid: article.pmid,
      source: 'abstract',
      text: article.title,
    })),
    suggestions: [],
    titlesPending: false,
    status: '',
    phase: 'understand',
    error: '',
    stopped: false,
    contextBefore: { summary: '', recent: [] },
  }
}

describe('carryEvidence', () => {
  it('copies the previous turn evidence onto a rephrase turn', () => {
    const article = {
      pmid: '12345678',
      title: 'Example',
      journal: 'Foods',
      year: '2024',
      authors: 'Doe J',
      url: 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
      has_abstract: true,
    }
    const next = carryEvidence([turn('a', [article]), turn('b')], 'b')
    assert.equal(next[1]?.articles[0]?.pmid, '12345678')
    assert.equal(next[1]?.passages[0]?.text, 'Example')
    assert.equal(next[0]?.articles.length, 1)
  })

  it('leaves the only turn unchanged', () => {
    const only = [turn('a')]
    assert.equal(carryEvidence(only, 'a'), only)
  })

  it('skips an empty rephrase and keeps the earlier articles', () => {
    const article = {
      pmid: '12345678',
      title: 'Example',
      journal: 'Foods',
      year: '2024',
      authors: 'Doe J',
      url: 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
      has_abstract: true,
    }
    const next = carryEvidence([turn('a', [article]), turn('b'), turn('c')], 'c')
    assert.equal(next[2]?.articles[0]?.pmid, '12345678')
    assert.equal(next[1]?.articles.length, 0)
  })
})

describe('loadSessions', () => {
  it('marks a mid-stream turn stopped and drops a corrupt article', () => {
    const store = new Map<string, string>()
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => {
          store.set(key, value)
        },
      },
    })
    store.set(
      STORAGE_KEY,
      JSON.stringify([
        {
          id: 's',
          title: '营养',
          updatedAt: 1,
          context: { summary: '', recent: [] },
          turns: [
            {
              id: 'done',
              question: '完成',
              answer: '正文',
              phase: 'done',
              articles: [{ pmid: '1', title: 'T' }, 'bad'],
              passages: [{ pmid: '1', text: '段' }, { pmid: '1' }],
            },
            { id: 'partial', question: '中断', answer: '半截', phase: 'answer' },
            { id: 'failed', question: '失败', answer: '', phase: 'search', error: '请求失败' },
          ],
        },
      ]),
    )
    const [session] = loadSessions()
    assert.equal(session?.turns[0]?.stopped, false)
    assert.equal(session?.turns[0]?.articles.length, 1)
    assert.equal(session?.turns[0]?.passages.length, 1)
    assert.equal(session?.turns[1]?.stopped, true)
    assert.equal(session?.turns[2]?.stopped, false)
    assert.equal(session?.turns[2]?.error, '请求失败')
  })

  it('folds a refreshed partial answer into the next turn context', () => {
    const store = new Map<string, string>()
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => {
          store.set(key, value)
        },
      },
    })
    store.set(
      STORAGE_KEY,
      JSON.stringify([
        {
          id: 's',
          title: '中断',
          updatedAt: 1,
          context: { summary: '', recent: [] },
          turns: [{ id: 'partial', question: '问题', answer: '半截回答', phase: 'answer' }],
        },
      ]),
    )
    const [session] = loadSessions()
    assert.equal(session?.turns[0]?.stopped, true)
    assert.equal(session?.context.last_answer, '半截回答')
    assert.equal(session?.context.recent[0]?.question, '问题')
  })
})
