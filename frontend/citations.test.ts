import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { citationOrder, linkifyCitations, numberCitations } from './src/citations.ts'

describe('citationOrder', () => {
  it('numbers the first sighting of each PMID and keeps later repeats', () => {
    const text = '见 [PMID:1111] 与 PMID:2222，再次 [PMID:1111]。'
    assert.deepEqual(citationOrder(text), ['1111', '2222'])
    assert.equal(
      linkifyCitations(text),
      '见 [1](#cite-1111) 与 [2](#cite-2222)，再次 [1](#cite-1111)。',
    )
  })

  it('leaves an unfinished marker untouched while the answer is still streaming', () => {
    assert.equal(linkifyCitations('半截 [PMID:3333'), '半截 [PMID:3333')
  })

  it('accepts a fullwidth colon', () => {
    assert.deepEqual(citationOrder('来源 [PMID：4444]'), ['4444'])
  })
})

describe('numberCitations', () => {
  it('replaces each marker with its first-seen number', () => {
    assert.equal(
      numberCitations('见 [PMID:1111]，再次 [PMID:1111]，以及 PMID:2222。'),
      '见 [1]，再次 [1]，以及 [2]。',
    )
  })

  it('leaves an unfinished marker untouched', () => {
    assert.equal(numberCitations('半截 [PMID:3333'), '半截 [PMID:3333')
  })
})
