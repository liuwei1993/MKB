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

  it('prefers 专家共识 over a co-tagged guideline', () => {
    assert.equal(
      pubTypeLabel([
        'Journal Article',
        'Practice Guideline',
        'Consensus Development Conference',
      ]),
      '专家共识',
    )
    assert.equal(
      pubTypeLabel(['Consensus Development Conference, NIH']),
      '专家共识',
    )
  })

  it('maps guideline publication types to 指南', () => {
    assert.equal(pubTypeLabel(['Guideline', 'Journal Article']), '指南')
    assert.equal(pubTypeLabel(['Practice Guideline']), '指南')
  })

  it('maps systematic reviews and meta-analyses ahead of Review', () => {
    assert.equal(
      pubTypeLabel(['Journal Article', 'Review', 'Systematic Review']),
      '系统评价/Meta分析',
    )
    assert.equal(pubTypeLabel(['Meta-Analysis', 'Review']), '系统评价/Meta分析')
    assert.equal(pubTypeLabel(['Network Meta-Analysis']), '系统评价/Meta分析')
  })

  it('folds trial designs into 临床试验 ahead of Journal Article', () => {
    assert.equal(
      pubTypeLabel(['Journal Article', 'Randomized Controlled Trial']),
      '临床试验',
    )
    assert.equal(pubTypeLabel(['Clinical Trial, Phase III']), '临床试验')
    assert.equal(pubTypeLabel(['Controlled Clinical Trial']), '临床试验')
    assert.equal(pubTypeLabel(['Pragmatic Clinical Trial']), '临床试验')
    assert.equal(pubTypeLabel(['Adaptive Clinical Trial']), '临床试验')
    assert.equal(pubTypeLabel(['Equivalence Trial']), '临床试验')
  })

  it('maps a plain review to 综述', () => {
    assert.equal(pubTypeLabel(['Journal Article', 'Review']), '综述')
  })

  it('uses 原创研究论文 for other and missing types', () => {
    assert.equal(pubTypeLabel(['Journal Article']), '原创研究论文')
    assert.equal(pubTypeLabel(['Observational Study']), '原创研究论文')
    assert.equal(pubTypeLabel(['Case Reports']), '原创研究论文')
    assert.equal(pubTypeLabel(['Editorial']), '原创研究论文')
    assert.equal(pubTypeLabel([]), '原创研究论文')
    assert.equal(pubTypeLabel(undefined), '原创研究论文')
  })
})
