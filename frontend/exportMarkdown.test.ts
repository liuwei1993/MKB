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
        '见 [1]，以及 [2]。再次 [1]。',
        '',
        '参考文献 2 篇',
        '',
        '1. SGLT2 inhibitors: a systematic review（PMID:1111）',
        '2. 达格列净在射血分数降低的心力衰竭患者中的应用（PMID:2222）',
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
    assert.match(text, /\[1\]\n\n参考文献 1 篇\n\n1\. PMID:9999\n$/)
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
        '[1]',
        '',
        '参考文献 1 篇',
        '',
        '1. \\*gene\\* \\_in vitro\\_ \\[Label\\](2020) \\<i>E. coli\\</i> \\`code\\` a\\\\b（PMID:1111）',
        '',
      ].join('\n'),
    )
  })

  it('keeps a leading block marker as part of the title', () => {
    const text = exportMarkdown({
      question: '问题',
      answer: '[PMID:1111] [PMID:2222] [PMID:3333] [PMID:4444] [PMID:5555] [PMID:6666]',
      articles: [
        article('1111', '>= 50% stenosis'),
        article('2222', '# Title'),
        article('3333', '- Omics'),
        article('4444', '+ item'),
        article('5555', '1. Background'),
        article('6666', '1) Background'),
      ],
    })
    assert.equal(
      text,
      [
        '# 问题',
        '',
        '[1] [2] [3] [4] [5] [6]',
        '',
        '参考文献 6 篇',
        '',
        '1. \\>= 50% stenosis（PMID:1111）',
        '2. \\# Title（PMID:2222）',
        '3. \\- Omics（PMID:3333）',
        '4. \\+ item（PMID:4444）',
        '5. 1\\. Background（PMID:5555）',
        '6. 1\\) Background（PMID:6666）',
        '',
      ].join('\n'),
    )
  })
})
