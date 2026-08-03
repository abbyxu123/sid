"""mmproj 视觉单测：菜单图 → 结构化菜品/价格。决定菜单拍照是否进 Demo 脚本。

  python3 scripts/test_menu_vision.py --image skills/food/demo_data/menu_sample.png \
      --base-url http://127.0.0.1:8080
"""
from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path

import httpx

PROMPT = """这是一张餐厅菜单照片。提取全部菜品与价格，只输出 JSON：
{"restaurant": "店名", "items": [{"name": "菜名", "price": 数字}], "delivery_fee": 数字或null}"""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--image", required=True)
    p.add_argument("--base-url", default="http://127.0.0.1:8080")
    p.add_argument("--model", default="step-local")
    p.add_argument("--max-tokens", type=int, default=1500)
    args = p.parse_args()

    b64 = base64.b64encode(Path(args.image).read_bytes()).decode()
    t0 = time.perf_counter()
    r = httpx.post(
        f"{args.base_url}/v1/chat/completions",
        json={
            "model": args.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
            "max_tokens": args.max_tokens,
            "temperature": 0.6,
        },
        timeout=600,
    )
    dt = time.perf_counter() - t0
    r.raise_for_status()
    data = r.json()
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    print(f"latency: {dt:.1f}s | usage: {data.get('usage')}")
    print(f"reasoning_chars: {len(msg.get('reasoning_content') or '')}")
    print("--- content ---")
    print(content)
    try:
        start, end = content.find("{"), content.rfind("}") + 1
        parsed = json.loads(content[start:end])
        print(f"--- JSON OK: {len(parsed.get('items', []))} items ---")
    except Exception as e:
        print(f"--- JSON FAIL: {e} ---")


if __name__ == "__main__":
    main()
