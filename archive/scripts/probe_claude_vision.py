"""Verify the existing Qwen endpoint through Claude SDK using actual initial image content."""

import asyncio
import base64
import dataclasses
import json
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/claude-vision-probe"


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    image = ROOT.parent / "MultimodalCode/data/design2code/images/image_1.png"
    content = [
        {
            "type": "text",
            "text": "Look at the attached screenshot. What site title and dominant colors do you see? Answer in one sentence. Do not use tools.",
        },
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(image.read_bytes()).decode(),
            },
        },
    ]
    (OUT / "input.json").write_text(json.dumps(content))

    async def prompts():
        yield {"type": "user", "message": {"role": "user", "content": content}}

    options = ClaudeAgentOptions(
        model="Qwen3.5-9B",
        cwd=str(OUT),
        allowed_tools=[],
        max_turns=1,
        setting_sources=[],
        env={
            "ANTHROPIC_BASE_URL": "http://10.119.255.142:18002",
            "ANTHROPIC_API_KEY": "EMPTY",
            "NO_PROXY": "10.119.255.142,127.0.0.1,localhost",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
        },
    )
    with (OUT / "messages.jsonl").open("w") as f:
        async for message in query(prompt=prompts(), options=options):
            obj = dataclasses.asdict(message) if dataclasses.is_dataclass(message) else str(message)
            f.write(json.dumps(obj, default=str) + "\n")
            f.flush()
            if type(message).__name__ == "ResultMessage":
                print(json.dumps(obj, default=str), flush=True)


asyncio.run(asyncio.wait_for(main(), timeout=120))
