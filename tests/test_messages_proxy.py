import base64
import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mm_harness.runtimes.messages_proxy import image_digests, messages_gateway


@pytest.mark.parametrize("suffix", ["", "/v1"])
@pytest.mark.parametrize("requested_tokens", [None, 64, 16000])
def test_actual_outgoing_image_tool_block_and_fixed_model(tmp_path, suffix, requested_tokens):
    received = []

    class Target(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path == "/v1/messages/count_tokens":
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"input_tokens":10}')
                return
            assert self.path == "/v1/messages"
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"content":[],"usage":{"input_tokens":10,"output_tokens":2}}')

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    thread = threading.Thread(target=target.serve_forever, daemon=True)
    thread.start()
    pixels = b"image-payload-for-transport-test"
    image = {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(pixels).decode(),
        },
    }
    body = {
        "model": "wrong",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "read-image-1", "content": [image]}
                ],
            }
        ],
    }
    role = {
        "model": "fixed-Qwen",
        "temperature": 0.6,
        "top_p": 0.95,
        "max_tokens": 8192,
        "max_requests": 1,
        "enable_thinking": True,
        "request_timeout_seconds": 2,
    }
    if requested_tokens is not None:
        body["max_tokens"] = requested_tokens
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with messages_gateway(
            f"http://127.0.0.1:{target.server_port}{suffix}", role, tmp_path
        ) as gateway:
            count_request = urllib.request.Request(
                gateway + "/v1/messages/count_tokens",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            with opener.open(count_request) as response:
                assert response.status == 200
            request = urllib.request.Request(
                gateway + "/v1/messages?beta=true",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            with opener.open(request) as response:
                assert response.status == 200
            with opener.open(count_request) as response:
                assert response.status == 200
            with pytest.raises(urllib.error.HTTPError) as exc:
                opener.open(request)
            assert exc.value.code == 400
            assert (
                json.loads((tmp_path / "budget-exhausted.json").read_text())["generation_requests"]
                == 1
            )
        assert len(received) == 1 and received[0]["model"] == "fixed-Qwen"
        assert received[0]["messages"] == body["messages"]
        assert received[0]["max_tokens"] == min(requested_tokens or 8192, 8192)
        assert image_digests(received[0]) == [hashlib.sha256(pixels).hexdigest()]
        media_audit = json.loads((tmp_path / "call-0001/media-audit.json").read_text())
        assert media_audit["uses"][0]["passed_to_model"] is True
        assert media_audit["uses"][0]["role"] == "B"
        assert media_audit["artifacts"][0]["content_hash"] == hashlib.sha256(pixels).hexdigest()
        count_audit = json.loads((tmp_path / "call-0000/media-audit.json").read_text())
        assert all(use["passed_to_model"] is False for use in count_audit["uses"])
        recorded = json.loads((tmp_path / "call-0001/request.json").read_text())
        assert recorded == received[0]
        assert (
            json.loads((tmp_path / "call-0000/request-kind.json").read_text())["generation"]
            is False
        )
    finally:
        target.shutdown()
        target.server_close()
        thread.join()
