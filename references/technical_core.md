# Technical Core

本文件记录 `sci-manuscript-skill` 长期需要保持稳定和持续优化的技术子系统。它面向维护、架构审计和发布审计，不是普通稿件工作的操作指南。评价优先级固定为：正确性、确定性、可维护性、性能、功能广度。

| # | Subsystem | Core problem | Current solution | Status | Optimization policy |
|---|---|---|---|---|---|
| 1 | TeX line locations | 将 reviewer change 映射到最终可见行号 | `lineno` + `\linelabel` + AUX | STABLE / FROZEN | 仅在真实复杂 AMS 需求、引擎兼容性回归或 `lineno` 失效时重开 |
| 2 | Revision change detection | 从 parent/current 找出 current 中应高亮的内容 | `latexdiff` addition evidence + current-source renderer | WATCH | 只修复可复现的 false positive/negative，不扩张为通用 TeX AST |
| 3 | Review provenance | 分离 WHAT changed 与 WHO caused it | current-source `\review` parser + sidecar intervals | STABLE / CONSERVATIVE | 语法和错误上下文可加固，ownership 语义保持冻结 |
| 4 | Revision/version state | 冻结、选择和重建历史 round | immutable per-round state + manifest/hash | WATCH | 仅针对真实历史重建或事务失败修复 |
| 5 | Bibliography/citation state | 以 BibTeX key 保持历史引用身份 | current full DB + resolved cited snapshot | WATCH | 新 backend 或依赖语义出现时扩展闭包规则 |
| 6 | Build/artifact freshness | 区分 PDF 存在与 PDF 当前有效 | content digest + artifact-specific dependencies | WATCH | 优先补齐真实漏依赖；不建设通用 cache framework |
| 7 | Template/resource migration | 升级资源同时保护用户修改与冻结状态 | ownership taxonomy + known-stock migration + archive | WATCH | 只为已知旧资源增加迁移器；未知定制继续 fail closed |

## 1. TeX line locations

### Problem

把 reviewer-owned 可见修订映射为最终 marked manuscript 中的连续行号，同时不把页码、公式编号、脚注编号、上下标数字或表格数字误认成行号。

### Hard invariants

- 行号必须来自最终排版使用的 TeX 行号机制。
- instrumentation 前后可见 word/bbox 序列完全一致。
- CJK、Latin、混排、多行正文、行内公式、`equation`、`equation*`、citation 和 bibliography 均可定位。
- 只接受 package namespace 下的 start/end label；缺失、冲突、倒序均 fail closed。
- `align`、`align*`、`gather`、`gather*`、`multline`、`multline*`、`displaymath` 和未验证复杂 AMS 环境不猜测位置。

### Candidate approaches

**Approach A — TeX-native `lineno` + `\linelabel` + AUX.** 在 reviewer event 边界写入 package-owned label，由同一次 marked source 编译生成真实行号。

**Approach B — PDF geometry / glyph/bbox mapping.** 从 PDF 字符坐标、数字 glyph 和空间聚类反推行号。

**Approach C — `zref/savepos` 等 TeX-native position reference.** 在 TeX 中记录绝对页内坐标，再建立位置到行号的二次映射。

### Evaluation

| Criterion | A | B | C |
|---|---|---|---|
| Correctness | 高：读取 TeX 行号 | 低：数字类别易混淆 | 中：坐标准确但不是行号 |
| Determinism | 高：AUX label 可复查 | 中：依赖 PDF 提取器 | 高：坐标写入 AUX |
| Scientific/document fidelity | 高：不改 scientific source | 中：后处理不改源但会猜测 | 高：marker 不改科学内容 |
| Failure behavior | 高：缺 label 明确失败 | 低：常以错误数字“成功” | 中：仍需映射规则 |
| Layout neutrality | 已用 word/bbox identity 证明 | 后处理本身中立 | marker 可中立，映射需额外层 |
| Historical reproducibility | 高 | 中：依赖 PDF 工具版本 | 中：依赖坐标解释器 |
| Performance | 高：提取约 0.01 s | 低：历史实测约 5.48 s | 中：需额外映射 pass |
| Code complexity | 低 | 高 | 中高 |
| Dependency burden | `lineno` | Poppler geometry parser | `zref` + 映射器 |
| Maintenance burden | 低 | 高 | 中高 |
| Backward compatibility | 高 | 中 | 中 |
| Testability | 高：可构造 AUX | 中：需要 PDF fixture | 中：坐标易测，行号难测 |

