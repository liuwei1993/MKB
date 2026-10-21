# PubMed 检索式使用说明

写给要在 PubMed 网页、Advanced Search，或通过 E-utilities（本仓库的 `esearch`）手写、审阅检索式的人。

检索式是交给 PubMed 的一条查询字符串。它决定命中哪些 PMID。网页侧栏里的过滤器和本仓库自动追加的研究设计限制，最终也都变成这条字符串的一部分。

本文语法整理自 [PubMed User Guide](https://pubmed.ncbi.nlm.nih.gov/help/)（查阅日期 2026-10-21）。过滤器的等价检索式摘自该指南的 Filter search strategies 与 Clinical Study Categories 表，按原文抄录。NLM 会改映射和过滤器；与本文不一致时，以 Advanced Search 的 **Search Details** 为准。

相关文档：[PubMed Skill 详细介绍](./pubmed-skill-详细介绍.md) 讲的是证据分级和挑文章的方法。本文只讲检索式怎么写。

## 1. 先看这条

一条能复用的检索式通常是：

```text
(人群或疾病) AND (干预、暴露或指标) AND (可选：研究设计或文献类型)
```

概念内部用 `OR` 并联同义词，概念之间用 `AND` 连接。`OR` 组必须加括号。布尔运算符必须大写。

最小例子：

```text
("heart failure"[mh] OR "heart failure"[tiab]) AND (dapagliflozin[tiab] OR empagliflozin[tiab] OR "sodium glucose transporter 2 inhibitors"[mh])
```

不要把整句中文或英文问句贴进检索框。PubMed 会丢掉停用词，再把剩下的词自动映射，结果和你想的往往不一样。

## 2. 下笔之前先拆概念

一个临床问题先拆成可以独立检索的块，再决定哪一块用主题词、哪一块用自由词。

| 问题成分 | 检索时放什么 | 例子 |
| --- | --- | --- |
| 人群 / 疾病 | MeSH，必要时加标题摘要自由词 | 射血分数降低的心衰 |
| 干预 / 暴露 | 通用名、商品名、药物类名 | 达格列净、SGLT2 抑制剂 |
| 对照 | 只有对照本身也是检索概念时才写 | 安慰剂、常规治疗。多数疗效问题不必写 placebo |
| 结局 | 结局词很泛时先不要写进检索式 | mortality、hospitalization 常留到筛文章时再看 |
| 研究设计 | 文献类型或 Clinical Queries 过滤器 | 系统综述、随机对照试验 |
| 限制 | 人类、年龄、年份、语种 | 容易漏掉尚未标引的新文章，最后再加 |

原则：先宽后窄。漏检比多翻几页更难补。第一稿只保留疾病和干预；结果太多，再加设计、人群或年份。

同一概念的不同说法放在一组 `OR` 里，例如：

- 主题词和入口词：heart failure、cardiac failure
- 英美拼写：tumor、tumour。不截词时，自动映射会补很多拼写；一旦加引号或截词，要自己写上
- 通用名和常见商品名：只在商品名文献很多时加入
- 缩写：缩写有歧义时不要单独检索。`HR` 既是心率也是风险比，应写成 `"hazard ratio"[tiab]` 或 `"heart rate"[tiab]`

## 3. 布尔运算

| 写法 | 含义 |
| --- | --- |
| `AND`，或 `&` | 两边都要出现 |
| `OR`，或 `\|` | 至少一边出现 |
| `NOT` | 去掉后面的命中 |

PubMed **从左到右**计算，没有「先 AND 后 OR」的优先级。下面两条不一样：

```text
aspirin OR warfarin AND stroke
(aspirin OR warfarin) AND stroke
```

第一条先算 `aspirin OR warfarin`，再和 `stroke` 做 AND，碰巧和括号版相同。换成下面这种就会错：

```text
stroke AND aspirin OR warfarin
```

它先算 `stroke AND aspirin`，再 OR 上所有华法林文献，包括与卒中无关的。同义词组一律加括号：

```text
(stroke OR "cerebrovascular accident") AND (aspirin OR warfarin)
```

其他规则：

- `AND`、`OR`、`NOT` 必须大写。小写 `and`、`or`、`not` 是停用词，会被丢掉，**不会**当成运算符。
- 词与词之间不写运算符时，PubMed 按 `AND` 处理，但会先尝试把相邻词识别成短语。不想要这种自动短语，就写成 `air AND bladder AND fistula`。
- `NOT` 会删掉仅仅提及排除词的相关文章。`cancer NOT mouse` 会丢掉讨论人类肿瘤、同时在背景里提到小鼠的论文。排除动物实验优先用 `humans[mh]`，并接受它会漏掉未标引记录。
- 括号可以嵌套。每一层 `OR` 组都要能单独读通。

## 4. 不写字段标签时，PubMed 会改写你的词

未加字段标签、未加引号、未截词的词，走 **Automatic Term Mapping（ATM）**。匹配按这个顺序，命中一个表就停止：

1. 主题翻译表：MeSH、入口词、副主题词、文献类型、药理作用、物质补充概念、英美拼写、单复数、商品名到通用名、部分 UMLS 同义词。
2. 期刊翻译表：全名、缩写、ISSN。
3. 作者索引。
4. 合作者（investigator）索引。
5. 仍无匹配：把短语拆开，对每个词重复上述过程；最后把各词 AND 起来，在全字段里检索。

主题表命中后，PubMed 同时检索该 MeSH（含下位词）和全字段。例如 `child rearing` 会被翻译成类似：

```text
"child rearing"[MeSH Terms] OR ("child"[All Fields] AND "rearing"[All Fields]) OR "child rearing"[All Fields]
```

入口词会带到正式主题词。`odontalgia` 会映射到 MeSH `toothache`，并保留 `odontalgia` 的全字段检索。

以下写法会**关闭** ATM，不再自动扩展下位 MeSH、同义词和拼写变体：

- 双引号短语
- 连字符强制短语
- 截词 `*`
- 字段标签（`[ti]`、`[tiab]`、`[mh]` 等）
- 邻近检索

所以自由词精确检索要自己补同义词；主题检索要把词放进 `[mh]`，而不是只加引号。

网页 Advanced Search 的 History 里展开 **Search Details**，可以看到每个词被翻译成了什么。翻译不符合主题时，改用字段标签重写，不要靠同一条字符串多跑几次碰运气。

## 5. 短语

多个词要按词组检索时，用下面任一形式：

```text
"kidney allograft"
kidney allograft[tiab]
kidney-allograft
```

差别：

- 双引号：短语不在短语索引里时，引号被忽略，词重新走 ATM，结果页会出现 “Quoted phrase not found in phrase index”。
- 字段标签：短语不在索引里时被拆开。标签是 `[all]` 时，拆开的词仍可能映射到 MeSH。要禁止映射，写成 `"heart attack"[all]`。
- 连字符：短语不在索引里时，这个短语贡献 0 条，不会退回单词检索。连字符短语若正好是 MeSH 或入口词，仍会映射；要禁止映射，写成 `"heart-attack"`。

短语检索不再纳入该 MeSH 的下位词。`"health planning"` 命中标引了 Health Planning 的记录，不会自动带上 Health Care Reform 等更细主题。

短语索引没收录、但词确实相邻时，用距离为 0 的邻近检索（见第 7 节）。

## 6. 截词

`*` 代表 0 个或多个字符。

```text
colo*
organi*ation*
"vaccin* schedul*"
"breast feed*"
breast feed*[tiab]
breast-feed*
"colo* cancer*"
```

限制：

- 第一个 `*` 之前至少 4 个字符。`cat*` 无效，星号会被当成普通字符处理并可能转成空格。
- 可以放在词中间，一个词里也可以有多个 `*`。
- 截词关闭 ATM。`"heart attack*"` 不会映射到 Myocardial Infarction，也不会带上下位词。
- 截词不能和邻近检索一起用。引号里若有 `*`，`~N` 会被忽略。

截词适合已经决定做短语或自由词、需要覆盖单复数和英美拼写的场合，例如 `"tumo*r associated macrophage*"`。它不适合代替 MeSH。

## 7. 邻近检索

多个词可以任意顺序出现，中间最多隔 N 个词：

```text
"search terms"[字段:~N]
```

```text
"rationing healthcare"[Title:~2]
"patient physician relationship"[tiab:~0]
"hip pain"[ti:~4] AND stretching
"accidental overdose"[tiab:~3] AND acetaminophen
```

规则：

- 只适用于标题 `[ti]` / `[Title]`、标题摘要 `[tiab]` / `[Title/Abstract]`、单位 `[ad]` / `[Affiliation]`。
- 引号内至少两个词。词序不能指定；要固定词序用第 5 节的短语。
- `N` 是词与词之间允许插入的最大词数。`N=0` 表示彼此相邻，中间没有其他词，顺序仍不限。
- `N` 越大越宽，也越容易混进弱相关记录。`N` 很大时，往往不如直接 `AND`。
- 关闭 ATM，且不能同时截词。
- 引号内的布尔词和停用词按普通词检索。
- 单位字段里，`N≤1000` 时，这些词必须出现在**同一条**单位中，而不是散落在不同作者的单位里。

单位示例：

```text
"Hopkins Bloomberg Public"[ad:~45]
```

## 8. 字段标签

标签放在词后面，用方括号。大小写和空格不敏感：`crabs [mh]` 与 `Crabs[mh]` 相同。

```text
UCLA[ad]
"heart failure"[tiab]
covid-19[ti] AND vaccine[ti] AND children[ti]
```

注意：

- 标签关闭 ATM，只在该字段里找你写的词。
- 一个标签加在多个词后面时，这些词按短语检索：`kidney allograft[tiab]`。
- 每个词都要落在同一字段、但不必成短语时，逐个加标签。词与词之间仍是 AND。
- 全称和简称都能用，例如 `[Title/Abstract]` 与 `[tiab]`，`[Publication Type]` 与 `[pt]`，`[MeSH Terms]` 与 `[mh]`。

常用标签：

| 标签 | 字段 | 用来找 |
| --- | --- | --- |
| `[all]` | All Fields | 与不写标签类似，走 ATM。日期类字段不在全字段检索里 |
| `[ti]` | Title | 标题 |
| `[tiab]` | Title/Abstract | 标题、摘要、作者关键词 |
| `[tw]` | Text Word | 标题、摘要、MeSH、副主题词、文献类型、物质名、团体作者、作者关键词等 |
| `[mh]` | MeSH Terms | 主题词。入口词会映射到正式词。默认包含下位词 |
| `[majr]` | MeSH Major Topic | 标成主要主题的 MeSH |
| `[sh]` | MeSH Subheading | 副主题词，不绑在某个主题上 |
| `[nm]` | Supplementary Concept | 补充概念（化学物质、方案、疾病或生物） |
| `[pa]` | Pharmacological Action | 药理作用 |
| `[pt]` | Publication Type | 文献类型。默认包含更细的类型 |
| `[au]` | Author | 个人作者 |
| `[1au]` | First Author | 第一个人作者 |
| `[lastau]` | Last Author | 最后一个个人作者 |
| `[fau]` | Full Author Name | 2002 年起的作者全名 |
| `[cn]` | Corporate Author | 团体作者 |
| `[ir]` | Investigator | 合作者 |
| `[ad]` | Affiliation | 作者单位 |
| `[ta]` | Journal | 期刊全名、缩写或 ISSN |
| `[la]` | Language | 语种 |
| `[dp]`、`[pdat]` | Publication Date | 发表日期 |
| `[epdat]` | Electronic Date | 电子出版日期 |
| `[ppdat]` | Print Date | 纸质出版日期 |
| `[edat]` | Entry Date | PubMed 处理用入库日期，Most Recent 排序用它 |
| `[crdt]` | Create Date | 记录首次创建日期。定期查新用它比 `[dp]` 全 |
| `[mhda]` | MeSH Date | 加上 MeSH 的日期 |
| `[lr]` | Modification Date | 记录最近修订日期 |
| `[pmid]` | PMID | PubMed 标识符 |
| `[aid]` | Article Identifier | 出版商给的 DOI 等 |
| `[lid]` | Location ID | 用作定位的 DOI 或出版商 ID |
| `[gr]` | Grants and Funding | 基金号、资助机构、国家 |
| `[sb]`、`[filter]` | Subset / Filter | 子集和侧栏过滤器 |
| `[si]` | Secondary Source ID | GenBank、ClinicalTrials.gov 等登录号 |
| `[rn]` | EC/RN Number | CAS、EC、UNII |
| `[jid]` | NLM Unique ID | 期刊的 NLM ID |
| `[pl]` | Place of Publication | 出版国。不参加全字段检索 |
| `[vi]`、`[ip]`、`[pg]` | Volume / Issue / Pagination | 卷、期、首页页码 |
| `[ot]` | Other Term | 作者关键词 |
| `[ps]` | Personal Name as Subject | 作为文章主题的人名 |
| `[auid]` | Author Identifier | ORCID 等 |
| `[isbn]`、`[ed]`、`[book]` | 图书 | ISBN、编者、图书 |

`[edat]`、`[crdt]`、`[mhda]`、`[lr]`、`[dcom]`、`[pl]` 不包含在不加标签的全字段检索里，必须写标签。

## 9. MeSH 主题词

MEDLINE 标引用 MeSH 描述主题，所以作者写 cardiac failure、标引词仍可能是 Heart Failure。主题词检索能把这些写法收在一起。

```text
"heart failure"[mh]
neoplasms[mh:noexp]
hypertension/therapy[mh]
hypertension/dh[mh]
"plants/genetics"[majr]
benzo a pyrene[mh]
```

规则：

- 默认**下扩**。`neoplasms[mh]` 包含下级的各种肿瘤。只要这一层本身时写 `[mh:noexp]`。
- 入口词可以写进 `[mh]`，PubMed 会映射到正式主题词。只要这个字符串本身、不要映射时，给主题词加双引号。
- 主题词里的括号改成空格：MeSH `Benzo(a)pyrene` 写成 `benzo a pyrene[mh]`。
- 副主题词用斜杠接在主题词后，全称或两字母缩写均可：`neoplasms/diet therapy`、`neoplasms/dh`。一条组合只能直接接一个副主题词。
- 主题词/副主题词组合也会下扩两边。`hypertension/therapy` 会带到 diet therapy、drug therapy，以及更细的高血压主题。只锁这一对时写 `hypertension/therapy[mh:noexp]`。
- `[majr]` 只要文章把该主题标成主要论题的记录。
- 未完成 MEDLINE 标引的记录没有 MeSH，包括部分在线优先发表、预印本，以及不进入 MEDLINE 的期刊。只写 `[mh]` 会丢掉它们。全面检索时用 `(主题词[mh] OR 自由词[tiab])`。

副主题词也可以不绑定主题，单独 AND：

```text
hypertension[mh] AND toxicity[sh]
therapy[sh:noexp]
dh[sh]
```

`[sh]` 同样默认下扩，`[sh:noexp]` 关闭。

常用副主题词：

| 缩写 | 副主题词 | 缩写 | 副主题词 |
| --- | --- | --- | --- |
| AE | Adverse Effects | DT | Drug Therapy |
| TU | Therapeutic Use | TH | Therapy |
| PC | Prevention and Control | DI | Diagnosis |
| ET | Etiology | EP | Epidemiology |
| MO | Mortality | CO | Complications |
| CI | Chemically Induced | PO | Poisoning |
| PK | Pharmacokinetics | PD | Pharmacology |
| AI | Antagonists and Inhibitors | AG | Agonists |
| SU | Surgery | RT | Radiotherapy |
| DH | Diet Therapy | DG | Diagnostic Imaging |

`DU` 不是合法缩写。药物不良反应用 `AE`，治疗应用用 `TU`。完整表以 [MeSH 副主题词](https://www.ncbi.nlm.nih.gov/mesh) 当年清单为准；上表只覆盖写临床检索式时最常用的一批。

## 10. 文献类型

文献类型用 `[pt]`，默认包含更细的类型。只要这一层、不要下层时用 `[pt:noexp]`。官方例子是 `review[pt:noexp]`。当年层级以 MeSH Browser 的 Publication Formats 树为准。

```text
"randomized controlled trial"[pt]
"systematic review"[pt]
"meta-analysis"[pt]
guideline[pt]
"practice guideline"[pt]
"case reports"[pt]
preprint[pt]
"retracted publication"[pt]
```

因此 `clinical trial[pt]` 会带上随机对照试验等更细类型；`review[pt]` 会带上树里位于 Review 之下的类型。想要「只要系统综述的文献类型标签」就写 `"systematic review"[pt]`，不要写 `review[pt]`。

PubMed 侧栏的 **Systematic Review 过滤器**比 `"systematic review"[pt]` 宽，检索式是：

```text
lyme disease AND systematic[sb]
```

`systematic[sb]` 除文献类型外还有一套策略，能捞到尚未标引的系统综述。只要已被标上该类型的记录时，才用 `"systematic review"[pt]`。

本仓库自动追加的是 `[pt]` 精确类型，不是 `systematic[sb]`。见第 16 节。

可检索的文献类型如下。带 `*` 的已经停用：旧记录上还有，可以用 `[pt]` 检索，新记录不再标，侧栏过滤器里也没有。

Adaptive Clinical Trial；Address；Autobiography `*`；Bibliography `*`；Biography；Case Reports；Clinical Conference `*`；Clinical Study；Clinical Trial；Clinical Trial, Phase I；Clinical Trial, Phase II；Clinical Trial, Phase III；Clinical Trial, Phase IV；Clinical Trial Protocol；Clinical Trial, Veterinary；Collected Work；Comment；Comparative Study；Conference Proceedings；Consensus Development Conference, NIH `*`；Consensus Statement；Controlled Clinical Trial；Corrected and Republished Article；Dataset；Dictionary `*`；Directory `*`；Duplicate Publication；Editorial；Electronic Supplementary Materials；English Abstract；Equivalence Trial；Evaluation Study；Evidence Synthesis；Expression of Concern；Festschrift；Government Publication `*`；Guideline；Historical Article；Interactive Tutorial `*`；Interview；Introductory Journal Article；Journal Article；Lecture；Legal Case `*`；Legislation `*`；Letter；Meta-Analysis；Multicenter Study；Network Meta-Analysis；News；Newspaper Article `*`；Observational Study；Observational Study, Veterinary；Overall `*`；Patient Education Handout；Periodical Index `*`；Personal Narrative；Portrait `*`；Practice Guideline；Pragmatic Clinical Trial；Preprint；Published Erratum；Randomized Controlled Trial；Randomized Controlled Trial, Veterinary；Research Support, American Recovery and Reinvestment Act；Research Support, N.I.H., Extramural；Research Support, N.I.H., Intramural；Research Support, Non-U.S. Gov't；Research Support, U.S. Gov't, Non-P.H.S.；Research Support, U.S. Gov't, P.H.S.；Retracted Publication；Retraction Notice；Review；Scientific Integrity Review `*`；Scoping Review；Seminal Article `*`；Systematic Review；Technical Report `*`；Twin Study；Validation Study；Video-Audio Media；Webcast。

多词类型加引号，避免被拆开。

撤稿不要只靠眼睛扫标题：

```text
NOT (hasretractionin OR "retracted publication"[pt])
```

侧栏 Retracted Publication 过滤器的等价式是 `hasretractionin OR "retracted publication"[pt]`。把它 AND 进检索式会只留下撤稿；排除时要放在 `NOT` 后面。撤稿通知本身是 `hasretractionof OR "retraction notice"[pt]`。

## 11. 日期

单个日期写成 `yyyy/mm/dd[字段]`，月和日可省略。范围用冒号。和主题组合时写上 `AND`。

```text
cancer AND 2020/06/01[dp]
"heart disease" AND 2019/01/01:2019/06/30[dp]
influenza AND 2000:2010[dp]
"last 30 days"[dp]
"last 6 months"[dp]
"last 5 year"[dp]
```

相对日期的官方格式是 `"last X days"`、`"last X months"`、`"last X year"`。`year` 用单数。相对发表日期还会带上发表日期晚于今天的记录。

| 标签 | 含义 | 何时用 |
| --- | --- | --- |
| `[dp]` | 发表日期。电子日期晚于纸质日期时，不把该电子日期算进 `[dp]` | 限制文章何时发表 |
| `[epdat]` | 只要电子出版日期 | 区分在线发表 |
| `[ppdat]` | 只要纸质出版日期 | 区分印刷日期 |
| `[crdt]` | 记录首次进入 PubMed 的日期 | 上周查过、今天查新 |
| `[edat]` | 处理用入库日期 | 与 Most Recent 排序一致 |
| `[mhda]` | 标上 MeSH 的日期 | 查新近标引 |

查新优先用 `[crdt]`。文章何时发表和记录何时进入 PubMed 不是同一天。

没有月份的日期按 1 月处理，跨月按起始月，没有日的按当月 1 日。季节：winter=1 月，spring=4 月，summer=7 月，fall=10 月。

## 12. 过滤器：人类、年龄、性别、全文、语种

这些字符串与 PubMed 侧栏过滤器等价。物种、性别、年龄都依赖 MEDLINE 标引，预印本、在线优先发表和未标引记录会被排除。

| 目的 | 检索式 |
| --- | --- |
| 人类 | `humans[mh]` |
| 侧栏 Other animals | `"animals"[mh:noexp]` |
| 女性 | `female[mh]` |
| 男性 | `male[mh]` |
| 英文 | `english[la]` |
| 中文 | `chinese[la]` 或 `chi[la]` |
| 日文 | `jpn[la]`（不是 `jap`） |
| 有摘要 | `hasabstract` |
| 有结构式摘要 | `hasstructuredabstract` |
| 有全文链接 | `full text[sb]` |
| 免费全文 | `free full text[sb]` |
| PMC 免费全文 | `"pubmed pmc"[sb]` |
| 已标引 MEDLINE | `medline[sb]` |
| 不标引 MEDLINE | `pubmednotmedline[sb]` |
| 在线优先发表 | `pubstatusaheadofprint` |
| 排除预印本 | `NOT preprint[pt]` |
| 有作者关键词 | `haskeyword` |
| 有利益冲突声明 | `hascois` |
| 有外部数据库登录号 | `hasdatabanklist` 或 `data[sb]` |
| 图书 | `"pubmed books"[sb]` |

`animals[mh]` 会下扩，人类在 MeSH 动物树下，所以它**包含人类**。侧栏 Other animals 是 `"animals"[mh:noexp]`，只命中标了 Animals 这一层、不含下位物种的记录。若要「小鼠、大鼠等非人类研究」，按物种写 MeSH，例如 `mice[mh]`；若要「全部动物标引但去掉人类」，可以写 `animals[mh] NOT humans[mh]`，这不是侧栏那条过滤器。

年龄：

| 侧栏年龄 | 检索式 |
| --- | --- |
| 儿童，出生至 18 岁 | `(infant[mh] OR child[mh] OR adolescent[mh])` |
| 新生儿，出生至 1 个月 | `infant, newborn[mh]` |
| 婴儿，出生至 23 个月 | `infant[mh]` |
| 婴儿，1–23 个月 | `infant[mh:noexp]` |
| 学龄前，2–5 岁 | `child, preschool[mh]` |
| 儿童，6–12 岁 | `child[mh:noexp]` |
| 青少年，13–18 岁 | `adolescent[mh]` |
| 成人，19 岁及以上 | `adult[mh]` |
| 青年，19–24 岁 | `"young adult"[mh]` |
| 成人，19–44 岁 | `adult[mh:noexp]` |
| 45 岁及以上 | `(middle aged[mh] OR aged[mh])` |
| 中年，45–64 岁 | `middle aged[mh]` |
| 65 岁及以上 | `aged[mh]` |
| 80 岁及以上 | `aged, 80 and over[mh]` |

`adult[mh]` 会下扩，包含青年、中年和老年。只要 19–44 岁这一层时用 `adult[mh:noexp]`。`infant[mh]` 包含新生儿；只要 1–23 个月时用 `infant[mh:noexp]`。

语种过滤会丢掉有英文摘要的非英文论文。只在确实不需要其他语言时使用。

处理状态：`publisher[sb]`、`inprocess[sb]`、`medline[sb]`、`pubmednotmedline[sb]`。新进入、尚未标引的记录多在 publisher 或 in process。

## 13. Clinical Queries：可直接粘贴的研究设计过滤器

PubMed Clinical Queries 的临床研究类别没有短标签名。把下面括号里的整段 AND 到主题后面。敏感度/特异度是 NLM 公布的过滤器性能，不是你这个题目的命中率。Broad 少漏、多噪声；Narrow 更干净、更容易漏。

疗法，broad（敏感度 99%，特异度 70%）：

```text
((clinical[Title/Abstract] AND trial[Title/Abstract]) OR clinical trials as topic[MeSH Terms] OR clinical trial[Publication Type] OR random*[Title/Abstract] OR random allocation[MeSH Terms] OR therapeutic use[MeSH Subheading])
```

疗法，narrow（93% / 97%）：

```text
(randomized controlled trial[Publication Type] OR (randomized[Title/Abstract] AND controlled[Title/Abstract] AND trial[Title/Abstract]))
```

诊断，broad（98% / 74%）：

```text
(sensitiv*[Title/Abstract] OR sensitivity and specificity[MeSH Terms] OR diagnose[Title/Abstract] OR diagnosed[Title/Abstract] OR diagnoses[Title/Abstract] OR diagnosing[Title/Abstract] OR diagnosis[Title/Abstract] OR diagnostic[Title/Abstract] OR diagnosis[MeSH:noexp] OR (diagnostic equipment[MeSH:noexp] OR diagnostic errors[MeSH:noexp] OR diagnostic imaging[MeSH:noexp] OR diagnostic services[MeSH:noexp]) OR diagnosis, differential[MeSH:noexp] OR diagnosis[Subheading:noexp])
```

诊断，narrow（64% / 98%）：

```text
(specificity[Title/Abstract])
```

病因，broad（93% / 63%）：

```text
(risk*[Title/Abstract] OR risk*[MeSH:noexp] OR (risk adjustment[MeSH:noexp] OR risk assessment[MeSH:noexp] OR risk factors[MeSH:noexp] OR risk management[MeSH:noexp] OR risk taking[MeSH:noexp]) OR cohort studies[MeSH Terms] OR group[Text Word] OR groups[Text Word] OR grouped [Text Word])
```

病因，narrow（51% / 95%）：

```text
((relative[Title/Abstract] AND risk*[Title/Abstract]) OR (relative risk[Text Word]) OR risks[Text Word] OR cohort studies[MeSH:noexp] OR (cohort[Title/Abstract] AND study[Title/Abstract]) OR (cohort[Title/Abstract] AND studies[Title/Abstract]))
```

预后，broad（90% / 80%）：

```text
(incidence[MeSH:noexp] OR mortality[MeSH Terms] OR follow up studies[MeSH:noexp] OR prognos*[Text Word] OR predict*[Text Word] OR course*[Text Word])
```

预后，narrow（52% / 94%）：

```text
(prognos*[Title/Abstract] OR (first[Title/Abstract] AND episode[Title/Abstract]) OR cohort[Title/Abstract])
```

临床预测，broad（96% / 79%）：

```text
(predict*[Title/Abstract] OR predictive value of tests[MeSH Terms] OR score[Title/Abstract] OR scores[Title/Abstract] OR scoring system[Title/Abstract] OR scoring systems[Title/Abstract] OR observ*[Title/Abstract] OR observer variation[MeSH Terms])
```

临床预测，narrow（54% / 99%）：

```text
(validation[Title/Abstract] OR validate[Title/Abstract])
```

病因 broad 的原文在 `grouped` 与 `[Text Word]` 之间有一个空格，上面按原文保留。

用法：

```text
("heart failure"[mh] OR "heart failure"[tiab]) AND (empagliflozin[tiab] OR dapagliflozin[tiab]) AND (randomized controlled trial[Publication Type] OR (randomized[Title/Abstract] AND controlled[Title/Abstract] AND trial[Title/Abstract]))
```

COVID-19 与医学遗传学可以用短过滤器名：

```text
remdesivir AND LitCGeneral[Filter]
"sickle cell anemia" AND "genetic counseling"[Filter]
```

COVID 类别：`LitCGeneral`、`LitCMechanism`、`LitCTransmission`、`LitCDiagnosis`、`LitCTreatment`、`LitCPrevention`、`LitCCaseReport`、`LitCForecasting`、`LitCLongCOVID`。

医学遗传学类别：Diagnosis、Differential Diagnosis、Clinical Description、Management、Genetic Counseling、Molecular Genetics、Genetic Testing、Medical Genetics。多词名称加引号再加 `[Filter]`。

## 14. 作者、期刊和标识符

作者：

```text
brody[au]
"smith j"[au]
fauci as[au]
"o'brien j"[au]
vollmer charles jr[fau]
smith ja[1au]
smith ja[lastau]
world health organization[cn]
```

- 姓加最多两个首字母，不加句点。后缀放在最后：`o'brien jc jr`。
- 不加引号时，作者名会自动截断以覆盖不同首字母。`o'brien j[au]` 会命中 `o'brien ja`、`o'brien jb`。只要完全一致时加引号：`"o'brien j"[au]`。
- 全名检索只覆盖约 2002 年以后有全名的记录。顺序可以是 `julia s wong` 或 `wong julia s`。
- 姓和名容易颠倒时，姓后面加逗号：`james, ryan`。
- 多个作者都写 `[au]`，避免被当成一个全名：`ryan[au] AND james[au]`。
- 2000 年以前的团体作者可能留在标题里，完整检索时加 `[ti]`。

期刊：

```text
"mol biol cell"[ta]
"science"[ta]
0021-9258[ta]
```

用全名、标准缩写或 ISSN。标题里的括号、方括号和 `&` 去掉再搜，例如 `j hand surg am`。加引号并加 `[ta]` 可关闭「另一种刊名」的自动映射。

标识符：

```text
17170002
16381840[pmid]
lipman AND 16381840[pmid]
"10.1056/NEJMoa2032183"[aid]
PMC2600426
```

- 只输入若干 PMID、用空格分开时，PubMed 把它们 OR 起来。和主题词组合时，PMID 必须加 `[pmid]`。
- DOI 加引号，不要写 `https://doi.org/` 前缀。DOI 可能在 `[aid]` 或 `[lid]`。
- PMCID 直接写 `PMC` 加数字。

基金号可以按编号、机构代码或国家检索：`CA101211[gr]`、`NCI[gr]`、`"intramural nih"[gr]`。

## 15. 停用词和特殊字符

未加引号时，PubMed 丢掉停用词。短语和邻近检索里的停用词是否参与匹配，以 Search Details 为准；邻近检索的官方说明是：引号内的停用词和布尔词按普通词检索。

停用词全文：

a, about, again, all, almost, also, although, always, among, an, and, another, any, are, as, at, be, because, been, before, being, between, both, but, by, can, could, did, do, does, done, due, during, each, either, enough, especially, etc, for, found, from, further, had, has, have, having, here, how, however, i, if, in, into, is, it, its, itself, just, kg, km, made, mainly, make, may, mg, might, ml, mm, most, mostly, must, nearly, neither, no, nor, obtained, of, often, on, our, overall, perhaps, pmid, quite, rather, really, regarding, seem, seen, several, should, show, showed, shown, shows, significantly, since, so, some, such, than, that, the, their, theirs, them, then, there, therefore, these, they, this, those, through, thus, to, upon, various, very, was, we, were, what, when, which, while, with, within, without, would.

小写 `and`、`or`、`not` 在这张表的行为里会被忽略。运算符必须大写，见第 3 节。

在检索语法里有特殊含义的字符：

| 字符 | 作用 |
| --- | --- |
| `( )` | 分组 |
| `[ ]` | 字段标签 |
| `&` | AND |
| `\|` | OR |
| `/` | MeSH 与副主题词 |
| `:` | 日期或范围 |
| `"` | 短语 |
| `-` | 强制短语 |
| `#` | 紧挨数字时表示网页 History，如 `#1 AND #2` |
| `*` | 截词 |
| `~` | 邻近距离 |

`! # $ % + . , ; < > = ? \ ^ _ { } '` 以及不能构成合法截词的 `*`、不在邻近语法里的 `~`，会转成空格。重音字母按无重音处理（é=e）。希腊字母转成英文拼写（α=alpha，β=beta）。

`#1` 只在浏览器的 PubMed History 里有效，约 8 小时无操作后过期。E-utilities 没有这套 History，接口里要写完整检索式。

## 16. 在本仓库里，检索式怎么生成和执行

MKB 不把用户的中文原句直接送给 PubMed。模型先判断这轮发言和对话的关系，再写 1 到 3 条英文检索式。实现在 `backend/app/pipeline.py`。

模型被要求：

- 每条保持简短，使用 MeSH 风格词汇、同义词和简单的 `AND` / `OR`。
- `AND`、`OR`、`NOT` 大写；多词术语加引号。
- **不要**自己写 `[pt]`、`[MeSH Terms]`、人类限制或年份。研究设计由程序追加。
- 只要求缩短、翻译或换说法时，检索式为空，本轮不重新检索。

程序只给第一条检索式追加设计过滤，作为额外的优先查询，而不是替换原来的宽检索。优先查询失败时忽略，宽检索结果仍然保留。

| 问题类型 | 追加到第一条后面的过滤 |
| --- | --- |
| treatment、prevention | `"systematic review"[pt]`、`"meta-analysis"[pt]`、`"network meta-analysis"[pt]`、`guideline[pt]`、`"practice guideline"[pt]`、`"randomized controlled trial"[pt]`，彼此 OR |
| diagnosis | 上面的综述类，再 OR `"validation study"[pt]`、`"evaluation study"[pt]` |
| prognosis、etiology | 综述类，再 OR `"observational study"[pt]` |
| mechanism、other | 不追加 |

实际形态：

```text
("heart failure") AND ("systematic review"[pt] OR "meta-analysis"[pt] OR "network meta-analysis"[pt] OR "guideline"[pt] OR "practice guideline"[pt] OR "randomized controlled trial"[pt])
```

这是文献类型标签，不是第 13 节那套 Clinical Queries。它不包含 `random*[tiab]`，也覆盖不到尚未标上 `[pt]` 的新文章。宽检索式仍然会先执行。

执行方式（`backend/app/pubmed.py`）：

- 接口是 `esearch.fcgi`，`db=pubmed`，`sort=relevance`（Best Match）。
- 按检索式顺序翻页，凑满 `TARGET_PMIDS`（默认 100）为止。
- 优先查询再额外加入最多 15 篇还没出现过的 PMID。
- 文献类型含 Retracted Publication 的记录不进入证据。
- 全文名额优先给相关且有 PMC 的文章，并给高证据类型留少量位置。

因此本仓库的宽检索式宜短、宜用同义词 OR，不要预先堆上年份和 `[pt]`。设计过滤已经会占掉优先名额。

## 17. 完整例子

例 1，疗效。成人，SGLT2 抑制剂用于心衰，要系统综述和随机对照试验，2019 年起，排除撤稿。

```text
(
  "heart failure"[mh] OR "heart failure"[tiab] OR "cardiac failure"[tiab]
)
AND
(
  "sodium-glucose transporter 2 inhibitors"[mh]
  OR "sglt2 inhibitor*"[tiab]
  OR "sglt-2 inhibitor*"[tiab]
  OR dapagliflozin[tiab]
  OR empagliflozin[tiab]
)
AND
(
  systematic[sb]
  OR "randomized controlled trial"[pt]
)
AND humans[mh]
AND 2019:2026[dp]
NOT (hasretractionin OR "retracted publication"[pt])
```

若结果太少，先去掉 `humans[mh]` 和年份，再考虑去掉设计过滤。若结果太杂，把药物类的自由词改成 `[ti]`，或换第 13 节的疗法 narrow。

例 2，诊断。高敏肌钙蛋白排除急性心梗。

```text
(
  "troponin"[mh] OR "high sensitivity troponin"[tiab] OR "hs-ctn"[tiab] OR "hs-tn"[tiab]
)
AND
(
  "myocardial infarction"[mh] OR "acute coronary syndrome"[mh]
)
AND
(
  "sensitivity and specificity"[mh]
  OR "predictive value of tests"[mh]
  OR specificity[tiab]
)
```

诊断 narrow 只有 `specificity[tiab]`，很紧，适合第二轮而不是第一轮。

例 3，药物不良反应。他汀与肌病，用副主题词而不是在自由词里写 side effect。

```text
(statins[mh] OR statin*[tiab]) AND ("muscular diseases/chemically induced"[mh] OR (myalgia[tiab] OR myopathy[tiab] OR rhabdomyolysis[tiab]))
```

例 4，只查一篇已知文献。不要写布尔式。

```text
"10.1056/NEJMoa2032183"[aid]
```

或把标题贴进检索框，让引用识别去配。标题检索不是字段检索式。

例 5，查某单位近年的随机对照试验。

```text
"Peking Union Medical College"[ad:~8] AND "randomized controlled trial"[pt] AND "last 5 year"[dp]
```

## 18. 写完后核对

在 [Advanced Search](https://pubmed.ncbi.nlm.nih.gov/advanced/) 把检索式粘进 Query box，用 Add to History 看命中数，展开 Search Details 看翻译。

逐项看：

1. 每个 `OR` 组是否都有括号，运算符是否大写。
2. Search Details 里有没有把缩写映射到无关 MeSH。有的话，给该缩写加引号和 `[tiab]`。
3. 有没有 “Quoted phrase not found”。有的话改邻近检索，或拆成 AND。
4. 只写了 `[mh]` 时，是否接受丢掉未标引记录。不接受就加 `[tiab]` 同义词。
5. `[pt]` 是否下扩过宽。`review[pt]` 通常比想要的综述更宽。
6. `NOT` 去掉的是不是一整类文献，而不是一个偶然出现的词。
7. 把主题块逐个删掉重跑，确认没有某一块写成了 0 结果。0 结果的常见原因是短语不在索引、字段标签拼错、截词不足 4 个字符。

网页 History 可以写成 `#1 AND #2`。交给 E-utilities 或本仓库之前，展开成完整字符串。

## 19. 常见错误

| 写法 | 实际效果 | 改法 |
| --- | --- | --- |
| `and` / `or` 小写 | 被当成停用词丢掉 | 写成 `AND` / `OR` |
| `a OR b AND c` | 从左到右，c 管不到你以为的范围 | `(a OR b) AND c` |
| `"heart attack"` | 关闭 ATM，不再映射到 myocardial infarction | 主题用 `[mh]`，自由词另列同义词 |
| `review[pt]` | 包含树下更细的综述类型 | 写明 `"systematic review"[pt]` 或 `systematic[sb]` |
| `animals[mh]` | 包含人类 | 人类用 `humans[mh]` |
| `cat*` | 不足 4 个字符，不构成截词 | 写完整词，或换一个更长的词干 |
| `"hip pain"[tiab:~2]` 里再写 `pain*` | 邻近被忽略 | 截词和邻近分开写 |
| `10.1056/NEJMoa2032183` 不加引号 | 标点被拆开 | `"10.1056/NEJMoa2032183"[aid]` |
| `smith j[au]` | 命中 smith ja、smith jb 等 | 只要这一形式时用 `"smith j"[au]` |
| 在本仓库的宽检索式里写 `[pt]`、人类和年份 | 和系统追加的设计过滤叠在一起，优先查询变窄 | 宽检索只留疾病和干预 |

## 20. 来源

- [PubMed User Guide](https://pubmed.ncbi.nlm.nih.gov/help/)：布尔运算、ATM、短语、截词、邻近、字段、日期、过滤器和停用词。
- 同一指南中的 Filter search strategies：人类、年龄、性别、全文、系统综述和撤稿的等价检索式。
- 同一指南中的 Clinical Study Categories：第 13 节全文抄录的疗法、诊断、病因、预后和临床预测过滤器。
- 本仓库 `backend/app/pipeline.py` 的 `design_filter_query`，以及 `backend/app/pubmed.py` 的 `esearch` 参数。
