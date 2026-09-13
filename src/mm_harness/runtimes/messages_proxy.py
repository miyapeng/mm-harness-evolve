"""Audit Claude Code's actual Anthropic requests without reimplementing its agent loop.

vLLM's native Messages endpoint preserves image/tool blocks. The gateway fixes
the model and sampling budget and stores bodies, never credentials or headers.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mm_harness.core.artifacts import write_json
from mm_harness.runtimes.media_audit import audit_media_request


def image_digests(value) -> list[str]:
    found = []
    if isinstance(value, dict):
        if value.get("type") == "image" and value.get("source", {}).get("type") == "base64":
            found.append(
                hashlib.sha256(base64.b64decode(value["source"]["data"], validate=True)).hexdigest()
            )
        else:
            for item in value.values():
                found.extend(image_digests(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(image_digests(item))
    return found


@contextmanager
def messages_gateway(base_url: str, role: dict, output: Path):
    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    output.mkdir(parents=True, exist_ok=True)
    counter = 0
    generation_requests = 0
    mutex = threading.Lock()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, body, content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            nonlocal counter, generation_requests
            route = self.path.split("?", 1)[0]
            if route not in {"/v1/messages", "/v1/messages/count_tokens"}:
                self.respond(404, b"{}")
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with mutex:
                index = counter
                counter += 1
                over_budget = (
                    route == "/v1/messages" and generation_requests >= role["max_requests"]
                )
                if route == "/v1/messages" and not over_budget:
                    generation_requests += 1
            if over_budget:
                write_json(
                    output / "budget-exhausted.json",
                    {
                        "max_requests": role["max_requests"],
                        "generation_requests": generation_requests,
                    },
                )
                self.respond(
                    400,
                    b'{"type":"error","error":{"type":"invalid_request_error","message":"Experiment request budget exhausted; this attempt cannot retry"}}',
                )
                return
            body["model"] = role["model"]
            body["chat_template_kwargs"] = {"enable_thinking": role["enable_thinking"]}
            if route == "/v1/messages":
                body.update(
                    max_tokens=min(body.get("max_tokens", role["max_tokens"]), role["max_tokens"]),
                    temperature=role["temperature"],
                    top_p=role["top_p"],
                )
            call = output / f"call-{index:04}"
            write_json(
                call / "request-kind.json", {"route": route, "generation": route == "/v1/messages"}
            )
            write_json(call / "request.json", body)
            write_json(call / "images.json", {"sha256": image_digests(body)})
            start = time.monotonic()
            request = urllib.request.Request(
                base_url.rstrip("/") + route,
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "anthropic-version": "2023-06-01"},
            )
            try:
                with opener.open(request, timeout=role["request_timeout_seconds"]) as response:
                    data = response.read()
                    (call / "response.raw").write_bytes(data)
                    audit_media_request(
                        body,
                        call,
                        role="B",
                        transport_status=response.status,
                        generation=route == "/v1/messages",
                    )
                    write_json(
                        call / "transport.json",
                        {"status": response.status, "seconds": time.monotonic() - start},
                    )
                    self.respond(
                        response.status,
                        data,
                        response.headers.get("Content-Type", "application/json"),
                    )
            except urllib.error.HTTPError as exc:
                data = exc.read()
                (call / "response.raw").write_bytes(data)
                write_json(
                    call / "transport.json",
                    {"status": exc.code, "seconds": time.monotonic() - start},
                )
                audit_media_request(
                    body,
                    call,
                    role="B",
                    transport_status=exc.code,
                    generation=route == "/v1/messages",
                )
                self.respond(exc.code, data)
            except OSError as exc:
                audit_media_request(
                    body,
                    call,
                    role="B",
                    transport_status="unknown",
                    generation=route == "/v1/messages",
                )
                write_json(call / "transport.json", {"status": "service_error", "error": str(exc)})
                self.respond(
                    502,
                    b'{"type":"error","error":{"type":"api_error","message":"Model service unavailable"}}',
                )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