### Experiments / evidence

- `tests/test_tex_locations.py` 覆盖 package label 解析、范围合并、错误上下文、数字 glyph 排除和复杂 AMS fail-closed。
- mixed CJK/Latin/prose/inline math/equation/citation/bibliography 的 instrumented/control PDF word/bbox 完全相同。
- Perspective Formula (6) 的 reviewer event 解析为第 153--158 行。
- `zref/savepos` feasibility probe 可编译，但 AUX 只产生 `posx/posy`，不能直接给出 manuscript line number；继续采用它会重新引入 geometry mapping。

### Decision

选择 Approach A。Approach B 因 false numeric detection、运行成本和启发式失败行为拒绝；Approach C 因只能提供坐标、不能消除二次映射而拒绝。该子系统冻结。

### Current implementation

- Module: `src/sci_manuscript/locations.py`
- Functions: `instrument_location_source`, `parse_location_labels`, `calculate_tex_locations`, `validate_location_math_environments`, `build_review_locations`
- TeX resource: `src/sci_manuscript/resources/revision/location_runtime.tex`
- Integration: `src/sci_manuscript/diff.py::build_marked_manuscript`

### Regression coverage

- `tests/test_tex_locations.py`
- `tests/test_highlight_response.py`
- `tests/test_release_integration.py`

### Known limitations

只验证 `equation` 和 `equation*`。复杂 AMS display 环境明确报 `LINE_LOCATION_UNSUPPORTED_MATH_ENVIRONMENT`。

### Future optimization triggers

- 真实用户明确需要 `align`、`gather` 或 `multline`。
- `lineno`、Tectonic 或 XeTeX 升级造成可复现兼容性回归。
- 新引擎能直接提供稳定、语义明确的可见行号 metadata。

## 2. Revision change detection

### Problem

根据 adjacent parent/current 确定 current 中应高亮的可见内容，同时确保 marked 去除 presentation 后严格等于 clean/current scientific content。

### Hard invariants

- current source 是唯一结构、内容和排版 authority；parent-only deletion 不进入输出。
- `\review`、source formatting、surrounding block change 和 exact move 不得使 unchanged content 变色。
- normalized-identical display equation 对任何 fine/whole highlight 都有 hard veto。
- changed display equation 使用 whole-current-equation 高亮，并保留真实 math semantics。
- citation/reference/math protected ranges 与 60% whole-block、tiny-island 合并合同保持不变。

### Candidate approaches

**Approach A — raw/full `latexdiff` union.** 直接编译包含 addition 和 deletion markup 的合并文档。

**Approach B — `latexdiff` addition evidence + current-source-only renderer.** 只把 addition 当证据，映射回 current source，再做 move suppression、adaptive block、equation identity、citation/math protection 和 provenance rendering。

**Approach C — explicit intent tracking.** 要求作者用 `\add`、`\remove`、`\replace` 显式表达每次修改。

历史备选 custom semantic parser/alignment 不再实现：它扩大了 TeX 语法面、对排版命令敏感，并重复成熟 diff 工具的职责。

### Evaluation

| Criterion | A | B | C |
|---|---|---|---|
| Correctness | 中：union 可污染 current | 高：输出只来自 current | 高：若人工标注完整 |
| Determinism | 中高 | 高 | 高 |
| Scientific/document fidelity | 低中：union 改结构 | 高：projection 可证明 | 中：intent 宏侵入写作 |
| Failure behavior | 中：TeX 错误晚暴露 | 高：unresolved mapping 明确失败 | 低中：漏标难发现 |
| Layout neutrality | 低中 | 高 | 中高 |
| Historical reproducibility | 中 | 高 | 高 |
| Performance | 中：一次 diff + compile | 中：一次 diff + renderer | 高：无需自动 diff |
| Code complexity | 低表面、高兼容风险 | 中高但职责分层 | 低代码、高流程复杂度 |
| Dependency burden | `latexdiff` | `latexdiff` | 无 diff 依赖 |
| Maintenance burden | 高 | 中 | 高：依赖作者纪律 |
| Backward compatibility | 低 | 高 | 低：要求迁移 |
| Testability | 中 | 高：纯函数 span tests | 中 |

