# BrowseComp-V3

研究角色/完整机制 profile：[mechanism-profile.json](mechanism-profile.json)。整体状态：[PROJECT](../../docs/PROJECT.md)。
当前仅 **source_integrated**：官方源码 `8584b33073b4e1e53c98a97608e7e5b73883dfc9` 已原样集成到 `third_party/BrowseComp-V3-8584b33073b4e1e53c98a97608e7e5b73883dfc9`，commit/archive SHA256 见 [SOURCE](upstream/SOURCE.json)。
没有执行模型、容器、rollout 或评分；`adapter.py` 是 command skeleton，execute/score 为 null。

恢复源码（不安装/运行任务）：

```bash
.venv/bin/python scripts/bootstrap_sources.py --source BrowseComp-V3
```

只读任务发现：

```python
from pathlib import Path
from benchmarks.browsecomp_v3.discovery import discover

tasks = discover(Path("benchmarks/browsecomp_v3/data/samples"))
# 需要先另行下载、解密官方样本；本次未下载数据，空目录返回空列表。
```

H0 为官方 OmniSeeker。检查过真实 env、image_processor、image_download_logger 和 search_server 源码；
provider/budget 与 loop 混在 shared env，mutation 仍关闭，不能只给 whole-file permission。
任务发现不 import 官方 loader，防止其 answer/sub_goals/arbitrary metadata 混入 agent 输入。
只导出 question 与明确 images/ 资源；评分端仍应由原官方 evaluator 独立读取答案。
官方布局 data/train.jsonl 不证明独立开发划分。模型/search/MCP 服务、输入隔离与官方评分未实测。
README 声明 CC BY 4.0 并链接 dataset card，但无单独源码 LICENSE；保留这一分发许可未决项。
