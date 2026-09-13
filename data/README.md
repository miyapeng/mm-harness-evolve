# 本仓库的数据副本

优先 benchmark 的运行数据放在这里，不软链接到旧 MultimodalCode。
大文件不提交 Git；导入命令与逐文件 hash 清单用于复核，源数据许可证保持原样。

```bash
.venv/bin/python scripts/import_priority_data.py --legacy /data/miyapeng/mmcode/MultimodalCode --benchmark swe_mm
.venv/bin/python scripts/import_priority_data.py --legacy /data/miyapeng/mmcode/MultimodalCode --benchmark vision2web
```

旧目录仅用于这一步复制，后续入口只使用本仓库数据。不同内容不会覆盖已有副本。
SWE-MM 的 `evaluator_private`、私有图片索引只供评分/数据准备；不得整体挂载给执行 agent。
Vision2Web 官方 inference 仅复制 prototypes/resources 和对应 prompt/prd，不复制 workflow 给 agent。
Claw-Eval 自带任务与部分 fixtures 在固定 `third_party` 副本中；完整 HF fixtures 尚需另行恢复。
