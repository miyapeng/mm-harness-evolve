"""Loopback OpenAI gateway: fixed model budgets, vision metadata and request evidence.

Transport compatibility for OpenHands' litellm_proxy model-info lookup. It does not
convert tools or images. Every forwarded request/response is retained without headers.
"""

from __future__ import annotations

import argparse
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mm_harness.core.artifacts import read_json, write_json
from mm_harness.runtimes.media_audit import audit_media_request


def serve(config, directory, ready_path):
    directory.mkdir(parents=True, exist_ok=True)
    mutex = threading.Lock()
    counter = 0
    role = config["role"]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, code, body, content_type="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/v1/model/info"):
                result = {
                    "data": [
                        {
                            "model_name": role["model"],
                            "model_info": {
                                "supports_vision": True,
                                "supports_function_calling": True,
                                "max_input_tokens": 100000,
                                "max_output_tokens": role["max_tokens"],
                                "max_tokens": 100000,
                                "mode": "chat",
                            },
                        }
                    ]
                }
            elif self.path in ("/models", "/v1/models"):
                result = {"object": "list", "data": [{"id": role["model"], "object": "model"}]}
            else:
                self.respond(404, b"{}")
                return
            self.respond(200, json.dumps(result).encode())

        def do_POST(self):
            nonlocal counter
            if self.path not in ("/chat/completions", "/v1/chat/completions"):
                self.respond(404, b"{}")
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with mutex:
                index = counter
                counter += 1
            if index >= config["max_calls"]:
                write_json(directory / "budget-exhausted.json", {"max_calls": config["max_calls"]})
                self.respond(
                    429, b'{"error":{"message":"fixed experiment model-call budget exhausted"}}'
                )
                return
            # These settings are part of H0 compatibility, held fixed across candidates.
            body.update(
                {
                    "model": role["model"],
                    "max_tokens": role["max_tokens"],
                    "temperature": role["temperature"],
                    **role.get("extra_body", {}),
                }
            )
            call_dir = directory / f"call-{index:04}"
            write_json(call_dir / "request.json", body)
            request = urllib.request.Request(
                config["base_url"].rstrip("/") + "/chat/completions",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                    request, timeout=role["timeout_seconds"]
                ) as response:
                    data = response.read()
                    (call_dir / "response.raw").write_bytes(data)
                    audit_media_request(body, call_dir, role="A", transport_status=response.status)
                    self.respond(
                        response.status,
                        data,
                        response.headers.get("Content-Type", "application/json"),
                    )
            except (OSError, urllib.error.URLError) as exc:
                write_json(call_dir / "error.json", {"error": str(exc)})
                audit_media_request(body, call_dir, role="A", transport_status="unknown")
                self.respond(502, json.dumps({"error": {"message": str(exc)}}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    write_json(ready_path, {"base_url": f"http://127.0.0.1:{server.server_port}"})
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    serve(read_json(args.config), args.output, args.output / "ready.json")


if __name__ == "__main__":
    main()
