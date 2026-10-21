const CATEGORY_RULES: { label: string; types: ReadonlySet<string> }[] = [
  {
    label: '专家共识',
    types: new Set([
      'Consensus Development Conference',
      'Consensus Development Conference, NIH',
    ]),
  },
  {
    label: '指南',
    types: new Set(['Guideline', 'Practice Guideline']),
  },
  {
    label: '系统评价/Meta分析',
    types: new Set(['Systematic Review', 'Meta-Analysis', 'Network Meta-Analysis']),
  },
  {
    label: '临床试验',
    types: new Set([
      'Clinical Trial',
      'Clinical Trial, Phase I',
      'Clinical Trial, Phase II',
      'Clinical Trial, Phase III',
      'Clinical Trial, Phase IV',
      'Controlled Clinical Trial',
      'Randomized Controlled Trial',
      'Pragmatic Clinical Trial',
      'Adaptive Clinical Trial',
      'Equivalence Trial',
    ]),
  },
  {
    label: '综述',
    types: new Set(['Review']),
  },
]

/** Map PubMed publication types to one of six literature categories. */
export function pubTypeLabel(types: string[] | undefined): string {
  const list = (types ?? []).map((item) => item.trim()).filter(Boolean)
  if (list.includes('Retracted Publication')) return '已撤稿'
  for (const rule of CATEGORY_RULES) {
    if (list.some((item) => rule.types.has(item))) return rule.label
  }
  return '原创研究论文'
}