### Experiments / evidence

- `tests/test_highlight_renderer.py` 和 `tests/test_revision_architecture.py` 覆盖 small addition、rewrite、large rewrite、move、CJK/Latin whitespace、citation、inline math、display equation 和 Formula (6)。
- normalized equation identity 忽略 comment、普通 source whitespace 和 line wrapping，但保留 `\text{...}` 等真实语义。
- Perspective object-definition equation normalized-identical，保持 black；Formula (6) 真实改变，whole equation 为 RubineRed。
- tiny unchanged island 仅在 CJK 不超过 5 lexical atoms、Latin 不超过 2 words、局部修改密度至少 80%、provenance 相同、同一 sentence/block 且非 citation/reference/math 时合并。

### Decision

选择 Approach B。它保留成熟 diff evidence，同时将 published output 限定为 current source。Approach A、C 和 custom semantic parser 不进入 production。

### Current implementation

- Detector/orchestration: `src/sci_manuscript/diff.py::run_latexdiff`, `prepare_change_detection_sources`, `build_marked_manuscript`
- Renderer: `src/sci_manuscript/revision_render.py::resolve_equation_spans`, `adaptive_blocks`, `coalesce_tiny_unchanged_islands`, `apply_highlights`
- TeX resource: `src/sci_manuscript/resources/revision/marked_runtime.tex`
- User hooks: `src/sci_manuscript/resources/revision_style.template.tex`

### Regression coverage

- `tests/test_highlight_renderer.py`
- `tests/test_revision_architecture.py`
- `tests/test_revision_style.py`
- `tests/test_release_integration.py`

### Known limitations

大幅重写的单个 block 可能按 60% 规则整体高亮；move suppression 只接受 exact normalized identity；没有 fuzzy semantic alignment、通用 TeX AST 或 Math AST。

### Future optimization triggers

- 出现最小、稳定、可复现的 false-positive/false-negative fixture。
- publisher macro 使 current-source projection 无法保持 identity。
- `latexdiff` 版本变化破坏 addition evidence contract。

## 3. Review provenance

### Problem

独立表示“改变了什么”和“由谁引起”，并把 reviewer/editor ID 映射到 current-source ranges，而不让 ownership wrapper 决定 changed extent。

### Hard invariants

- `\review` 只定义 ownership；完全未修改的 scoped content 仍为 black。
- nested wrapper 继承并按首次出现顺序 union ID。
- comments 中的 wrapper inert；wrapper seam 不制造新段落。
- empty wrapper 可记录 deletion-only provenance，但不拥有可见 bytes。
- parser error 必须包含 file、line、ID、reason 和 context。

### Candidate approaches

**Approach A — current source-range `\review` parser.** 删除 wrapper，生成不相交的 sidecar intervals。

**Approach B — 每个 change 显式携带 reviewer ID.** 将 ownership 与 `\add/\replace` intent macro 绑定。

**Approach C — 从最终颜色或 render 结果反推 ownership.** 把 RubineRed/ForestGreen 当作 provenance source。

### Evaluation

| Criterion | A | B | C |
|---|---|---|---|
| Correctness | 高：ownership 独立 | 高但依赖人工标注 | 低：颜色是结果而非原因 |
| Determinism | 高 | 高 | 低中 |
| Scientific/document fidelity | 高：wrapper 投影可证明 | 中：intent 宏侵入写作 | 低：丢失多 ID |
| Failure behavior | 高：语法错误明确 | 中：漏标难识别 | 低：冲突通常静默 |
| Layout neutrality | 高：最终剥离 wrapper | 中高 | 低 |
| Historical reproducibility | 高 | 高 | 低中 |
| Performance | 高：线性解析 | 高 | 中 |
| Code complexity | 中 | 中 | 高 |
| Dependency burden | 无新增依赖 | 无新增依赖 | PDF/TeX 结果解析 |
| Maintenance burden | 低中 | 中高 | 高 |
| Backward compatibility | 高 | 低 | 中 |
| Testability | 高 | 中 | 低 |

