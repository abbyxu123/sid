"""结构化抽取评测：对任意 OpenAI 兼容端点跑 40 条验收集，输出字段级准确率 + 延迟。

同一脚本评 Step 基线 / 原始 Qwen / 蒸馏后 kitten —— 三方对照表直接由此产出。

  python scripts/eval_extraction.py --base-url http://127.0.0.1:8080 --model step-local \
      --cases tests/synthetic_cases/cases.json --tag step37_baseline --concurrency 4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

# kitten 训练与评测共用的系统提示（改这里 = 改任务定义，训练数据需重生成）
SYSTEM_PROMPT = """你是猫咪决策机的需求结构化模块。把用户的话解析成 JSON，字段：
goal(字符串), allergens(数组), diet_taboos(数组), hated(数组), budget_max(数字或null),
eat_by_minutes(数字或null), spicy("none"/"mild"/"medium"/"hot"/null), cuisines(数组),
novelty("conservative"/"balanced"/"bold"/null), people(数字), state("normal"/"tired"/"low_patience"/"fitness"/"late_night"), channel("delivery"/"dine_in"/"any")。
用户没提到的字段用 null/[]/默认值(people=1, state="normal", channel="any")。只输出 JSON。"""

LIST_FIELDS = ["allergens", "diet_taboos", "hated", "cuisines"]
SCALAR_FIELDS = ["budget_max", "eat_by_minutes", "spicy", "novelty", "people", "state", "channel"]


def flatten_gt(gt: dict) -> dict:
    """cases.json 的嵌套真值 → 扁平格式。"""
    hc, sp, ctx = gt["hard_constraints"], gt["soft_preferences"], gt["context"]
    return {
        "allergens": hc.get("allergens", []), "diet_taboos": hc.get("diet_taboos", []),
        "hated": hc.get("hated", []), "budget_max": hc.get("budget_max"),
        "eat_by_minutes": hc.get("eat_by_minutes"), "spicy": sp.get("spicy"),
        "cuisines": sp.get("cuisines", []), "novelty": sp.get("novelty"),
        "people": ctx.get("people", 1), "state": ctx.get("state", "normal"),
        "channel": ctx.get("channel", "any"),
    }


def parse_json_loose(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}") + 1
    return json.loads(text[start:end])


SPICY_ALIAS = {"不辣": "none", "微辣": "mild", "中辣": "medium", "特辣": "hot", "重辣": "hot", "很辣": "hot"}


def norm_item(x) -> str:
    """菜系/忌口别名归一：'西北菜'≈'西北'，'云南菜'≈'云南'——对所有被评模型一视同仁。"""
    s = str(x).strip()
    return s[:-1] if s.endswith("菜") and len(s) > 2 and s[:-1] not in ("川", "湘", "粤", "鲁") else s


def score_fields(pred: dict, gt: dict) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for f in LIST_FIELDS:
        p = {norm_item(v) for v in (pred.get(f) or [])}
        g = {norm_item(v) for v in (gt.get(f) or [])}
        out[f] = p == g
    for f in SCALAR_FIELDS:
        p, g = pred.get(f), gt.get(f)
        if f == "spicy":
            p = SPICY_ALIAS.get(p, p)
            if p == "none" and g is None:
                p = None  # none 与未提及等价
        if f in ("budget_max", "eat_by_minutes", "people") and p is not None:
            try:
                p = float(p)
                g = float(g) if g is not None else g
            except (TypeError, ValueError):
                pass
        out[f] = p == g
    return out


async def eval_one(client: httpx.AsyncClient, args, sem, case: dict) -> dict:
    async with sem:
        t0 = time.perf_counter()
        try:
            r = await client.post(
                f"{args.base_url}/v1/chat/completions",
                json={
                    "model": args.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": case["utterance"]},
                    ],
                    "max_tokens": args.max_tokens,
                    "temperature": 0.2,
                },
                timeout=600,
            )
            r.raise_for_status()
            d = r.json()
            content = d["choices"][0]["message"].get("content") or ""
            latency = time.perf_counter() - t0
            pred = parse_json_loose(content)
            fields = score_fields(pred, flatten_gt(case["ground_truth"]))
            return {"case_id": case["case_id"], "latency": latency, "json_ok": True,
                    "fields": fields, "exact": all(fields.values()), "pred": pred,
                    "completion_tokens": d.get("usage", {}).get("completion_tokens")}
        except Exception as e:
            return {"case_id": case["case_id"], "latency": time.perf_counter() - t0,
                    "json_ok": False, "fields": {}, "exact": False, "error": f"{type(e).__name__}: {e}"}


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--cases", default="tests/synthetic_cases/cases.json")
    p.add_argument("--tag", required=True)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--max-tokens", type=int, default=1500)
    p.add_argument("--out-dir", default="docs/benchmarks")
    args = p.parse_args()

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.perf_counter()
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[eval_one(client, args, sem, c) for c in cases])
    wall = time.perf_counter() - t0

    n = len(results)
    json_ok = sum(r["json_ok"] for r in results)
    exact = sum(r["exact"] for r in results)
    lat = [r["latency"] for r in results if r["json_ok"]]
    all_fields = LIST_FIELDS + SCALAR_FIELDS
    field_acc = {
        f: sum(r["fields"].get(f, False) for r in results) / n for f in all_fields
    }
    summary = {
        "tag": args.tag, "model": args.model, "n": n,
        "json_ok_rate": json_ok / n, "exact_match_rate": exact / n,
        "field_acc": {k: round(v, 3) for k, v in field_acc.items()},
        "avg_field_acc": round(sum(field_acc.values()) / len(field_acc), 3),
        "latency_avg_s": round(statistics.mean(lat), 2) if lat else None,
        "latency_p95_s": round(sorted(lat)[int(0.95 * len(lat)) - 1], 2) if lat else None,
        "wall_s": round(wall, 1),
    }
    out = Path(args.out_dir) / f"extraction_{args.tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    errs = [r for r in results if not r["json_ok"]]
    for r in errs[:5]:
        print("ERR", r["case_id"], r.get("error", "")[:100])


if __name__ == "__main__":
    asyncio.run(main())
