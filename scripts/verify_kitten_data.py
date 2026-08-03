"""训练数据质检：Kimi 逐批校验 utterance 是否精确蕴含 target，不合格的重写。

  python scripts/verify_kitten_data.py --in skills/food/kitten/train_raw.jsonl \
      --out skills/food/kitten/train_verified.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

PROMPT = """逐条检查："utterance 是否精确蕴含 target 的全部非空信息，且不含 target 之外的约束、不含模糊表述"。
辣度必须精确：none=不辣, mild=微辣, medium=中辣, hot=特辣/很辣；"微辣中辣都行"这种模糊表述算不合格。
novelty: conservative=保守/吃熟悉的, balanced=可以尝试点新的, bold=想大胆尝鲜。
state: tired=累, low_patience=别让我选/赶紧定, fitness=减脂/健身, late_night=夜宵。
对不合格的条目重写 utterance（自然口语、保持原文风、精确蕴含全部非空字段）。
只输出 JSON 数组：[{{"idx": n, "ok": true}} 或 {{"idx": n, "ok": false, "fixed": "重写后原话"}}]
数据：{pairs}"""


async def verify_batch(client, args, sem, rows: list[dict], out_path: Path, lock) -> tuple[int, int]:
    pairs = [
        {"idx": i, "utterance": r["utterance"],
         "target": {k: v for k, v in r["target"].items() if v not in (None, []) and k != "goal"}}
        for i, r in enumerate(rows)
    ]
    headers = {"Authorization": f"Bearer {os.environ['KIMI_API_KEY']}"}
    async with sem:
        for attempt in range(3):
            try:
                r = await client.post(
                    f"{args.base_url}/v1/chat/completions", headers=headers,
                    json={"model": args.model,
                          "messages": [{"role": "user", "content": PROMPT.format(pairs=json.dumps(pairs, ensure_ascii=False))}],
                          "max_tokens": 8192, "temperature": 0.3},
                    timeout=600)
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
                verdicts = json.loads(text[text.find("["):text.rfind("]") + 1])
                by_idx = {v["idx"]: v for v in verdicts}
                fixed = 0
                async with lock:
                    with out_path.open("a", encoding="utf-8") as f:
                        for i, row in enumerate(rows):
                            v = by_idx.get(i, {"ok": True})
                            if not v.get("ok") and v.get("fixed"):
                                row = {**row, "utterance": v["fixed"], "was_fixed": True}
                                fixed += 1
                            f.write(json.dumps(row, ensure_ascii=False) + "\n")
                return len(rows), fixed
            except Exception as e:
                print(f"batch attempt {attempt}: {type(e).__name__} {e}")
                await asyncio.sleep(5 * (attempt + 1))
        # 三次失败：原样写回，不丢样本
        async with lock:
            with out_path.open("a", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps({**row, "verify_skipped": True}, ensure_ascii=False) + "\n")
        return len(rows), 0


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--batch-size", type=int, default=25)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--base-url", default="http://127.0.0.1:18003")
    p.add_argument("--model", default="kimi-k2.7-code")
    args = p.parse_args()

    rows = [json.loads(l) for l in Path(args.inp).read_text(encoding="utf-8").splitlines()]
    out_path = Path(args.out)
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            done.add(json.loads(line)["id"])
        print(f"resume: {len(done)} done")
    todo = [r for r in rows if r["id"] not in done]
    batches = [todo[i:i + args.batch_size] for i in range(0, len(todo), args.batch_size)]
    print(f"verifying {len(todo)} rows in {len(batches)} batches")
    sem = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[verify_batch(client, args, sem, b, out_path, lock) for b in batches])
    total = sum(n for n, _ in results)
    fixed = sum(f for _, f in results)
    print(f"verified {total}, fixed {fixed} ({fixed / max(total, 1):.1%})")


if __name__ == "__main__":
    asyncio.run(main())