### Experiments / evidence

- `tests/test_provenance.py` 覆盖 single/multiple ID、nested/inherited union、comments、empty deletion、wrapper seam。
- `tests/test_highlight_renderer.py` 覆盖 CJK、math、citation 与 provenance boundary。
- 非法 ID 的 regression 证明错误包含 source file、line、raw ID、validator reason 和 source-line context。

### Decision

选择 Approach A。Approach B 会把 change detection 与 ownership 重新耦合并要求 schema migration；Approach C 无法恢复 multiple IDs、empty deletion 和因果冲突。

### Current implementation

- Module: `src/sci_manuscript/provenance.py`
- Functions/classes: `extract_provenance`, `split_by_review_provenance`, `ProvenanceSource`, `ReviewSpan`
- ID grammar: `src/sci_manuscript/review_ids.py::validate_review_id_list`
- Source audit: `src/sci_manuscript/review.py::_review_ids_with_paths`

### Regression coverage

- `tests/test_provenance.py`
- `tests/test_review_audit.py`
- `tests/test_highlight_renderer.py`
- `tests/test_review_workflow_final.py`

### Known limitations

Ownership 仍由作者显式声明；系统不能从 reviewer prose 或最终颜色可靠推断科学因果。

### Future optimization triggers

- 新的合法 provenance nesting 需求。
- 多文件 flattening 暴露无法定位到原 source file 的真实 parser error。
- reviewer ID grammar 由公开 metadata contract 正式扩展。

## 4. Revision/version state

### Problem

管理 `initial_submission -> revision_01 -> revision_02 -> ...` 的冻结、回滚、重建和历史选择，同时避免失败操作污染 last successful state。

### Hard invariants

- historical scientific state immutable；round ancestry 必须 adjacent。
- historical build 不改变 active round、不刷新 frozen snapshot、不重新编号、不迁移 scientific content。
- failed lifecycle/build 不污染 last successful state。
- successful state 更新通过 staging、archive 和 atomic replace 完成。

### Candidate approaches

**Approach A — mutable current directories only.** 只保留一个可编辑目录，由用户手工复制历史版本。

**Approach B — immutable per-round state snapshots + manifest/hash.** 每轮保留 source directory、creation state、bibliography snapshot 和 build manifest。

**Approach C — 完全依赖 Git commit.** 用 Git tree/commit 作为唯一 scientific state 和 ancestry。

### Evaluation

| Criterion | A | B | C |
|---|---|---|---|
| Correctness | 低：易覆盖历史 | 高 | 高：提交纪律充分时 |
| Determinism | 低 | 高 | 高 |
| Scientific/document fidelity | 中 | 高 | 高 |
| Failure behavior | 低：部分写入 | 高：transaction rollback | 中：工作树状态复杂 |
| Layout neutrality | 不相关 | 不相关 | 不相关 |
| Historical reproducibility | 低 | 高 | 高 |
| Performance | 高 | 高 | 中高 |
| Code complexity | 低 | 中 | 低代码、高外部流程复杂度 |
| Dependency burden | 无 | 无新增依赖 | 强制 Git |
| Maintenance burden | 高人工负担 | 中 | 高用户/仓库负担 |
| Backward compatibility | 低 | 高 | 低 |
| Testability | 低 | 高 | 中：需 Git fixture |

### Experiments / evidence

- synthetic active `revision_02` 项目显式 build `revision_01` 后，active round 仍为 2，且未调用 source initialization/mutation。
- failed revision creation 删除 partial round/state/tmp，parent scientific digest 不变。
- rollback/reindex 使用 archive，并验证 scientific bytes 与 editable submission sources 保留。

### Decision

选择 Approach B。Git 可作为外部协作历史，但不能成为 build 的必需 scientific-state backend。

