import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { pubTypeLabel } from './src/pubTypes.ts'

describe('pubTypeLabel', () => {
  it('shows a retracted publication as 已撤稿', () => {
    assert.equal(
      pubTypeLabel(['Journal Article', 'Retracted Publication', 'Review']),
      '已撤稿',
    )
  })

  it('still prefers a specific study type over the generic journal article label', () => {
    assert.equal(pubTypeLabel(['Journal Article', 'Systematic Review']), '系统综述')
  })
})
