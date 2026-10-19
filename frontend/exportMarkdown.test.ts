import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { exportMarkdown } from './src/exportMarkdown.ts'
import type { ArticleMeta } from './src/history.ts'

function article(pmid: string, title: string, titleZh = ''): ArticleMeta {
  return {
    pmid,
    title,
    title_zh: titleZh,
    journal: 'J',
    year: '2024',
    authors: 'Doe',
    url: `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`,
    has_abstract: true,
  }
}

describe('exportMarkdown', () => {
  it('appends cited titles in first-seen order, preferring the Chinese title', () => {
    const text = exportMarkdown({
      question: 'SGLT2 抑制剂对心衰住院的影响',
      answer: '见 [PMID:1111]，以及 PMID:2222。再次 [PMID:1111]。',
      articles: [
        article('2222', 'Dapagliflozin in heart failure', '达格列净在射血分数降低的心力衰竭患者中的应用'),
        article('1111', 'SGLT2 inhibitors: a systematic review'),
        article('3333', 'Retrieved but not cited'),
      ],
    })
    assert.equal(
      text,
      [
        '# SGLT2 抑制剂对心衰住院的影响',
        '',
        '见 [PMID:1111]，以及 PMID:2222。再次 [PMID:1111]。',
        '',
        '参考文献 2 篇',
        '',
        '1. SGLT2 inhibitors: a systematic review',
        '2. 达格列净在射血分数降低的心力衰竭患者中的应用',
        '',
      ].join('\n'),
    )
  })

  it('omits the reference section when the answer cites nothing', () => {
    const text = exportMarkdown({
      question: '问题',
      answer: '没有引用。',
      articles: [article('1111', 'Unused')],
    })
    assert.equal(text, '# 问题\n\n没有引用。\n')
  })

  it('falls back to PMID when the cited paper has no title', () => {
    const text = exportMarkdown({
      question: '问题',
      answer: '[PMID:9999]',
      articles: [],
    })
    assert.match(text, /参考文献 1 篇\n\n1\. PMID:9999\n$/)
  })

  it('keeps reference titles as plain text and skips a blank Chinese title', () => {
    const text = exportMarkdown({
      question: '问题',
      answer: '[PMID:1111]',
      articles: [
        article(
          '1111',
          '*gene* _in vitro_ [Label](2020) <i>E. coli</i> `code` a\\b',
          '   ',
        ),
      ],
    })
    assert.equal(
      text,
      [
        '# 问题',
        '',
        '[PMID:1111]',
        '',
        '参考文献 1 篇',
        '',
        '1. \\*gene\\* \\_in vitro\\_ \\[Label\\](2020) \\<i>E. coli\\</i> \\`code\\` a\\\\b',
        '',
      ].join('\n'),
    )
  })
})
