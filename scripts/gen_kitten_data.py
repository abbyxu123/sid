"""Kitten 训练数据工厂：放大逆向生成到数千条（Kimi 离线，异步并发+断点续传）。

  export KIMI_API_KEY=...
  python scripts/gen_kitten_data.py --n 4000 --base-url http://127.0.0.1:18003 \
      --out skills/food/kitten/train_raw.jsonl

输出 JSONL，每行 {"utterance": ..., "target": <扁平化真值>, "style": ..., "category": ...}。
真值先采样、原话后生成 → 标签零噪声。与 tests/synthetic_cases/cases.json（验收集）
用不同 RNG 种子，天然不重叠；训练前仍会做一次字符串去重。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
from pathlib import Path

import httpx

SEED = 20260717
CUISINES = ["川菜", "湘菜", "粤菜", "日料", "韩餐", "西北", "轻食", "云南", "鲁菜", "东北菜", "江浙", "泰国菜", "汉堡西式", "麻辣烫", "饺子馄饨"]
ALLERGENS = ["花生", "海鲜", "虾", "芒果", "鸡蛋", "牛奶", "坚果"]
TABOOS = ["面食", "猪肉", "牛肉", "炸物", "生冷", "内脏", "香菜", "辣"]
STATES = ["normal", "tired", "low_patience", "fitness", "late_night"]
SPICY = [None, "none", "mild", "medium", "hot"]
NOVELTY = [None, None, None, "conservative", "balanced", "bold"]
CHANNELS = ["any", "any", "delivery", "delivery", "dine_in"]
STYLES = [
    "口语随意，像跟朋友说话",
    "很简短，有点不耐烦",
    "啰嗦纠结，想法来回变但最终信息完整",
    "带语气词（呃、那个、就是）",
    "打字输入，夹杂一两个错别字或缩写",
    "礼貌正式一点",
    "边想边说，信息顺序打乱",
]


def sample_target(rng: random.Random) -> dict:
    """扁平化真值：kitten 的训练目标格式（与 eval_extraction.py 保持一致）。"""
    n_allergen = rng.choices([0, 1, 2], weights=[6, 3, 1])[0]
    n_taboo = rng.choices([0, 1, 2], weights=[5, 4, 1])[0]
    t = {
        "goal": "找一顿现在能吃的饭",
        "allergens": rng.sample(ALLERGENS, k=n_allergen),
        "diet_taboos": rng.sample(TABOOS, k=n_taboo),
        "hated": rng.sample(TABOOS, k=rng.choices([0, 1], weights=[7, 3])[0]),
        "budget_max": rng.choice([None, 20, 25, 30, 40, 50, 60, 80, 100]),
        "eat_by_minutes": rng.choice([None, None, 20, 25, 30, 40, 60]),
        "spicy": rng.choice(SPICY),
        "cuisines": rng.sample(CUISINES, k=rng.choices([0, 1, 2], weights=[5, 4, 1])[0]),
        "novelty": rng.choice(NOVELTY),
        "people": rng.choices([1, 2, 3, 4], weights=[7, 2, 0.5, 0.5])[0],
        "state": rng.choices(STATES, weights=[5, 2, 2, 1, 1])[0],
        "channel": rng.choice(CHANNELS),
    }
    # 去掉自相矛盾：hated/taboos 重叠、辣偏好与忌辣冲突
    t["hated"] = [h for h in t["hated"] if h not in t["diet_taboos"]]
    if "辣" in t["diet_taboos"] or "辣" in t["hated"]:
        t["spicy"] = "none"
    return t


BATCH_PROMPT = """下面是 {n} 条"用户让 AI 帮忙决定吃什么"的结构化真值。为每条写一句中国用户说的自然原话。
文风要求：{style}。
硬要求：原话必须蕴含该条全部非空真值信息（null/空数组的字段不要提及，也不要编造新约束）；
state 用状态描述表达（tired=累了，low_patience=别让我选/快点定，fitness=减脂/健身餐，late_night=夜宵）；
channel 的 delivery=要外卖送来，dine_in=想出去吃/堂食，any 不用提；people>1 要体现几个人吃。
只输出 JSON 数组：[{{"idx": 0, "utterance": "..."}}, ...]
真值：
{targets}"""


async def gen_batch(client: httpx.AsyncClient, args, sem, batch_id: int,
                    items: list[tuple[int, dict, str]], out_path: Path, lock) -> int:
    style = items[0][2]
    targets = [{"idx": i, **t} for i, (_, t, _) in enumerate(items)]
    prompt = BATCH_PROMPT.format(n=len(items), style=style, targets=json.dumps(targets, ensure_ascii=False))
    headers = {}
    if key := os.environ.get("KIMI_API_KEY"):
        headers["Authorization"] = f"Bearer {key}"
    async with sem:
        for attempt in range(3):
            try:
                r = await client.post(
                    f"{args.base_url}/v1/chat/completions", headers=headers,
                    json={"model": args.model, "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": 8192, "temperature": 0.9},
                    timeout=600,
                )
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
                start, end = text.find("["), text.rfind("]") + 1
                rows = json.loads(text[start:end])
                by_idx = {u["idx"]: u["utterance"] for u in rows if u.get("utterance")}
                written = 0
                async with lock:
                    with out_path.open("a", encoding="utf-8") as f:
                        for local_i, (global_i, t, st) in enumerate(items):
                            utt = by_idx.get(local_i)
                            if utt:
                                f.write(json.dumps(
                                    {"id": global_i, "utterance": utt, "target": t, "style": st},
                                    ensure_ascii=False) + "\n")
                                written += 1
                print(f"batch {batch_id}: {written}/{len(items)}")
                return written
            except Exception as e:
                print(f"batch {batch_id} attempt {attempt}: {type(e).__name__} {e}")
                await asyncio.sleep(5 * (attempt + 1))
    return 0


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=4000)
    p.add_argument("--batch-size", type=int, default=25)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--base-url", default="http://127.0.0.1:18003")
    p.add_argument("--model", default="kimi-k2.7-code")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids: set[int] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            try:
                done_ids.add(json.loads(line)["id"])
            except Exception:
                pass
        print(f"resume: {len(done_ids)} already done")

    rng = random.Random(SEED)
    all_items = []
    for i in range(args.n):
        t = sample_target(rng)
        style = STYLES[i // args.batch_size % len(STYLES)]
        if i not in done_ids:
            all_items.append((i, t, style))

    batches = [all_items[i:i + args.batch_size] for i in range(0, len(all_items), args.batch_size)]
    print(f"todo: {len(all_items)} samples in {len(batches)} batches")
    sem = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[gen_batch(client, args, sem, bi, b, out_path, lock) for bi, b in enumerate(batches)]
        )
    print(f"TOTAL written this run: {sum(results)}; file now has ~{len(done_ids) + sum(results)}")


if __name__ == "__main__":
    asyncio.run(main())
