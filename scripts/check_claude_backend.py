"""Exercise the real Claude Code CLI + Read/Write tools using a scripted API.

This is a transport/isolation check, not a model rollout or benchmark result.
"""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from mm_harness.core.artifacts import file_digest, read_json, write_json
from mm_harness.runtimes.claude_code import run_claude
from mm_harness.runtimes.messages_proxy import image_digests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--history-image",
        action="store_true",
        help="Read pixels from the new read-only history mount",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if Path(args.name).name != args.name:
        raise ValueError("Use a single-component run name")
    output = root / "runs" / args.name
    output.mkdir()
    workspace = output / "workspace"
    (workspace / "evidence").mkdir(parents=True)
    (workspace / "source").mkdir()
    image = workspace / (
        "history/round-000/visual.png" if args.history_image else "evidence/visual.png"
    )
    image.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), "red").save(image)
    write_json(workspace / "overview.json", {"purpose": "scripted_API_transport_test"})
    received = []

    class Target(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.startswith("/v1/messages/count_tokens"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"input_tokens":100}')
                return
            received.append(body)
            index = len(received)
            if index == 1:
                block = {
                    "type": "tool_use",
                    "id": "read_image",
                    "name": "Read",
                    "input": {"file_path": "/workspace/" + str(image.relative_to(workspace))},
                }
            elif index == 2 and args.history_image:
                block = {
                    "type": "tool_use",
                    "id": "history_write_probe",
                    "name": "Write",
                    "input": {
                        "file_path": "/workspace/history/write-probe.txt",
                        "content": "must fail",
                    },
                }
            elif index == (3 if args.history_image else 2):
                block = {
                    "type": "tool_use",
                    "id": "write_proposal",
                    "name": "Write",
                    "input": {
                        "file_path": "/workspace/proposal.json",
                        "content": '{"status":"no_change","reason":"scripted transport check"}\n',
                    },
                }
            else:
                block = {"type": "text", "text": "Transport check complete."}
            reason = "tool_use" if block["type"] == "tool_use" else "end_turn"
            message = {
                "id": f"msg_probe_{index}",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 1},
            }
            if not body.get("stream"):
                message.update(content=[block], stop_reason=reason)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(message).encode())
                return
            start = (
                {**block, "input": {}}
                if block["type"] == "tool_use"
                else {"type": "text", "text": ""}
            )
            delta = (
                {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
                if block["type"] == "tool_use"
                else {"type": "text_delta", "text": block["text"]}
            )
            events = [
                ("message_start", {"message": message}),
                ("content_block_start", {"index": 0, "content_block": start}),
                ("content_block_delta", {"index": 0, "delta": delta}),
                ("content_block_stop", {"index": 0}),
                (
                    "message_delta",
                    {
                        "delta": {"stop_reason": reason, "stop_sequence": None},
                        "usage": {"output_tokens": 12},
                    },
                ),
                ("message_stop", {}),
            ]
            data = "".join(
                f"event: {name}\ndata: {json.dumps({'type': name, **payload})}\n\n"
                for name, payload in events
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    role = read_json(root / "configs/models/qwen38-pilot.json")["evolver"]
    role.update(
        system_prompt="This is a tool transport integration check. Follow the requested tool calls.",
        wall_timeout_seconds=120,
        max_turns=4,
    )
    try:
        run_claude(
            root, workspace, role, f"http://127.0.0.1:{server.server_port}", output / "claude"
        )
        outgoing_images = [sha for body in received for sha in image_digests(body)]
        result = {
            "kind": "real_claude_code_with_scripted_API_not_model_inference",
            "requests": len(received),
            "image_sha256": file_digest(image),
            "image_sent": file_digest(image) in outgoing_images,
            "image_location": str(image.relative_to(workspace)),
            "proposal_written": (workspace / "proposal.json").is_file(),
            "all_model_ids": sorted({body["model"] for body in received}),
        }
        if args.history_image:
            result["history_write_blocked"] = not (
                workspace / "history/write-probe.txt"
            ).exists() and any(
                block.get("tool_use_id") == "history_write_probe" and block.get("is_error")
                for body in received
                for msg in body.get("messages", [])
                for block in msg.get("content", [])
                if isinstance(block, dict)
            )
            if not result["history_write_blocked"]:
                raise RuntimeError("History write was not confirmed blocked")
        write_json(output / "result.json", result)
        if not result["image_sent"] or not result["proposal_written"]:
            raise RuntimeError(f"Tool/image check failed: {result}")
        print(json.dumps(result))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
