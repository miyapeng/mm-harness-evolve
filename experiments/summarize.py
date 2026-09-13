"""Export compact, auditable experiment records; never call a model or read scorer answers."""

import argparse
import base64
import difflib
import hashlib
import html
import json
import os
from pathlib import Path

from mm_harness.core.artifacts import file_digest, read_json, write_json


def sum_cost(values):
    fields = (
        "input_tokens",
        "output_tokens",
        "model_calls",
        "tool_calls",
        "visual_observations",
        "wall_seconds",
    )
    return {**{key: sum(v.get(key, 0) for v in values) for key in fields}, "dollars": None}


def unified_patch(parent, child):
    lines = (
        line
        for name in parent
        for line in difflib.unified_diff(
            parent[name].splitlines(True),
            child[name].splitlines(True),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
        )
    )
    return "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines
    )


def export_run(run, output):
    frozen = read_json(run / "frozen-selection.json")
    records = {}
    for line in (run / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event["event_type"] != "EvaluationCompleted":
            continue
        for observation in event["payload"]["evaluation"]["observations"]:
            o = observation["metadata"]["outcome"]
            key = o["task_id"], o["harness_id"], o["split"], o["repetition"]
            records[key] = {**o, "reused": observation["metadata"]["reused"]}
    outcomes = list(records.values())
    sessions, costs = [], []
    for proposal_path in sorted((run / "sessions").glob("*/proposal.json")):
        directory = proposal_path.parent
        index = read_json(directory / "model/request-index.json")
        body = read_json(directory / "model/request.json")
        response = read_json(directory / "model/response.json")
        blocks = [
            block
            for message in body["messages"]
            for block in message["content"]
            if block["type"] == "image_url"
        ]
        assert len(blocks) == len(index["images"])
        for block, ref in zip(blocks, index["images"]):
            raw = base64.b64decode(block["image_url"]["url"].split(",", 1)[1])
            assert (
                hashlib.sha256(raw).hexdigest() == ref["sha256"] == file_digest(Path(ref["path"]))
            )
        usage = response["usage"]
        cost = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "model_calls": 1,
            "visual_observations": len(blocks),
            "wall_seconds": response["seconds"],
        }
        costs.append(cost)
        sessions.append(
            {
                "proposal": read_json(proposal_path),
                "path": str(proposal_path),
                "request_index": str(directory / "model/request-index.json"),
                "request_sha256": index["request_sha256"],
                "images": index["images"],
                "cost": cost,
            }
        )
    comparisons = read_json(run / "selection-comparison.json")
    for comparison in comparisons:
        parent = read_json(
            run / "candidates" / comparison["parent"].removeprefix("sha256:") / "candidate.json"
        )
        child = read_json(
            run / "candidates" / comparison["candidate"].removeprefix("sha256:") / "candidate.json"
        )
        patch = unified_patch(parent, child)
        patch_path = output / f"{run.name}.patch"
        patch_path.write_text(patch)
        comparison["patch"] = str(patch_path)
        comparison["patch_sha256"] = file_digest(patch_path)
    return {
        "run": str(run),
        "mode": frozen["experiment"]["evidence_mode"],
        "selected": frozen["selected_candidate_id"],
        "experiment_config_sha256": frozen["config_sha256"],
        "comparisons": comparisons,
        "outcomes": outcomes,
        "proposer_sessions": sessions,
        "new_search_cost": sum_cost([o["cost"] for o in outcomes if not o["reused"]] + costs),
        "attributed_search_cost_including_shared_h0": sum_cost(
            [o["cost"] for o in outcomes] + costs
        ),
        "baseline_reused_from": frozen["experiment"].get("reuse_from", []),
        "cost_note": "wall_seconds in these frozen runs sums A generation and B calls; excludes native scorer overhead; local dollar price unknown",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    conditions = [export_run(p.resolve(), output) for p in args.runs]
    tests = [
        read_json(p / "test-result.json") for p in args.runs if (p / "test-result.json").exists()
    ]
    result = {
        "schema_version": "mm_harness/report/v1",
        "conditions": conditions,
        "test": tests,
        "generalization_claim": False,
        "confidence_intervals": None,
        "notes": [
            "2 exploration / 2 validation / 2 test; one candidate and one repetition per condition",
            "A=B=Qwen3.5-9B; A receives identical reference-image capability",
            "Independent B sessions; identical exploration text, 0 versus 4 image blocks",
            "No positive gain; rejected candidates retained; no retry/fixed-check budget baseline yet",
        ],
    }
    write_json(output / "results.json", result)
    training = []
    for condition in conditions:
        for session, comparison in zip(condition["proposer_sessions"], condition["comparisons"]):
            training.append(
                {
                    "schema_version": "mm_harness/evolver-example/v1",
                    "source_run": condition["run"],
                    "evidence_mode": condition["mode"],
                    "parent_id": comparison["parent"],
                    "candidate_id": comparison["candidate"],
                    "proposal": session["proposal"],
                    "evidence": {
                        "request_index": session["request_index"],
                        "images": session["images"],
                    },
                    "patch": comparison["patch"],
                    "validation_label": comparison,
                    "search_cost": condition["new_search_cost"],
                    "training_use": "future export only; validation_label is never an input to the original B session",
                }
            )
    (output / "evolver-examples.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in training)
    )
    lines = [
        "# Design2Code 开发闭环结果",
        "",
        "A＝B＝Qwen3.5-9B，2 探索／2 验证／2 测试，单次采样。无统计显著性或泛化结论。",
        "",
        "| 条件 | H0 验证均分 | 候选均分 | 差值 | 决策 | B 图片 |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for condition in conditions:
        c = condition["comparisons"][0]
        n = sum(len(s["images"]) for s in condition["proposer_sessions"])
        lines.append(
            f"| {condition['mode']} | {c['parent_score']:.6f} | {c['candidate_score']:.6f} | {c['gain']:+.6f} | {'保留候选' if c['accepted'] else '保留 H0'} | {n} |"
        )
    lines += [
        "",
        "逐任务原生指标、成本、rollout 路径和图片校验见 [results.json](results.json)。",
        "图片对比见 [gallery.html](gallery.html)；训练样本接口见 [evolver-examples.jsonl](evolver-examples.jsonl)。",
        "补丁可在独立 H0 目录用 `git apply --check` 检查；不应用到公共代码。",
        "",
    ]
    if tests:
        lines += [
            f"冻结后保留 H0 的测试均分：{tests[0]['mean_score']:.6f}（{tests[0]['valid']}/{tests[0]['requested']} 条有效记录）。",
            "",
        ]
    (output / "README.md").write_text("\n".join(lines))
    groups = {}
    for condition in conditions:
        parent = condition["comparisons"][0]["parent"]
        for o in condition["outcomes"]:
            groups.setdefault(o["task_id"], {})[
                "H0" if o["harness_id"] == parent else condition["mode"]
            ] = o
    page = [
        '<!doctype html><meta charset="utf-8"><title>Design2Code smoke evidence</title>',
        "<style>body{font:16px system-ui;margin:24px;background:#f5f6fa;color:#172033}select{font:inherit;padding:8px}.grid{display:grid;grid-template-columns:repeat(4,minmax(160px,1fr));gap:12px}figure{margin:0;background:white;padding:12px}img{width:100%;height:65vh;object-fit:contain;object-position:top}small{display:block}h1{font-size:24px}</style>",
        '<h1>Design2Code：原图、H0 与两个被拒绝的候选</h1><p>开发集可视检查；点击图片打开原始尺寸。两种候选均没有验证增益。</p><label>任务 <select id="task">',
    ]
    for task in sorted(groups):
        page.append(f'<option value="t{html.escape(task)}">{html.escape(task)}</option>')
    page.append("</select></label>")
    for task, values in sorted(groups.items()):
        page.append(
            f'<section id="t{html.escape(task)}" class="case"><h2>Task {html.escape(task)}</h2><div class="grid">'
        )
        for name in ("reference", "H0", "multimodal", "text"):
            o = values["H0"] if name == "reference" else values.get(name)
            if o is None:
                continue
            events = [
                json.loads(line)
                for line in (Path(o["rollout"]) / "events.jsonl").read_text().splitlines()
            ]
            role = "reference" if name == "reference" else "generated"
            media = [m for e in events for m in e["media"] if m["role"] == role][-1]
            link = html.escape(
                os.path.relpath(Path(o["rollout"]) / media["path"], output), quote=True
            )
            caption = (
                "reference input"
                if name == "reference"
                else f"{o['split']} / score {o['score']:.4f}"
            )
            page.append(
                f'<figure><figcaption>{name}<small>{caption}</small></figcaption><a href="{link}"><img src="{link}"></a></figure>'
            )
        page.append("</div></section>")
    page.append(
        '<script>const s=document.querySelector("select");function show(){document.querySelectorAll(".case").forEach(e=>e.hidden=e.id!==s.value)}s.onchange=show;show()</script>'
    )
    (output / "gallery.html").write_text("\n".join(page))
    print(output / "README.md")


if __name__ == "__main__":
    main()
