# Vision2Web：官方 H0 已集成，容器 rollout 待验证

当前研究角色：`active`；机制/接入状态以 [mechanism-profile.json](mechanism-profile.json) 为准。
本页保留任务安装与历史起点说明，整体状态见 [PROJECT](../../docs/PROJECT.md)。

H0 使用官方 `InferenceEngine + OpenHandsAdapter + get_prompt_for_task`，固定 released commit
`577f9397b3db8fc6d828adde254a830caa65d515`。完整源码已下载到本仓库 `third_party/Vision2Web-<commit>`，
三个任务层级的 [官方 prompt](upstream/vision2web/inference/prompts.py)、
[OpenHands adapter](upstream/vision2web/inference/adapters/openhands.py) 与 [来源 hash](upstream/SOURCE.json) 可检查。
H0 保留官方工具与 CLI、按任务类型选择的完整提示、重试/停止逻辑；不加 browser_enabled、guided_vsv 或 self_verify 增强。

原生入口为 `launch_h0.py`，直接调用官方 inference。它不使用此前的本机诊断 monkey patch。
复用旧官方镜像 digest（CLI 1.16.0、SDK/tools 1.21.0），保持镜像内 OpenHands；
外层控制器安装在本仓库 `.venv-vision2web`。镜像记录见 `data/vision2web/image.json` 与 [历史环境](upstream/legacy-runtime.json)。
193 个任务数据已独立复制到 `data/vision2web/extracted`，官方 DatasetManager 已识别 100/66/27 个任务；无旧目录软链接。

```bash
.venv/bin/python scripts/bootstrap_sources.py --source Vision2Web --no-proxy
/usr/bin/python3.12 -m venv .venv-vision2web
.venv-vision2web/bin/python -m pip install -e third_party/Vision2Web-577f9397b3db8fc6d828adde254a830caa65d515
# 使用支持视觉能力元数据的模型路由；默认只打印命令。
.venv/bin/python -m benchmarks.vision2web.launch_h0 \
  --task-type webpage --project cloudera --model litellm_proxy/Qwen3.5-9B \
  --base-url http://127.0.0.1:4000/v1 --output runs/vision2web-official-h0-001
```

示例的 4000 端口是待配置的模型网关，不表示已启动；真实环境需让容器可以访问它并如实提供视觉能力元数据。
Docker/镜像/网关就绪后加 `--execute`，凭据来自 `MM_HARNESS_API_KEY`。
当前宿主无 Docker；未验证容器内实际读图、生成或官方评分，不能报告有效 H0。
此原生 launcher 与公共进化器 worker 接线分别计状态；`commands.execute/score` 仍未配置。

## 历史诊断，不能作为官方 H0

旧的 `h0/prompt.txt` 只是官方 webpage prompt 副本，`adapter.py/worker.py` 是此前本机诊断路径。
它加入过 workspace 翻译、模型元数据、固定 extensions 与请求预算，不是现在的官方原生启动路径。

2026-09-09 的 `runs/vision2web-cloudera-h0-v1` 已判无效：20 次模型请求没有图片，
且 actor 通过终端读到了相邻 resolved.json。原始记录保留，不能进入进化或结果比较。
`scripts/run_vision2web_h0.py` 是诊断入口，当前不建议继续跑无隔离基线。

当前没有为此任务保留排队作业。早期诊断的新 proc 挂载失败已记录；后来 SWE 使用了兼容方案，
但不能据此声称 Vision2Web 环境已验证。整体进度见[项目总览](../../docs/PROJECT.md#benchmarks)。
下一步在固定容器中只挂载 prototypes/resources/任务提示及可写产物目录，
先验证 file_editor 图片确实进入请求，再生成并运行官方 evaluator。
评分端 workflow.json 与 agent 输入分开；released evaluator 与 paper `3111cc3` 分开报告。

不要把“未评分”作为模型任务失败，也不要把目录分开当成文件系统隔离。
