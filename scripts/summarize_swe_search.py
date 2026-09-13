"""Summarize measured development rounds; never imply frozen-test generalization."""

import argparse
import json
import os
from pathlib import Path

from mm_harness.core.artifacts import read_json, write_json


def summarize(experiment: Path, output: Path):
    experiment = experiment.resolve()
    output = output.resolve()
    frozen = read_json(experiment / "experiment.json")
    state = read_json(experiment / "search/search.json")
    output.mkdir(parents=True, exist_ok=True)
    rounds, tasks, pending = [], [], []
    actor_cost, evolver_cost = {}, {}
    for round_file in sorted((experiment / "search/rounds").glob("*/round.json")):
        current = read_json(round_file)
        index = int(round_file.parent.name.split("-")[-1])
        proposal = current.get("proposal", {})
        row = {
            "round_index": index,
            "status": current["status"],
            "parent": current["spec"]["parent"],
            "candidate": proposal.get("harness_id"),
            "exploration": current.get("batch_comparison"),
            "validation": current.get("dev_comparison"),
            "proposal": str(round_file.parent / "proposal/result.json") if proposal else None,
            "diagnosis": proposal.get("diagnosis"),
            "patch": proposal.get("patch"),
        }
        rounds.append(row)
        for request_file in sorted(round_file.parent.glob("attempts/*/actor-request.json")):
            attempt = request_file.parent
            if (attempt / "result.json").exists():
                continue
            identity = read_json(request_file)["identity"]
            actor_done = (attempt / "rollout/actor-result.json").exists()
            job_file = attempt / ("score-job.json" if actor_done else "actor-job.json")
            calls = list((attempt / "audit-private/requests").glob("call-*/request.json"))
            pending.append(
                {
                    **identity,
                    "stage": "scoring_or_collection" if actor_done else "actor",
                    "job": read_json(job_file)["name"] if job_file.exists() else None,
                    "observed_model_requests": len(calls),
                    "latest_request_mtime": max((p.stat().st_mtime for p in calls), default=None),
                    "attempt": str(attempt),
                }
            )
        for result in current["attempts"].values():
            tasks.append({**result, "round_index": index})
            for key, value in result.get("cost", {}).items():
                if isinstance(value, (int, float)):
                    actor_cost[key] = actor_cost.get(key, 0) + value
        cost = proposal.get("cost") or {}
        for key, value in cost.get("usage", {}).items():
            if isinstance(value, (int, float)):
                evolver_cost[key] = evolver_cost.get(key, 0) + value
        evolver_cost["seconds"] = evolver_cost.get("seconds", 0) + cost.get("seconds", 0)
    report = {
        "experiment": frozen["name"],
        "code_commit": frozen["code_commit"],
        "model": frozen["roles"]["actor"]["model"],
        "h0": frozen["h0"],
        "status": state["status"],
        "completed_rounds": len(state["rounds"]),
        "selected": state["selected"],
        "rounds": rounds,
        "tasks": tasks,
        "pending_attempts": pending,
        "actor_search_cost": actor_cost,
        "evolver_search_cost": evolver_cost,
        "limitations": [
            "development E/V only; no final test evaluated",
            "partial/in-flight attempts excluded from totals",
            "unreported request usage makes token totals lower bounds",
            "deployment cost and transfer gains have not been evaluated",
        ],
    }
    if (experiment / "stopped.json").exists():
        report["stop_record"] = read_json(experiment / "stopped.json")
        report["controller_status"] = report["status"]
        report["status"] = report["stop_record"]["status"]
    reliability_file = experiment / "analysis/reliability.json"
    if reliability_file.exists():
        report["reliability"] = read_json(reliability_file)
    write_json(output / "summary.json", report)

    def link(path):
        return os.path.relpath(path, output)

    def gain(value):
        return "—" if not value else str(value.get("gain", "inconclusive"))

    lines = [
        f"# {frozen['name']}",
        "",
        f"A=B={report['model']}；已完成 {report['completed_rounds']} 轮；状态 `{report['status']}`。",
        "仅报告开发 E/V；没有最终测试或泛化结论。",
        "工程验收限定：存在已记录的评测可靠性/答案污染问题，不能用于论文收益。"
        if report.get("reliability", {}).get("scope") == "engineering_only"
        else "",
        "",
        f"冻结代码：`{report['code_commit']}`；H0：`{report['h0']}`。",
        f"当前选定：`{report['selected']}`。",
        "",
        "| 轮次（从 0 开始） | 决策/状态 | E 净增益 | V 净增益 | 补丁 |",
        "|---|---|---:|---:|---|",
    ]
    for row in rounds:
        patch = f"[patch]({link(row['patch'])})" if row["patch"] else "—"
        lines.append(
            f"| {row['round_index']} | {row['status']} | {gain(row['exploration'])} | {gain(row['validation'])} | {patch} |"
        )
    lines += [
        "",
        "| 轮次 | 集合 | 任务 | Harness 前缀 | 状态 | 分数 | 原始记录 |",
        "|---|---|---|---|---|---:|---|",
    ]
    for row in tasks:
        result = Path(row["rollout"]).parent / "result.json"
        lines.append(
            f"| {row['round_index']} | {row['split']} | {row['task_id']} | {row['harness_id'][:12]} | {row['status']} | {row['score']} | [result]({link(result)}) |"
        )
    lines += [
        "",
        "| 运行中轮次 | 任务 | 阶段 | 作业 | 已记录模型请求 |",
        "|---|---|---|---|---:|",
    ]
    for row in pending:
        lines.append(
            f"| {row['round_index']} | {row['task_id']} | {row['stage']} | {row['job']} | {row['observed_model_requests']} |"
        )
    lines += [
        "",
        "成本只累加控制器已接收的完成结果；排队、被中止调试与运行中的请求另行保留。",
        f"A 搜索 input/output tokens：{actor_cost.get('input_tokens', 0)} / {actor_cost.get('output_tokens', 0)}。",
        f"B 搜索 input/output tokens：{evolver_cost.get('input_tokens', 0)} / {evolver_cost.get('output_tokens', 0)}。",
        "本地推理美元价格未知；不采用 Claude CLI 自动估算的美元费用。",
        f"[结构化汇总](summary.json) · [自动生成谱系]({link(experiment / 'search/history.md')})",
        "",
    ]
    (output / "README.md").write_text("\n".join(lines))
    print(
        json.dumps({"report": str(output / "README.md"), "completed_rounds": len(state["rounds"])})
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.experiment, args.output)
