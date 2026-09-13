"""Count actual provider usage, including fixed CLI helper calls and failed attempts."""

import argparse
import json
from pathlib import Path

from mm_harness.core.artifacts import read_json, write_json


def summarize(directory: Path, output: Path):
    calls = []
    for call in sorted((directory / "requests").glob("call-*")):
        request = read_json(call / "request.json")
        kind = (
            read_json(call / "request-kind.json") if (call / "request-kind.json").exists() else {}
        )
        usage = {}
        final_usage = False
        raw = call / "response.raw"
        response = None
        if raw.exists():
            data = raw.read_text()
            try:
                response = json.loads(data)
                usage = response.get("usage", {})
                final_usage = "output_tokens" in usage
            except json.JSONDecodeError:
                for line in data.splitlines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    if event.get("type") == "message_start":
                        usage.update(event.get("message", {}).get("usage", {}))
                    elif event.get("type") == "message_delta":
                        usage.update(event.get("usage", {}))
                        final_usage = "output_tokens" in event.get("usage", {})
        count_only = kind.get("route") == "/v1/messages/count_tokens" or (
            isinstance(response, dict) and "input_tokens" in response and "usage" not in response
        )
        helper = "process Bash commands" in str(request.get("system"))
        calls.append(
            {
                "call": call.name,
                "kind": "token_count"
                if count_only
                else "bash_helper"
                if helper
                else "other_generation",
                "usage": usage,
                "usage_known": count_only or final_usage,
                "transport": read_json(call / "transport.json")
                if (call / "transport.json").exists()
                else None,
                "images": read_json(call / "images.json")["sha256"],
            }
        )
    totals = {"input_tokens": 0, "output_tokens": 0}
    for call in calls:
        for key in totals:
            totals[key] += call["usage"].get(key, 0)
    unknown = sum(not call["usage_known"] for call in calls)
    report = {
        "directory": str(directory.resolve()),
        "calls": calls,
        "recorded_http_requests": len(calls),
        "token_count_requests": sum(c["kind"] == "token_count" for c in calls),
        "bash_helper_generations": sum(c["kind"] == "bash_helper" for c in calls),
        "unreported_generation_usage": unknown,
        "token_accounting": "lower_bound" if unknown else "complete",
        "usage": totals,
        "unique_images_transmitted": len({sha for c in calls for sha in c["images"]}),
        "usd": None,
    }
    write_json(output, report)
    print(json.dumps({k: v for k, v in report.items() if k != "calls"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.claude, args.output)
