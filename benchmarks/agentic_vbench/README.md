# AgenticVBench

研究角色/完整机制 profile：[mechanism-profile.json](mechanism-profile.json)。整体状态：[PROJECT](../../docs/PROJECT.md)。
当前仅 **source_integrated**：官方源码 `6d7f19a5832b283be6b27bf9cc0d3c1f47e97349` 已原样集成到 `third_party/AgenticVBench-6d7f19a5832b283be6b27bf9cc0d3c1f47e97349`，commit/archive SHA256 见 [SOURCE](upstream/SOURCE.json)。
没有执行模型、容器、rollout 或评分；`adapter.py` 是 command skeleton，execute/score 为 null。

恢复源码（不安装/运行任务）：

```bash
.venv/bin/python scripts/bootstrap_sources.py --source AgenticVBench
```

只读任务发现：

```python
from pathlib import Path
from benchmarks.agentic_vbench.discovery import discover

tasks = discover(Path("third_party/AgenticVBench-6d7f19a5832b283be6b27bf9cc0d3c1f47e97349"))
# 默认论文四个家族 100 题；include_extra_families=True 包含源码中的 24 个 understanding 任务。
```

H0 是官方 Harbor agent recipe，尚需选择/固定实际 A agent revision。`avb` 只是 launcher，不当作完整 A runtime。
只读发现检查 task.toml 和公开 instruction；环境 media mount 要逐任务审核，solution/tests/calibration 不能供 A/B。
源码自带资源不等于环境所有媒体齐备，有的在 build 时生成或下载。Harbor/Docker/媒体工具未安装验证。
repair/assembly/sequencing 采用官方程序判分；repurpose 包括模型 grader，需固定协议和单列费用。
开发池尚未批准，所有发现任务 split=unassigned，不能直接用于 E/V。
