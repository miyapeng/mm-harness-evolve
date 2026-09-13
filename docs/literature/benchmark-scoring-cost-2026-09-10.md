# 八个 benchmark 的评分模型与成本

核对：2026-09-10。只回答评分依赖，不改变评分协议；不是八套环境运行验证或费用实测。未冻结的上游以本次访问的公开源码为准，正式接入时仍要固定 commit 与任务配置。配置中的 vlm:null 可能是占位，不能作为不调用模型的证据。

| Benchmark | 评分机制 | 额外推理 / API 成本 |
|---|---|---|
| SWE-MM | 官方测试与补丁验证 | 不依赖额外 LLM judge；容器、浏览器/测试资源仍计费 |
| GameDevBench | Godot 单元测试，检查行为、相机可见性、碰撞等 | 无需 LLM judge；Godot/显示环境成本另计，执行者看视频属于 A 成本 |
| OSWorld-Verified | 任务级执行结果与文件/应用状态检查 | 不要求统一 LLM judge；VM、状态读取/转换等成本另计。S3 grounding 属于执行模型。不要混入有 LLM 指标的 OSWorld-V2 |
| Design2Code | block/text/position/color 及 CLIP | 有本地 CLIP 模型推理，不需要付费 LLM/VLM judge API；浏览器渲染及指标计算另计 |
| Claw-Eval-MM | 任务 grader、rubric、环境证据；固定副本独立配置 judge | 官方多模态配置为 google/gemini-3-flash-preview，模型评分另计；不是每个 task 必然只有一次请求 |
| Vision2Web | 功能验证 agent + VLM 视觉比较 | 两部分都可能产生模型费用，功能验证可为多轮 |
| ChartMimic | low-level Text/Layout/Type/Color F1；high-level GPT-4o Score | low-level 为代码 tracer 和统计；high-level 需 VLM。论文 v2 overall 为两层均分，不能只跑 low-level 却报告完整 overall |
| VisualWebArena | 根据任务组合 string/url/html/image evaluator | 部分规则；fuzzy/不可达理由匹配调用 GPT-4；图片 VQA 调 captioning model（官方支持本地 BLIP-2），SSIM 本身不调用模型。不能笼统标为纯规则，也不能说每任务必有付费调用 |

主要来源：

- [GameDevBench §3.2](https://arxiv.org/abs/2602.11103)：明确 deterministic verification。
- [OSWorld-Verified 官方说明](https://xlang.ai/blog/osworld-verified)、[指标入口](https://github.com/xlang-ai/OSWorld/blob/main/desktop_env/evaluators/metrics/__init__.py)。本项目尚未冻结 Verified 评分任务全集；这里概括其执行式评分，不声称逐函数审计全部版本。新版 [OSWorld-V2 llm_metrics](https://github.com/xlang-ai/OSWorld-V2/blob/main/desktop_env/evaluators/metrics/llm_metrics.py) 是另一套协议。
- [Design2Code 官方指标说明](https://github.com/NoviScl/Design2Code#running-automatic-evaluation)、本地 [score_worker.py](../../benchmarks/design2code/score_worker.py) 明确加载 CLIP。
- 本地 [Claw 多模态配置](../../benchmarks/claw_eval_mm/upstream/config_multimodal.yaml) 与 [Vision2Web 说明](../../benchmarks/vision2web/upstream/README.md)。
- [ChartMimic v2 §2.4](https://arxiv.org/abs/2406.09961v2)：低层代码执行追踪，高层 GPT-4o。
- [VisualWebArena evaluator router](https://github.com/web-arena-x/visualwebarena/blob/main/evaluation_harness/evaluators.py)、[LLM 匹配](https://github.com/web-arena-x/visualwebarena/blob/main/evaluation_harness/helper_functions.py)、[BLIP-2 与 SSIM](https://github.com/web-arena-x/visualwebarena/blob/main/evaluation_harness/image_utils.py)。
- [SWE-MM 项目说明](../../benchmarks/swe_mm/README.md)。

成本解读：无需付费 judge 不等于总成本低；本地模型有算力成本，VM/渲染/测试也有时间与计算成本。只有具体任务集的 scorer 路由与调用计量才能估总账。后续接入按 task/attempt 记录 judge 输入输出 token、图片、调用次数/重试和本地推理耗时；不因本次分类替换 judge 或裁掉原生指标。

