# Design2Code 开发闭环结果

A＝B＝Qwen3.5-9B，2 探索／2 验证／2 测试，单次采样。无统计显著性或泛化结论。

| 条件 | H0 验证均分 | 候选均分 | 差值 | 决策 | B 图片 |
|---|---:|---:|---:|---|---:|
| multimodal | 0.920396 | 0.882692 | -0.037704 | 保留 H0 | 4 |
| text | 0.920396 | 0.838566 | -0.081831 | 保留 H0 | 0 |

逐任务原生指标、成本、rollout 路径和图片校验见 [results.json](results.json)。
图片对比见 [gallery.html](gallery.html)；训练样本接口见 [evolver-examples.jsonl](evolver-examples.jsonl)。
补丁可在独立 H0 目录用 `git apply --check` 检查；不应用到公共代码。

冻结后保留 H0 的测试均分：0.865063（2/2 条有效记录）。
