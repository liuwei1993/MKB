import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { contextAfterStop, type ContextEnvelope } from './src/stopContext.ts'

function envelope(): ContextEnvelope {
  return {
    summary: '更早摘要',
    recent: [
      { question: '问题一', excerpt: '回答一', pmids: ['1111'] },
      { question: '问题二', excerpt: '回答二', pmids: [] },
      { question: '问题三', excerpt: '回答三', pmids: [] },
    ],
    last_answer: '回答三全文',
  }
}

describe('contextAfterStop', () => {
  it('folds the oldest turn into the summary when recent is full', () => {
    const prev = envelope()
    const next = contextAfterStop(prev, {
      question: '问题四',
      answer: '部分回答 PMID:2222',
    })

    assert.equal(next.summary, '更早摘要\n用户：问题一；回答：回答一；PMID：1111')
    assert.deepEqual(
      next.recent.map((turn) => turn.question),
      ['问题二', '问题三', '问题四'],
    )
    assert.equal(next.recent[2]?.excerpt, '部分回答 PMID:2222')
    assert.deepEqual(next.recent[2]?.pmids, ['2222'])
    assert.equal(next.last_answer, '部分回答 PMID:2222')
    assert.equal(prev.recent.length, 3)
  })

  it('leaves context unchanged when generation stopped before any text', () => {
    const prev = envelope()
    const next = contextAfterStop(prev, { question: '问题四', answer: '  \n' })
    assert.equal(next, prev)
  })

  it('appends without folding when there is still room', () => {
    const prev: ContextEnvelope = {
      summary: '',
      recent: [{ question: '问题一', excerpt: '回答一', pmids: [] }],
      last_answer: '回答一',
    }
    const next = contextAfterStop(prev, { question: '问题二', answer: '新的半截' })
    assert.equal(next.summary, '')
    assert.equal(next.recent.length, 2)
    assert.equal(next.recent[1]?.question, '问题二')
    assert.equal(next.last_answer, '新的半截')
  })

  it('clips a long partial the same way the server clips excerpts', () => {
    const answer = '答'.repeat(600)
    const next = contextAfterStop(
      { summary: '', recent: [], last_answer: '' },
      { question: '长回答', answer },
    )
    assert.equal(next.recent[0]?.excerpt.length, 500)
    assert.ok(next.recent[0]?.excerpt.endsWith('…'))
    assert.equal(next.last_answer?.length, 600)
  })
})
