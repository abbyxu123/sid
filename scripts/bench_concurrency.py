"""Step 3.7 并发/延迟基准：验证议事会 <25s 是否可行，量化 reasoning 开销。

在能访问 llama-server 的机器上运行（local AI host 本机或经 Tailscale）：
  python scripts/bench_concurrency.py --base-url http://127.0.0.1:8080 \
      --concurrency 1 4 --max-tokens 1200 --runs 3

测三件事：
  1) 单流 vs 4 并发的每请求延迟与聚合吞吐（-np 4 continuous batching 实际收益）
  2) reasoning 开销：思考 token 数 vs content token 数
  3) json_schema 约束下的格式成功率（response_format）

输出 CSV 到 stdout 追加行，可直接进对照实验表。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import httpx

AGENT_PROMPT = """你是外卖决策系统的预算评估 Agent。对下面候选给出结构化评分，只输出 JSON。
候选：香辣烤鱼小份，总价36元含配送，预计26分钟，中辣，非面食。
用户约束：预算40元以内，30分钟内吃到，想吃辣，不吃面。
输出字段：candidate_id, hard_constraint_pass, score(0-1), evidence(数组), risks(数组), confidence(0-1)。"""

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string"},
        "hard_constraint_pass": {"type": "boolean"},
        "score": {"type": "number"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["candidate_id", "hard_constraint_pass", "score", "evidence", "confidence"],
}


async def one_request(client: httpx.AsyncClient, args, use_schema: bool) -> dict:
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": AGENT_PROMPT}],
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "top_p": 0.95,
    }
    if use_schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "agent_score", "schema": JSON_SCHEMA},
        }
    t0 = time.perf_counter()
    r = await client.post(f"{args.base_url}/v1/chat/completions", json=payload, timeout=300)
    dt = time.perf_counter() - t0
    r.raise_for_status()
    data = r.json()
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    usage = data.get("usage", {})
    json_ok = False
    try:
        json.loads(content)
        json_ok = True
    except Exception:
        pass
    return {
        "latency_s": dt,
        "completion_tokens": usage.get("completion_tokens", 0),
        "content_chars": len(content),
        "reasoning_chars": len(reasoning),
        "json_ok": json_ok,
    }


async def bench(args) -> None:
    async with httpx.AsyncClient() as client:
        print("mode,concurrency,run,latency_avg_s,latency_max_s,total_tokens,agg_tok_s,json_ok_rate")
        for use_schema in ([False, True] if args.test_schema else [False]):
            mode = "json_schema" if use_schema else "free"
            for conc in args.concurrency:
                for run in range(args.runs):
                    t0 = time.perf_counter()
                    results = await asyncio.gather(
                        *[one_request(client, args, use_schema) for _ in range(conc)]
                    )
                    wall = time.perf_counter() - t0
                    lat = [r["latency_s"] for r in results]
                    toks = sum(r["completion_tokens"] for r in results)
                    ok = sum(r["json_ok"] for r in results) / len(results)
                    print(
                        f"{mode},{conc},{run},{statistics.mean(lat):.1f},{max(lat):.1f},"
                        f"{toks},{toks / wall:.1f},{ok:.2f}"
                    )
                    if run == 0 and results:
                        r0 = results[0]
                        print(
                            f"# sample: reasoning={r0['reasoning_chars']}ch "
                            f"content={r0['content_chars']}ch json_ok={r0['json_ok']}",
                        )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8080")
    p.add_argument("--model", default="step-local")
    p.add_argument("--concurrency", type=int, nargs="+", default=[1, 4])
    p.add_argument("--max-tokens", type=int, default=1200)
    p.add_argument("--temperature", type=float, default=1.0)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--test-schema", action="store_true", help="同时测 json_schema 约束模式")
    asyncio.run(bench(p.parse_args()))


if __name__ == "__main__":
    main()