### Current implementation

- Module: `src/sci_manuscript/workspace.py`
- Types/functions: `ProjectConfig`, `load_project`, `start_revision`, `rollback_revision`, `reindex_revisions`, `temporary_run`, `write_build_manifest`
- Lifecycle orchestration: `src/sci_manuscript/api.py::ManuscriptProject`

### Regression coverage

- `tests/test_core.py`
- `tests/test_build_targets.py`
- `tests/test_release_hardening.py`
- `tests/test_release_integration.py`

### Known limitations

round 必须是连续 fixed-width 目录；删除中间 round 后必须显式 reindex。历史 source 可重建，但外部字体和 TeX bundle 仍需由 manifest/toolchain 信息辅助复现。

### Future optimization triggers

- 真实跨机器 historical rebuild 暴露 manifest 缺口。
- 原子 filesystem 语义在新平台出现不兼容。
- lifecycle 需要正式支持非线性 revision ancestry。

## 5. Bibliography/citation state

### Problem

引用显示编号会随内容和 style 改变，但 scientific identity 必须稳定为 BibTeX key；历史 round 需要从当时解析到的引用集合重建。

### Hard invariants

- `references/references.bib` 是 current full DB。
- `state/<round>/bibliography.bib` 是该 round 的 resolved cited snapshot。
- snapshot 保留 cited entries、`crossref`/`xdata` 闭包、必要 `@string`/`@preamble`，不依赖 rendered `[N]`。
- revision 新增 citation 或 full DB 新增无关 entry 不改变 initial snapshot。
- 原始 `.bib` 可包含 `abstract`；skill 不回写、不静默剥离用户字段。

### Candidate approaches

**Approach A — 每轮复制完整 `references.bib`.** 简单冻结整个数据库。

**Approach B — 每轮 snapshot resolved cited entries + dependencies.** 从 successful AUX 或 source fallback 获取 key，并闭包 `crossref/xdata`。

**Approach C — 不保存 bibliography state.** 历史 build 始终读取 current DB，并假设 Git 能恢复旧值。

### Evaluation

| Criterion | A | B | C |
|---|---|---|---|
| Correctness | 高 | 高 | 低：current DB 漂移 |
| Determinism | 高 | 高 | 低中 |
| Scientific/document fidelity | 高但含无关数据 | 高：只保留实际状态 | 低 |
| Failure behavior | 高 | 高：missing dependency 明确失败 | 低：可能静默改变历史 |
| Layout neutrality | 高 | 高 | 低中 |
| Historical reproducibility | 高 | 高 | 低 |
| Performance | 中：大 DB 重复复制 | 高：lean snapshot | 高表面、重建不可靠 |
| Code complexity | 低 | 中 | 低 |
| Dependency burden | 无新增依赖 | 无新增依赖 | 强依赖 Git/外部 DB |
| Maintenance burden | 低代码、高存储 | 中 | 高操作负担 |
| Backward compatibility | 高 | 高 | 低 |
| Testability | 高 | 高 | 低 |

### Experiments / evidence

- citation numbering 改变但 BibTeX key/content 不变时，状态为 unchanged。
- revision 修改 current DB 后，parent snapshot bytes/hash 保持不变；historical source 始终选择 frozen snapshot。
- current full DB 的无关 entry 不进入 cited snapshot。
- `crossref` 和 comma-separated `xdata` dependency closure 均有回归；缺依赖 fail closed。
- Better BibTeX `abstract` 字段被接受，input string 保持逐字不变。

### Decision

选择 Approach B。它比完整复制更 lean，同时保留完整的已解析引用闭包；Approach C 不能满足历史重建。

### Current implementation

- Module: `src/sci_manuscript/bibliography.py`
- Functions: `resolved_citation_keys`, `source_citation_keys`, `citation_only_bibliography`, `sync_bibliography`
- State routing: `src/sci_manuscript/workspace.py::bibliography_source_for_round`, `snapshot_bibliography`
- Visible comparison: `src/sci_manuscript/diff.py::_bibliography_change_states`

### Regression coverage

