# OSWorld-Verified

当前研究角色：`active`；机制/接入状态以 [mechanism-profile.json](mechanism-profile.json) 为准。
本页保留任务安装与历史起点说明，整体状态见 [PROJECT](../../docs/PROJECT.md)。

状态：**框架已接入，环境与官方 H0 尚待专项调试**。
起点：[Agent-S S3](https://github.com/simular-ai/Agent-S)，`S3 single trajectory; no bBoN`。具体协议与待办见 [profile.json](profile.json)。

`adapter.py` 复用公共命令桥；各阶段可使用不同 Python 环境或容器。
配置 `commands.prepare/execute/score/cleanup`，遵守 [worker 协议](../../docs/PROJECT.md#implementation)。
执行与评分请求分开生成，未配置命令会直接报告缺项，不产生伪分数。
`h0/prompt.txt` 当前是“加载上游默认配置”的描述符，并非已经复现的官方提示。
专项调试时把实际提示/配置和人工兼容修改冻结为 H0，再开始进化。

模型可见输入：instruction、desktop screenshot、released files。
评分专用输入：evaluator config、reference state。
按 application/workflow 分组划分，保留原生指标 official task success。

下一步：

- VM snapshot and reset service
- S3 planner + separately pinned grounding model
- official verified task revision
