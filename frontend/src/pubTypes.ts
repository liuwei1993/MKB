const PUB_TYPE_ZH: Record<string, string> = {
  Review: '综述',
  'Systematic Review': '系统综述',
  'Meta-Analysis': '荟萃分析',
  'Randomized Controlled Trial': '随机对照试验',
  'Clinical Trial': '临床试验',
  'Clinical Trial, Phase I': 'I 期临床试验',
  'Clinical Trial, Phase II': 'II 期临床试验',
  'Clinical Trial, Phase III': 'III 期临床试验',
  'Clinical Trial, Phase IV': 'IV 期临床试验',
  'Controlled Clinical Trial': '对照临床试验',
  'Case Reports': '病例报告',
  'Comparative Study': '对照研究',
  'Observational Study': '观察性研究',
  'Multicenter Study': '多中心研究',
  'Evaluation Study': '评价研究',
  'Validation Study': '验证研究',
  'Practice Guideline': '实践指南',
  Guideline: '指南',
  Editorial: '述评',
  Letter: '读者来信',
  Comment: '评论',
  'Journal Article': '期刊论文',
}

function isNoise(label: string): boolean {
  return (
    label === 'English Abstract' ||
    label.startsWith('Research Support') ||
    label === 'Retracted Publication'
  )
}

/** Prefer a specific study type over the generic journal-article label. */
export function pubTypeLabel(types: string[] | undefined): string {
  const list = (types ?? []).map((item) => item.trim()).filter(Boolean)
  const specific = list.find((item) => item !== 'Journal Article' && !isNoise(item))
  const chosen = specific || list.find((item) => !isNoise(item))
  if (!chosen) return ''
  return PUB_TYPE_ZH[chosen] || chosen
}
