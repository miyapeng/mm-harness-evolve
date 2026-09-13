# Rollout 评分来源分类

日期：2026-09-10。议题：Q1/Q5。用户要求统计各方法进化期间给一批 rollout 打分的标准来源，而非区分结果评价与诊断职责。未更改本项目评价协议。

## 分类口径

统计进化期间用于评估结果、比较候选的主结果信号；另列最终报告使用什么。B 的反思、失败解释、补丁质量检查不自动算成新的任务评分准则。

“沿用 benchmark 标准”表示保留其任务正确性定义、参考标签、环境成功条件或指标；不保证官方评分代码、judge 型号、执行环境逐字逐项一致。本轮是论文协议核对，不是全部 scorer 源码审计。方法跨多个 benchmark 时保留差异。

在原 31 项中，先单列 17 项冻结权重的 prompt / harness / skill / controller 优化：9 项沿用任务标准；5 项明确使用作者设计的优化期评分或代理；3 项需按任务区分或证据不足。不把这组计数写成整个领域的比例。

## A：沿用 benchmark / 任务正确性标准（9）

| 方法 | 进化期间结果评分 | 最终评价及限定 | 来源 |
|---|---|---|---|
| Meta-Harness | 分类 / 数学正确率；TerminalBench 任务结果 | 对应任务的标准指标；不同任务的评分实现不同 | [§4](https://arxiv.org/abs/2603.28052v1) |
| AutoSaddler | GAIA2 按协议 judge；SWE-Bench Pro 测试；Terminal-Bench 状态测试 | 同类官方协议，在测试集报告 | [附录 B](https://arxiv.org/abs/2608.23041v1) |
| Self-Harness | 对应 benchmark 官方 verifier，生成 Pass 信号 | Terminal-Bench、SWE-bench Verified、AppWorld 的 verifier；另有任务筛选和运行适配 | [§4.1、附录 A.2](https://arxiv.org/abs/2606.09498v3) |
| SHAPER | 环境任务 reward / success；VLABench 成功与 ESI 问题正确性 | 对应任务成功率 / 准确率；视觉 judge 的五级进度分仅用于诊断，不替代任务结果 | [§3–4、附录 A.3](https://arxiv.org/abs/2608.11350v1) |
| HarnessCompass | SWE-bench Verified 任务成功与 Pass@1 | 同一任务成功口径；额外自反馈与改动检查不构成替代结果分数 | [方法、实验设置](https://arxiv.org/abs/2608.01918v1) |
| HarnessLens | benchmark 任务 reward，附加行为归因接纳条件 | TEST 任务 pass@1；不能说完全只靠官方分数接纳，也不能说用自建诊断替代评分 | [§3.2、§4、附录 B](https://arxiv.org/abs/2608.27311v1) |
| Life-Harness | 训练任务反馈及成功表现；无另立通用主观质量分 | 沿用任务协议；AgentBench 明确跟随官方实现，交互任务 user simulator 配置有作者选择 | [§4.4–5.1](https://arxiv.org/abs/2605.22166v2) |
| EvolveNet | 带标签的逐任务结果驱动本地选择及合并；ClawEval 为连续 rubric 分 | BIRD、DS-1000、LCB、SWE-V 的正确性；ClawEval 均分。本轮未逐项审计 scorer 实现 | [§4–6](https://arxiv.org/abs/2608.04968v1) |
| AutoTTS | 基于预采样轨迹回放计算数学答案正确率与成本 | AIME25 / HMMT25 正确率；自建的是回放执行环境，不是另立主观正确性标准 | [§3.2–4](https://arxiv.org/abs/2605.08083v2) |

## B：作者自建优化期评分 / 代理（5）

| 方法 | 进化时用什么 | 最终是否仍按 benchmark 评价 | 来源 |
|---|---|---|---|
| AutoDesign | 根据人工标注样例构建固定 R_meta，规则与 VLM 混合 | 最终用独立固定 PosterBench；不能把论文定义的 PosterBench 当作已核验第三方旧官方协议 | [§3.2、附录 A.4](https://arxiv.org/abs/2608.13560v1) |
| COMFYCLAW | 自建 VLM reward：0.6×需求通过率 + 0.4×细节质量；以此分成败和验证 skill | 最终使用各图像 benchmark 指标，并指定 Qwen3-VL-8B judge；指标沿用不等于原版 scorer 配置完全复用 | [§3.3–3.4、Table 1](https://arxiv.org/abs/2607.01709v1) |
| RHO | 自验证 / 一致性诊断，候选用模型成对偏好 | 进化信号与最终任务效果评价分开；本轮没有逐项审计所有最终 scorer 的官方代码一致性 | [§4、附录 B.5](https://arxiv.org/abs/2606.05922v3) |
| TTHE | 无标签的执行反馈与作者设计 judge；不用隐藏正确性标签选分支 | 最终才用任务正确性评价；ClawEval 附录明确 in-loop grader 关闭，提交版本后 gold grading。其 headroom 任务筛选使用过基线分数，故不能声称整个实验从未触及标签 | [§4、附录 C.1](https://arxiv.org/abs/2607.08124v1) |
| RHI | 作者定义的评价 prompt 驱动模型成对比较新旧产物 | 主实验为作者构造的开放式 ML 任务与评价，不能归成沿用一个既有官方 benchmark scorer | [§3.2、§4](https://arxiv.org/abs/2607.15524v1) |

## C：需要按任务展开，或不能确认“原版官方”（3）

| 方法 | 已确认内容 | 分类限制 | 来源 |
|---|---|---|---|
| GEPA | 外部任务 metric / feedback function 提供标量与反馈；可消费正确答案、执行反馈或人工反馈 | 算法没有统一 scorer，必须看每个实验；不能整体标成纯官方或自评 | [§3、任务附录](https://arxiv.org/abs/2507.19457v2) |
| AutoHarness | 环境动作合法性与游戏反馈；搜索对合法性设置目标 | 环境信号来自任务，优化目标又是作者定义的合法性统计，不适合与最终任务成功率混为一类 | [§3–4](https://arxiv.org/abs/2603.03329v1) |
| DREvo | 任务输出、成败、准确率驱动搜索；涉及领域任务与 TB2 / SWE-V | 更接近 A；正文未足够明确逐项 scorer 来源及官方代码一致性，暂不强行计入纯沿用 | [方法、Experimental Setups](https://arxiv.org/abs/2607.26722v2) |

## 原清单其余 14 项

- 5 项训练 / 共同进化方法：EvoHarness-RL、WHALE、HASE、EvoTrainer、HarnessForge。训练 reward、harness 搜索结果分和最终 benchmark 分应分别审计，不计入上述冻结模型统计。WHALE 的外层继承 Meta-Harness；HASE 可修改局部训练 evaluator；EvoHarness-RL 有成本项，因此整篇贴“官方 scorer”标签会掩盖关键差异。本轮未完成这五项逐 benchmark 评分来源审计。
- 9 项不属于同一统计单位：MUSE、When Does Continual Learning Require Learning、The Interplay of Harness Design and Post-Training、EnvHarness、VeRO、Workspace Optimization、Phantom Guardrails、Towards Direct Evaluation of Harness Optimizers via Priority Ranking、Stop Comparing LLM Agents Without Disclosing the Harness。它们分别是固定框架、比较、环境 / 工作区适应、基础设施或评价研究，不把其评价方式强算成一种批次 harness 候选评分算法。

## 本次结论与剩余工作

- 常见离线进化并没有因为加了 LLM 分析就替换 benchmark 结果标准。
- AutoDesign、COMFYCLAW、RHO、TTHE、RHI 是明确应单列的替代评分 / 代理路线；最终评分来源仍有区别。
- 两种不同问题需要保持分开：是否自建正确性 / 质量准则，是否自行实现沿用标准的评分器。后者不能单凭“有自写代码”计为新准则。
- 本项目还没有据此决定使用哪种评分方案，也没有新成本测量。后续若复现 baseline，需固定其逐 benchmark scorer 源码、模型及配置；不能从本文表格推导成本一定更低。