- `tests/test_bibliography_state.py`
- `tests/test_core.py`
- `tests/test_release_hardening.py`
- `tests/test_release_integration.py`

### Known limitations

BibTeX parser 是保守 top-level scanner，不是完整 BibLaTeX data model；新的 dependency 字段需要显式加入 allowlist 和回归。

### Future optimization triggers

- 真实项目使用当前闭包未覆盖的 BibLaTeX dependency 字段。
- Biber AUX/BCF 输出改变 resolved-key contract。
- snapshot 大小或解析耗时成为可测瓶颈。

## 6. Build/artifact freshness

### Problem

PDF 文件存在不代表它由当前 source、metadata、resource、provenance 和 location state 生成；系统必须把 artifact 分为 `MISSING`、`CURRENT`、`STALE`。

### Hard invariants

- `CURRENT` 同时要求 artifact bytes hash 和 artifact-specific input fingerprints 匹配 manifest。
- source 或 dependency 改变后，旧 PDF 不得继续留在 `output/` 并被视为 current。
- marked 至少依赖 parent/current source、bibliography、provenance、revision style 和 renderer resources。
- response 至少依赖 `responses.tex`、`reviewer_comments.md`、response template、metadata、marked/reference location inputs。
- failed manifest update 保留上一次 successful manifest；successful write 使用 atomic replace。

### Candidate approaches

**Approach A — mtime.** 比较 source/artifact 修改时间。

**Approach B — always rebuild everything.** 每次构建 clean、marked、locations 和 response。

**Approach C — content digest + dependency-aware freshness.** 对每个 artifact 计算最小明确 dependency mapping，并验证 output hash。

### Evaluation

| Criterion | A | B | C |
|---|---|---|---|
| Correctness | 低：copy/clock 会欺骗 | 高 | 高 |
| Determinism | 低 | 高 | 高 |
| Scientific/document fidelity | 低中 | 高 | 高 |
| Failure behavior | 低：常误判 current | 高但代价大 | 高：缺 manifest 即 stale |
| Layout neutrality | 不相关 | 高 | 高 |
| Historical reproducibility | 低 | 高 | 高 |
| Performance | 高但不可靠 | 低 | 高：复用已证明 current 的 artifact |
| Code complexity | 低 | 低 | 中 |
| Dependency burden | 无 | TeX passes 增加 | 无新增依赖 |
| Maintenance burden | 低代码、高事故风险 | 低代码、高运行成本 | 中：需维护 dependency graph |
| Backward compatibility | 中 | 高 | 高 |
| Testability | 中 | 高 | 高：可变更单一 dependency |

### Experiments / evidence

- 修改 `responses.tex` 只使 response stale；clean/marked 仍 current。
- 修改 response template 只使 response stale。
- stale selective build 删除旧 PDF；manifest-verified current PDF 保留。
- response target 可复用 current marked PDF；缺失/陈旧 marked 会重建。
- manifest atomic replace 注入失败后，previous successful manifest bytes 不变。

### Decision

选择 Approach C。mtime 不具内容语义；always rebuild 可作为诊断基线，但不是默认策略。正式状态语义为：文件不存在是 `MISSING`；文件存在且 manifest/output/input 全匹配是 `CURRENT`；其余是 `STALE`。

### Current implementation

- Fingerprints/state: `src/sci_manuscript/workspace.py::_build_input_fingerprints`, `_artifact_input_fingerprints`, `artifact_input_digest`, `build_artifact_is_current`
- Manifest: `src/sci_manuscript/workspace.py::write_build_manifest`
- Target orchestration and stale cleanup: `src/sci_manuscript/api.py::ManuscriptProject.build`, `_remove_stale_output_pdfs`
- Response consistency audit: `src/sci_manuscript/response.py::build_response`

### Regression coverage

- `tests/test_build_targets.py`
- `tests/test_release_hardening.py`
- `tests/test_release_integration.py`

### Known limitations

dependency graph 必须由维护者显式更新；新增 package resource 若未进入 fingerprint，可能形成漏依赖。当前不提供跨项目共享 cache。

### Future optimization triggers

