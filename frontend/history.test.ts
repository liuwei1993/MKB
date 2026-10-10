import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { carryEvidence, type ChatTurn } from './src/history.ts'

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
})