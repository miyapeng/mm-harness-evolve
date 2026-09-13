# 归档组件

当前研究池仅保留 SWE-MM、GameDevBench、Vision2Web、OSWorld-Verified、AgenticVBench、BrowseComp-V3。
当前完整状态见 [PROJECT](../docs/PROJECT.md)。本目录不是第二个开发入口。

- [Design2Code](benchmarks/design2code/README.md)：保留历史负结果对应的实现、worker、H0 和配置。
- [Claw-Eval-MM](benchmarks/claw_eval_mm/README.md)：保留官方 H0 接线、数据获取工具及来源；尚无真实模型 rollout。
- `configs/` 保存归档时配置，`scripts/` 保存历史开发脚本作为参考。它们可能引用旧布局；复现历史实验应使用对应 frozen 源码/配置，不能直接将归档脚本视为当前可运行入口。

`benchmarks` package 的搜索路径保留 `benchmarks.design2code.*` 和 `benchmarks.claw_eval_mm.*` import。
当前 registry 将这两项显示为 `archived`；原始 profile JSON 不改写，加载时提供当前视图。
默认 CLI 仅列六个 active；`benchmarks --all` 或 `benchmarks --status archived` 可查看归档。
公共 `adapter_for` 默认拒绝归档任务，维护兼容工具可显式设置 `allow_archived=True`。

Claw 的 data、task-catalog、upstream 配置/许可证及 docker 来源仍在
[原资产目录](../benchmarks/claw_eval_mm/README.md)，不复制或搬动大媒体。
历史 runs、experiments/frozen 和实验配置/结果保持原位置。

ChartMimic、VisualWebArena 的占位 adapter、H0 和开发配置已按用户确认删除。
上游 source lock、来源/许可证及历史记录保留；如未来重新接入，可从清理前 Git 提交
`0b19c6a` 查回占位代码，但不能据此声称完成 integration。