- 新 artifact 或 resource contract 加入 build graph。
- 出现“输入改变但仍被判 CURRENT”的最小 reproducer。
- real E2E 表明 always-rebuild 成本可通过一个简单、可验证的复用点显著降低。

## 7. Template/resource migration

### Problem

package 升级后，旧项目可能保留过时 resource；迁移必须升级已知 stock contract，同时保护用户定制、response scientific body 和 frozen historical state。

### Hard invariants

- ownership 分类决定更新策略：`PACKAGE-OWNED` 每次从安装包 staging；`GENERATED` 可重建；`COPY-ONCE USER-EDITABLE` 只做已知 stock targeted migration；`USER-OWNED` 不自动改；`FROZEN STATE` 不静默迁移。
- 自动迁移必须 deterministic、idempotent、rollback-safe。
- unknown/heavily customized legacy resource 明确停止。
- 迁移不得修改 scientific prose、response body 或 frozen historical content。
- response Latin typography（Times New Roman）是 versioned package-owned template contract。

### Candidate approaches

**Approach A — 直接覆盖旧 resource.** 始终用最新版替换项目副本。

**Approach B — 从不迁移.** 所有升级交给用户手工完成。

**Approach C — ownership + fingerprint/known-stock targeted patch + archive.** 仅识别旧 stock token，验证未被定制，保留无关用户内容并先归档。

### Evaluation

| Criterion | A | B | C |
|---|---|---|---|
| Correctness | 低：覆盖用户修改 | 低中：旧 contract 可失效 | 高：known-stock 范围内 |
| Determinism | 高 | 低：人工过程 | 高：content-digest archive |
| Scientific/document fidelity | 低 | 中 | 高 |
| Failure behavior | 低：静默覆盖 | 中：通常晚失败 | 高：unknown customization 停止 |
| Layout neutrality | 低中 | 中 | 高：targeted hooks only |
| Historical reproducibility | 低 | 高但不可升级 | 高：frozen state 不迁移 |
| Performance | 高 | 不适用 | 高 |
| Code complexity | 低 | 低 | 中 |
| Dependency burden | 无 | 无 | 无新增依赖 |
| Maintenance burden | 高事故成本 | 高人工成本 | 中 |
| Backward compatibility | 低 | 中 | 高 |
| Testability | 高但语义危险 | 低 | 高：stock/custom/no-op/stop |

### Experiments / evidence

- old stock `revision_style.tex` 自动移除旧 semantic color/deletion contract，并保留 required presentation hooks。
- old resource 中无关 `\UserFontChoice` 定制逐字保留。
- latest resource 为 no-op；unknown customized legacy color 返回 `REVISION_STYLE_MIGRATION_UNSUPPORTED`，原文件和 archive state 不变。
- archive directory 使用 source content digest，不使用时间戳/随机值；重复相同 migration 复用一致 archive，冲突 fail closed。
- package-owned response templates 仅在 run staging 中使用，不复制进 round；response body 始终来自 user-owned `responses.tex`。

### Decision

选择 Approach C。只保留一个正式 known-stock migration path；不引入通用 patch framework，也不自动处理未知 v1 workspace。

### Current implementation

- Ownership/staging: `src/sci_manuscript/templates.py::stage_runtime_resources`, `copy_project_scaffold`
- Known-stock migration: `src/sci_manuscript/workspace.py::migrate_revision_style_file`
- Legacy workspace stop: `src/sci_manuscript/workspace.py::_detect_v1_workspace`
- Package resources: `src/sci_manuscript/resources/`

### Regression coverage

- `tests/test_revision_style.py`
- `tests/test_architecture_contract.py`
- `tests/test_release_hardening.py`
- `tests/test_release_integration.py`

### Known limitations

目前只有已知 legacy revision-style contract 支持自动 targeted migration；ambiguous v1 workspace、未知 response/template 定制需要用户先归档并显式迁移。

### Future optimization triggers

- 新版本确实改变一个 copy-once public resource contract。
- 至少一个真实旧项目提供可判定的 stock fingerprint 和用户定制边界。
- package-owned/generated/user-owned taxonomy 被新 artifact 类型突破。
