"""Probe both A/B protocols with actual image bytes against the requested service."""

import argparse
import base64
import io
import json
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

from mm_harness.core.artifacts import file_digest, read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.ready.parent / "stopped.json").exists():
        raise RuntimeError("Service lease has ended; ready.json is stale")
    ready = read_json(args.ready)
    if ready["model"] != "Qwen3.8-27B" or ready["tensor_parallel_size"] != 2:
        raise ValueError("Unexpected model/service resource identity")
    args.output.mkdir(parents=True)
    picture = Image.new("RGB", (256, 128), "white")
    draw = ImageDraw.Draw(picture)
    draw.rectangle((8, 8, 112, 120), fill="red")
    draw.rectangle((144, 8, 248, 120), fill="blue")
    picture.save(args.output / "input.png")
    buf = io.BytesIO()
    picture.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode()
    question = "What are the colors of the two rectangles, left to right? Answer with only the two color names."
    requests = {
        "openai": {
            "route": "/v1/chat/completions",
            "body": {
                "model": ready["model"],
                "max_tokens": 128,
                "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": question},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64," + encoded},
                            },
                        ],
                    }
                ],
            },
        },
        "anthropic": {
            "route": "/v1/messages",
            "body": {
                "model": ready["model"],
                "max_tokens": 128,
                "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": question},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": encoded,
                                },
                            },
                        ],
                    }
                ],
            },
        },
    }
    base = ready["endpoint"].removesuffix("/v1")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    results = {}
    for kind, value in requests.items():
        write_json(args.output / f"{kind}.request.json", value["body"])
        start = time.monotonic()
        request = urllib.request.Request(
            base + value["route"],
            data=json.dumps(value["body"]).encode(),
            headers={"Content-Type": "application/json", "anthropic-version": "2023-06-01"},
        )
        with opener.open(request, timeout=180) as response:
            data = json.load(response)
        write_json(args.output / f"{kind}.response.json", data)
        answer = (
            data["choices"][0]["message"]["content"]
            if kind == "openai"
            else " ".join(x.get("text", "") for x in data["content"] if x["type"] == "text")
        )
        answer = answer.lower()
        results[kind] = {
            "answer": answer,
            "correct": "red" in answer
            and "blue" in answer
            and answer.index("red") < answer.index("blue"),
            "seconds": time.monotonic() - start,
            "usage": data.get("usage", {}),
        }
    record = {
        "model": ready["model"],
        "image_sha256": file_digest(args.output / "input.png"),
        "service_ready_sha256": file_digest(args.ready),
        "results": results,
        "scope": "real_model_image_protocol_probe_not_SWE_rollout",
    }
    write_json(args.output / "result.json", record)
    print(json.dumps(record))
    if not all(r["correct"] for r in results.values()):
        raise RuntimeError("Image protocol probe returned an unexpected color answer")


if __name__ == "__main__":
    main()
