# SWE-bench Multimodal

当前研究角色：`active`；机制/接入状态以 [mechanism-profile.json](mechanism-profile.json) 为准。
本页保留任务安装与历史起点说明，整体状态见 [PROJECT](../../docs/PROJECT.md)。

当前状态统一见[项目总览](../../docs/PROJECT.md#status)。2026-09-13 调试已停止，两卡已释放；
真实官方 SWE-agent rollout 与独立实例评分已有记录，尚未完成真实候选重跑或进化轮。
起点：[SWE-agent](https://github.com/SWE-agent/SWE-agent)，固定 `3ea751c087f32b16e039a2233dd6eefecef325d5` 的
`config/default_mm_with_images.yaml`。完整代码在仓库内 `third_party/SWE-agent-<commit>`；
[官方配置副本](upstream/config/default_mm_with_images.yaml) 与 [SOURCE.json](upstream/SOURCE.json) 可检查。

H0 是官方完整 agent：原始模板、函数调用工具、图像历史处理、image_tools、web_browser、review_on_submit_m、执行循环。
不添加我们的重观察/自修订策略。该配置中的 Python 仓库措辞也原样保留，未擅自改成 JavaScript 提示。
这是所选官方版本的原始配置，未声称复现 2024 年论文对应的历史版本。

旧项目实际用 mini-swe-agent，见 [旧运行配置](upstream/legacy-runtime.json)。它不作为此 H0。
复用的是本仓库内复制的数据、163 个允许的 issue 图片引用、102 个实例的镜像 digest 映射与固定 SWE-bench 评分源码。
原生 SWE-agent 已成功加载 102 个多模态实例。当前 Qwen3.8-27B 请求审计已确认实际图片字节传输，
processing__p5.js-6069 的真实补丁已评分为 resolved=false；完整跨轮结果见[运行记录](../../docs/PROJECT.md#experiments)。

```bash
.venv/bin/python scripts/bootstrap_sources.py --source SWE-agent --source SWE-bench --no-proxy
/usr/bin/python3.12 -m venv .venv-swe-agent
.venv-swe-agent/bin/python -m pip install -e third_party/SWE-agent-3ea751c087f32b16e039a2233dd6eefecef325d5
.venv/bin/python -m benchmarks.swe_mm.prepare_inputs
# 默认仅打印命令；Docker/镜像/模型配置就绪后加 --execute。
.venv/bin/python -m benchmarks.swe_mm.launch_h0 \
  --instance-id Automattic__wp-calypso-21409 \
  --model-config configs/models/swe-agent-local-qwen.yaml --output runs/swe-mm-official-h0-001
```

`prepare_inputs` 只从 agent_visible 数据构建官方 file instances，映射 digest 匹配的实例镜像，不含 gold/test patch。
离线实例清单保持官方 URL。新 ClusterX worker 校验本地原图 hash 后通过 task-local HTTP 提供图片；
GIF 固定提取首/中/末三帧以适配官方读取器，保留原 GIF 与帧索引。这是固定 H0 兼容层。
`MM_HARNESS_API_KEY` 从环境读取；本地服务可设置占位值。local-qwen 映射只改 provider/model/采样，不覆盖 H0 提示和工具。
正式 rollout 前还须确定自托管模型的有效预算：官方默认美元限额不能替代未知单价模型的调用限额。

当前宿主无 Docker；新 `cluster_runner.py` 使用 ClusterX 运行 digest-pinned 实例镜像，实际拉取与运行已验证。
A 和评分器使用两个独立干净实例。`actor_worker.py` 加载所选源码；`score_worker.py` 使用本仓库固定官方评分代码。
上面的通用 launcher 仍是 Docker 路径；当前集群请使用下面的 worker 路径。

`adapter.py` 复用公共命令桥；各阶段可使用不同 Python 环境或容器。
配置 `commands.prepare/execute/score/cleanup`，遵守 [worker 协议](../../docs/PROJECT.md#implementation)。
执行与评分请求分开生成，未配置命令会直接报告缺项，不产生伪分数。
`h0/prompt.txt` 当前是“加载上游默认配置”的描述符，并非已经复现的官方提示。
专项调试时把实际提示/配置和人工兼容修改冻结为 H0，再开始进化。

模型可见输入：issue text、released issue images、repository at base commit。
评分专用输入：gold patch、test patch、hidden tests。
按 repository 分组划分，保留原生指标 resolved。

当前集群运行入口：

```bash
bash scripts/setup_swe_worker.sh
PYTHONPATH=src:. .venv/bin/python scripts/prepare_swe_pilot.py --name UNIQUE_NAME
PYTHONPATH=src:. .venv/bin/python scripts/run_harness_search.py \
  --experiment runs/UNIQUE_NAME --runner benchmarks.swe_mm.cluster_runner:run_and_score \
  --base-url http://SERVICE_IP:18138/v1 --rounds 2 --wait-pending
```

A/B 同一模型独立会话。默认 E4/V4、1 候选、最多两条 CPU 流水共享现有两卡服务。
各次运行的环境修复、时限与成本缺口须保留，不能把它们记作 harness 自动进化收益。
