"""Translate the imported actor-visible data into official SWE-agent file instances."""

import argparse
import json
from pathlib import Path


def convert(rows, mirrors):
    result = []
    for row in rows:
        mirror = mirrors[row["instance_id"]]
        if (
            mirror["status"] not in {"mirrored", "already_present"}
            or mirror["source_digest"] != mirror["target_digest"]
        ):
            raise ValueError(f"Unverified instance image: {row['instance_id']}")
        result.append(
            {
                "instance_id": row["instance_id"],
                "image_name": f"{mirror['target']}@{mirror['target_digest']}",
                "repo_name": "testbed",
                "base_commit": row["base_commit"],
                "problem_statement": row["problem_statement"],
                "extra_fields": {"issue_images": [image["source_url"] for image in row["images"]]},
            }
        )
    return result


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=root / "data/swe_mm/dev")
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in (args.data / "agent_visible/instances.jsonl").read_text().splitlines()
    ]
    mirrors = {
        row["instance_id"]: row
        for row in map(json.loads, (args.data / "private_images.jsonl").read_text().splitlines())
    }
    destination = args.data / "agent_visible/sweagent-instances.jsonl"
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in convert(rows, mirrors))
    if destination.exists() and destination.read_text() != content:
        raise ValueError("Existing SWE-agent inputs differ; use a new data snapshot")
    destination.write_text(content)
    print(json.dumps({"path": str(destination), "instances": len(rows)}))


if __name__ == "__main__":
    main()
