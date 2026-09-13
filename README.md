# Self-Evolving Multimodal Agent Harness

冻结模型参数，根据 multimodal execution evidence 自动诊断并进化 runtime 中可复用的
Acquire / Transform / Persist / Route / Ground / Verify policies。

**唯一当前入口：[项目总览](docs/PROJECT.md)**，包含定义、架构、schema、B 流程、六个 active benchmark 与两个归档兼容入口、
真实历史结果、兼容说明和待验证问题。真实 SWE 进化仍为 0 轮；已停止的模型/两卡作业没有重启。

```bash
cd /data/miyapeng/mmcode/mm-harness-evolve
PYTHONPATH=src:. .venv/bin/python -m mm_harness.cli benchmarks
PYTHONPATH=src:. .venv/bin/python -m mm_harness.cli benchmarks --all
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
.venv/bin/ruff check src scripts benchmarks archive tests
```

新环境使用 Python 3.12：`python3.12 -m venv .venv`，再 `.venv/bin/python -m pip install -e '.[dev]'`。
测试只用本地 fixture；HTTP 测试需 loopback socket 权限，不需要模型/GPU/benchmark 服务。
上游源码恢复见 `scripts/bootstrap_sources.py --help`，新源码可选 `--source AgenticVBench --source BrowseComp-V3`。
源码、任务数据、运行环境的就绪程度分别记录，不能把源码下载当成真实接通。

开发约定：[AGENTS.md](AGENTS.md)；版本/许可证：[source lock](third_party/lock.json)；
架构重构：[结构化记录](experiments/provenance/control-plane-refactor-20260913.json)；清理说明：[归档目录](archive/README.md)。
历史 runs、frozen data 保持原样，Design2Code/Claw 旧 import 路径保留，bulk media/源码归档不进入 Git。

GitHub 保存当前源码、配置、测试、研究文档、小型结果摘要和来源锁定记录；完整开发提交历史保留在本地。
完整数据集、rollout 媒体、frozen 快照、模型权重、Python 环境、容器镜像和上游完整源码副本留在本地，
不随 Git 上传。因此克隆仓库不等于恢复完整实验环境；请按各 benchmark 的说明恢复依赖与数据。
历史配置中的本机路径和服务地址只是运行记录，使用时需配置自己的环境。
项目整体许可证尚未指定，已复用组件的原始许可证与来源声明继续适用。
