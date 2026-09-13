# Claw-Eval-MM

当前状态：`archived`，不参与当前开发和默认研究池；JSON 保留归档前分类。
本页保留历史安装与起点说明；下列实验准备说明不是当前可运行承诺，恢复运行须先重新接线。整体状态见 [PROJECT](../../../docs/PROJECT.md)。

状态：**官方 H0 源码、完整发布 fixtures、独立 Python 环境、sandbox 镜像和原生 CLI 已集成；尚未执行模型 rollout**。
本项目名称 `Claw-Eval-MM`、目录名 `claw_eval_mm`，对应
[官方 Claw-Eval](https://github.com/claw-eval/claw-eval) 的 `multimodal` 子集。
已核对 commit `5680b8b11ff2ee5dd2b07b89086a29a5c5c984d7`：300 个 task.yaml 中，
101 个带 `multimodal` 标签。只读任务索引见 [task-catalog.json](../../../benchmarks/claw_eval_mm/task-catalog.json)，未分配研究 split。

数据固定在 ModelScope revision `1a4a1bce4ccd4f97c9eb326ddbbbedaa2331da40`；2,879,916,129 字节原始
fixtures 和 32,411 字节 multimodal parquet 均通过发布 Git-LFS SHA-256。运行树位于 `data/tasks`，
原生 TaskDefinition 校验通过 101 个任务，101/101 的显式 sandbox/fixture/grader 文件齐全。
报告见 [附件审查](../../../experiments/provenance/claw-fixture-audit.json)，来源见 [数据清单](../../../benchmarks/claw_eval_mm/data/SOURCE.json)。
这是静态输入完整性证据，不表示 task service、模型调用和 grader 已经端到端运行。

另发现官方 `config_multimodal.yaml` 未声明 `model.input_modalities`，展开默认值为 `[text]`。
这会影响 M099/M100/M101 的初始图片引用；工具结果的图片注入走另一条路径，不能笼统称为整个 harness 没有视觉。
后续映射目标模型时需如实声明其模态能力并验证实际请求，保留官方原始配置和兼容差异，不能把这项修复算作进化收益。

## 初始 harness

按用户要求，直接采用 benchmark 自带 harness：

- `claw_eval.runner.loop.run_task`：官方执行循环、上下文处理与停止流程。
- `claw_eval.runner.system_prompt.build_system_prompt`：官方动态提示构建，保留 task 工具与配置。
- `config_multimodal.yaml` 加 `Config/MediaConfig` 默认项：媒体加载、工具图片注入、视频帧预算和历史图片策略。
- 官方 sandbox 工具、任务服务、fixtures 与 grader。

`h0/harness.py` 仅把调用交给 upstream API；`h0/prompt.txt` 是选择官方实现的描述符，
不添加自定义系统提示。完整的执行循环和提示源码位于固定的 third_party 副本。
官方配置和 MIT 许可证另原样保存在 [upstream/](../../../benchmarks/claw_eval_mm/upstream)，对应源文件 hash 见 SOURCE.json。
没有把官方 harness 替换成 Claude Code/OpenHands，外层 B 仍由项目的固定进化器运行。

官方 YAML 的默认 executor 为 `anthropic/claude-opus-4.6`、judge 为 `google/gemini-3-flash-preview`。
主实验接线时把 executor 映射到 `roles.executor` 的同一目标模型，独立固定 judge；
保留模型能力、context window、采样参数和媒体预算的展开配置。不能把 judge 随 A/B 一起换掉。

## 来源恢复与启动入口

```bash
# 恢复官方代码并获取发布数据；bulk 数据不提交 Git。
.venv/bin/python scripts/bootstrap_sources.py --source Claw-Eval --no-proxy
/usr/bin/python3.12 -m venv .venv-claw
.venv-claw/bin/python -m pip install -e 'third_party/claw-eval-5680b8b11ff2ee5dd2b07b89086a29a5c5c984d7[mock,sandbox]'
.venv-claw/bin/python -m pip install modelscope==1.40.0
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY .venv-claw/bin/python archive/benchmarks/claw_eval_mm/fetch_data.py --materialize
.venv-claw/bin/python -m benchmarks.claw_eval_mm.check_inputs --tasks-dir benchmarks/claw_eval_mm/data/tasks --output experiments/provenance/claw-fixture-audit.json
PYTHONPATH=src:. .venv/bin/python -m mm_harness.cli benchmarks --name claw_eval_mm
PYTHONPATH=src:. .venv/bin/python -m mm_harness.cli check-config --config archive/configs/benchmarks/claw_eval_mm.json

# 默认只打印官方 H0 命令，不调用模型、不启动 Docker。
PYTHONPATH=src:. .venv/bin/python -m benchmarks.claw_eval_mm.launch_h0 --output runs/claw-eval-mm-h0
```

完成 Claw-Eval 自身独立 Python/Docker/服务环境配置后，可给 launcher 添加 `--execute`。
用 `--executable /your/env/bin/claw-eval` 指定官方 CLI，`--config /your/frozen-model-config.yaml`
指定实际模型配置。launcher 固定 `--tag multimodal --sandbox`，默认 `--trials 3 --parallel 1`。
**仅选择 `config_multimodal.yaml` 不会过滤任务**，必须保留 `--tag multimodal`。

launcher 默认使用本项目 `.venv-claw/bin/claw-eval`。小规模调试可加 `--task-id M001_clock --trials 1`，
只选择一个官方多模态任务；这不构成官方三次重复结果。

这个 launcher 用于官方 H0 的专项调试，不冒充已经完成候选执行/评分的公共 worker。
`adapter.py` 已接入公共命令桥，`commands.execute/score` 尚待在该环境中接线，
遵循 [worker 协议](../../../docs/PROJECT.md#implementation)。官方 CLI 的 `run`/`grade` 可作为接线起点；
完整 grader 还可能需要 mock-service audit 与环境 snapshot，不能只传最终文本。

## 多模态输入和评分边界

允许给 A：task.prompt 的文本/附件、公开 fixtures、sandbox_files、声明的工具及其返回。
task.yaml 同时可能含 reference_solution、judge_rubric、scoring_components、safety_checks 和 grader 文件；
这些仅用于控制器/评分，不把整个 YAML 送入 A 或 B。A 不访问评分阶段采集的私有 snapshot。

原生 trace 的 `media_load`、`tool_dispatch.tool_use_id`、message、trace_end、grading_result 要保留；
图片字节、PDF 页面、视频帧与对应动作关联，原媒体保留。`media_load=loaded` 不单独证明图片到达模型，
仍需审计模型请求。B text/MM 对照只改变进化器证据，A 保留相同官方媒体能力。

完整 fixtures（包括视频）来自 [官方数据集](https://huggingface.co/datasets/claw-eval/Claw-Eval)，
本机通过其 ModelScope 镜像的固定 revision 获取；原始归档、multimodal parquet 与 materialized 运行树均在本 benchmark 内。
源任务、相同附件、模板及语言版本的关联用于后续分组。上游 `multimodal` 是子集，
不是本研究 exploration/validation/test 的划分；如与其他 benchmark 来源重叠，也须检查跨任务泄漏。

保留 completion、safety、robustness、task_score、逐次 passed 与官方跨重复指标。
固定源码中 task_score 为 `round(safety * (0.80*completion + 0.20*robustness), 4)`，默认通过阈值 0.75。
README 的严格三次通过描述与源码 `compute_pass_hat_k=(c/n)^k` 不完全相同；
后续报告需同时保留原生数值和三次全通过指示，明确指标定义，不能将单次 smoke 当 Pass³。
研究选择使用原生连续 task_score；benchmark 的 0.75 与公共策略默认 0.8 是不同阈值，
专项实验应显式设置 `selection.success_threshold=0.75`。
已提供 `archive/configs/evolution/claw_eval_mm.json`；用通用 prepare_experiment.py 冻结该 benchmark 时，
传入 `--policy archive/configs/evolution/claw_eval_mm.json`，正式三次重复另设 `--repetitions 3`。

镜像已上传为 `registry.pjlab.org.cn/ccr-t-llm-frontier/claw-eval:agent-5680b8b-pjlab`，固定 digest
`sha256:a3a42b5c1cc367a162c6760217aece1c5817098da0f4fcae05dc7e5c8e4f3878`。由于官方 DaoCloud
基础镜像不可达，构建使用已固定的 PJLab Vision2Web 基础镜像，并复制原样 Claw sandbox server、安装官方依赖；
健康端点、ffmpeg、pdftoppm 和 Chromium 已在镜像内检查。这是有记录的环境兼容修复，不属于 harness 进化。

当前缺口：把该 image 写入实际模型配置、映射 A/provider 配置、实现 execute/score worker、规范化媒体轨迹、
分组研究 split 与完整原生评分。这些留给后续专项调试，当前没有 Claw-Eval-MM 分数。
