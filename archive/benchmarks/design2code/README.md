# Design2Code：已完成开发规模真实闭环

当前状态：`archived`，不参与当前开发和默认研究池；JSON 保留归档前分类。
本页保留历史安装与起点说明；下列实验准备说明不是当前可运行承诺，恢复运行须先重新接线。整体状态见 [PROJECT](../../../docs/PROJECT.md)。

起点为官方 `gpt4v.py:direct_prompting` 提示，模型改为固定 Qwen3.5-9B。
只向模型发送 reference screenshot，不读取 reference HTML 或从其提取文本。
原生 block/text/position/color/CLIP 评分通过已审计的旧项目兼容层执行。
代码 MIT、数据 ODC-By；上游和本地文件 hash 见 `third_party/lock.json` 与 provenance。

已有 2 探索／2 验证／2 测试的真实开发记录，text/visual B 各一个候选，均拒绝。
历史配置与 frozen 源码用于复查；结果见 [开发报告](../../../experiments/results/design2code-smoke/README.md)。
该规模不支持泛化或多模态优势结论。

API：`api.prompt`、`api.reference_image`、`api.generate(prompt, images)`、`api.render(html)`。
render 返回本次图片引用；修订时应将**当前生成代码**和本次 render 与 reference 一起发送，
不能借用别次输出。固定 `max_model_calls=2`；H0 实际只调用一次。
Direct、self-revision、额外重试作为独立固定 H0/对照配置，不能混用参考 HTML 可见性。

人工 H0 适配：统一模型 API、移除代码围栏、固定 Chromium viewport/placeholder；
旧 evaluator 已有缩进、pkg_resources 和 Python 路径兼容；本项目补显式 CLIP 缓存位置。
未改变原生指标计算公式。兼容清单属于初始工程工作，不计入进化收益。

最新主分支修正了 code_sha256 口径、图像输入 freeze 校验和总耗时；历史实验仍使用记录的冻结源码。
评分器 reference.html 在生成结束后才进入 scorer-private；当前 worker 仅进程隔离。
开启任意 Python 逻辑修改前需要接入限定挂载的容器，参见 [worker 协议](../../../docs/PROJECT.md#implementation)。
