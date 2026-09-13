from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.request
from pathlib import Path

from mm_harness.core.artifacts import digest, file_digest, read_json, write_json


class ModelError(RuntimeError):
    pass


def image_block(path: Path) -> dict:
    mime = mimetypes.guess_type(path)[0]
    if mime not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        raise ValueError(f"Unsupported model image: {path}")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"},
    }


class ChatModel:
    """Separate session per call; persist the exact body sent, never auth headers."""

    def __init__(self, provider: dict, role: dict, transport=None):
        self.provider, self.role = provider, role
        self.transport = transport or self._send

    def _send(self, body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        key = os.environ.get(self.provider.get("api_key_env", ""), "")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request = urllib.request.Request(
            self.provider["base_url"].rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers=headers,
        )
        opener = (
            urllib.request.build_opener(urllib.request.ProxyHandler({}))
            if self.provider.get("no_proxy", False)
            else urllib.request.build_opener()
        )
        with opener.open(request, timeout=self.role["timeout_seconds"]) as response:
            return json.load(response)

    def call(self, prompt: str, images: list[dict], directory: Path, *, seed: int) -> dict:
        directory.mkdir(parents=True, exist_ok=True)
        content = [{"type": "text", "text": prompt}]
        image_refs = []
        for image in images:
            path = Path(image["path"])
            actual = file_digest(path)
            if image.get("sha256", actual) != actual:
                raise ValueError("Image changed before request")
            label = {k: v for k, v in image.items() if k != "path"}
            content.append({"type": "text", "text": json.dumps(label)})
            content.append(image_block(path))
            image_refs.append({**image, "sha256": actual})
        body = {
            "model": self.role["model"],
            "messages": [{"role": "user", "content": content}],
            "temperature": self.role["temperature"],
            "max_tokens": self.role["max_tokens"],
            "seed": seed,
            **self.role.get("extra_body", {}),
        }
        identity = digest({"provider": self.provider, "role": self.role, "body": body})
        if (directory / "response.json").exists():
            if read_json(directory / "request-index.json")["identity"] != identity:
                raise ValueError("Completed model call has different inputs")
            return read_json(directory / "response.json")
        if (directory / "started.json").exists():
            raise ModelError("Interrupted request has unknown cost; use a fresh attempt/sample")
        write_json(directory / "request.json", body)
        write_json(
            directory / "request-index.json",
            {
                "identity": identity,
                "images": image_refs,
                "request_sha256": file_digest(directory / "request.json"),
                "model": self.role["model"],
            },
        )
        write_json(directory / "started.json", {"time": time.time()})
        started = time.monotonic()
        try:
            raw = self.transport(body)
            write_json(directory / "raw-response.json", raw)
            if raw.get("model") and raw["model"] != self.role["model"]:
                raise ModelError(f"Server returned unexpected model {raw['model']}")
            choice = raw["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ModelError("Model exhausted output token budget")
            message = choice["message"]
            if not isinstance(message.get("content"), str) or not message["content"].strip():
                raise ModelError("Model returned no text content")
            usage = raw.get("usage", {})
            result = {
                "text": message["content"],
                "usage": usage,
                "seconds": time.monotonic() - started,
                "images": len(images),
                "model": raw.get("model"),
                "request_identity": identity,
            }
            write_json(directory / "response.json", result)
            return result
        except Exception as e:
            write_json(
                directory / "error.json",
                {
                    "type": type(e).__name__,
                    "message": str(e),
                    "seconds": time.monotonic() - started,
                    "cost_unknown": True,
                },
            )
            raise ModelError(str(e)) from e


def assert_same_model(config: dict):
    a, b = config["roles"]["executor"], config["roles"]["evolver"]
    if config.get("same_model", True):
        if any(a[k] != b[k] for k in ("provider", "model", "revision")):
            raise ValueError("A=B requires identical provider, model and revision")
