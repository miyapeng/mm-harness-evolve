# GameDevBench

当前研究角色：`active`；机制/接入状态以 [mechanism-profile.json](mechanism-profile.json) 为准。
本页保留任务安装与历史起点说明，整体状态见 [PROJECT](../../docs/PROJECT.md)。

状态：**框架已接入，环境与官方 H0 尚待专项调试**。
起点：[OpenHandsSolver](https://github.com/waynchi/gamedevbench)，`OpenHandsSolver with official visual feedback`。具体协议与待办见 [profile.json](profile.json)。

`adapter.py` 复用公共命令桥；各阶段可使用不同 Python 环境或容器。
配置 `commands.prepare/execute/score/cleanup`，遵守 [worker 协议](../../docs/PROJECT.md#implementation)。
执行与评分请求分开生成，未配置命令会直接报告缺项，不产生伪分数。
`h0/prompt.txt` 当前是“加载上游默认配置”的描述符，并非已经复现的官方提示。
专项调试时把实际提示/配置和人工兼容修改冻结为 H0，再开始进化。

模型可见输入：task description、starter project、released assets。
评分专用输入：official tests、hidden solution。
按 game/template 分组划分，保留原生指标 official test pass rate。

下一步：

- Godot version and Xvfb/ffmpeg
- official OpenHands solver entrypoint
- interactive playtest and native tests
