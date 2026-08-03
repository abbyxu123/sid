"""用自托管 Kimi-K2.7-Code（16×A100 sglang）批量生成 Demo 数据。仅离线使用，不进运行时链路。

  # 在能访问 10.84.10.22:8003 的机器（工作站）上：
  python scripts/gen_demo_data_kimi.py restaurants --n 40 --out skills/food/demo_data/restaurants.json
  python scripts/gen_demo_data_kimi.py cases --out tests/synthetic_cases/cases.json

cases 用「逆向生成」保证标签零噪声：先随机采样结构化真值（约束/偏好/状态），
再让 Kimi 把真值改写成自然的用户原话 → (utterance, ground_truth) 对。
这批数据同时是: ① 40 条验收测试集 ② 小模型结构化抽取器(kitten)的训练数据种子。
"""
from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

import httpx

SEED = 20260716
CUISINES = ["川菜", "湘菜", "粤菜", "日料", "韩餐", "西北", "轻食", "云南", "鲁菜", "东北菜"]
ALLERGENS = ["花生", "海鲜", "虾", "芒果", "鸡蛋"]
TABOOS = ["面食", "猪肉", "牛肉", "炸物", "生冷"]
STATES = ["normal", "tired", "low_patience", "fitness", "late_night"]
CATEGORIES = ["allergy_hard", "conflict", "dine_in_queue", "one_shot", "explore"]


def call_kimi(client: httpx.Client, base_url: str, model: str, prompt: str) -> str:
    headers = {}
    if key := os.environ.get("KIMI_API_KEY"):
        headers["Authorization"] = f"Bearer {key}"
    r = client.post(
        f"{base_url}/v1/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 16384,
            "temperature": 0.8,
        },
        timeout=600,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def extract_json(text: str):
    start = min(i for i in (text.find("["), text.find("{")) if i >= 0)
    end = max(text.rfind("]"), text.rfind("}")) + 1
    return json.loads(text[start:end])


def gen_restaurants(client, args) -> None:
    prompt = f"""生成 {args.n} 家中国城市商圈餐厅的外卖/到店 Demo 数据，JSON 数组，每条字段严格为：
id(如 r11_xxx, 从 r11 开始编号), restaurant, item(招牌套餐), price_total(数字,15-130),
eta_minutes(数字,15-50), cuisine(从 {CUISINES} 选), spicy_level(none|mild|medium|hot),
ingredients(3-5个主料,过敏原如花生/虾要如实出现), tags(从 面食/米饭/汤/热食/冷食/炸物/海鲜/健身 选),
distance_m(200-2000), open_now(90%为true), queue_minutes(到店0-50,外卖0), channel(delivery|dine_in,约7:3)。
要求：菜系、辣度、价位分布均匀；至少5条含花生或虾（做过敏测试）；至少4条是面食；只输出 JSON 数组。"""
    data = extract_json(call_kimi(client, args.base_url, args.model, prompt))
    Path(args.out).write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"wrote {len(data)} restaurants -> {args.out}")


def sample_ground_truth(category: str, rng: random.Random) -> dict:
    gt = {
        "goal": "找一顿现在能吃的饭",
        "hard_constraints": {
            "allergens": [], "diet_taboos": [], "budget_max": None,
            "eat_by_minutes": None, "hated": [],
        },
        "soft_preferences": {
            "spicy": rng.choice([None, "mild", "medium", "hot"]),
            "cuisines": rng.sample(CUISINES, k=rng.randint(0, 2)),
            "novelty": None,
        },
        "context": {"people": 1, "state": "normal", "channel": "any"},
        "category": category,
    }
    hc = gt["hard_constraints"]
    if category == "allergy_hard":
        hc["allergens"] = rng.sample(ALLERGENS, k=rng.randint(1, 2))
        hc["budget_max"] = rng.choice([30, 40, 50])
    elif category == "conflict":
        hc["budget_max"] = rng.choice([25, 30, 40])
        hc["eat_by_minutes"] = rng.choice([25, 30])
        hc["diet_taboos"] = rng.sample(TABOOS, k=1)
        gt["soft_preferences"]["spicy"] = rng.choice(["medium", "hot"])
    elif category == "dine_in_queue":
        gt["context"]["channel"] = "dine_in"
        gt["context"]["people"] = rng.choice([2, 3, 4])
        hc["eat_by_minutes"] = rng.choice([40, 60])
    elif category == "one_shot":
        gt["context"]["state"] = rng.choice(["tired", "low_patience"])
        hc["budget_max"] = rng.choice([30, 40, None])
    elif category == "explore":
        gt["soft_preferences"]["novelty"] = rng.choice(["balanced", "bold"])
        hc["hated"] = rng.sample(TABOOS, k=1)
        hc["allergens"] = rng.sample(ALLERGENS, k=rng.randint(0, 1))
    return gt


def gen_cases(client, args) -> None:
    rng = random.Random(SEED)
    truths = [sample_ground_truth(cat, rng) for cat in CATEGORIES for _ in range(args.per_category)]
    # 每条真值内嵌显式 0-based idx，要求原样回显——防止模型自行 1-based 编号导致整体错位
    indexed = [{"idx": i, **t} for i, t in enumerate(truths)]
    prompt = f"""下面是 {len(truths)} 条外卖/吃饭决策的结构化真值（每条自带 idx）。为每条写一句中国用户
对语音助手说的自然原话（口语、信息可打乱顺序，但必须精确蕴含全部真值信息，不得增加新约束）。
只输出 JSON 数组，每条 {{"idx": 与输入相同的idx, "utterance": "原话"}}。
真值：{json.dumps(indexed, ensure_ascii=False)}"""
    utterances = extract_json(call_kimi(client, args.base_url, args.model, prompt))
    by_idx = {u["idx"]: u["utterance"] for u in utterances}
    cases = [
        {"case_id": f"case_{i:02d}", "utterance": by_idx.get(i, ""), "ground_truth": gt}
        for i, gt in enumerate(truths)
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(cases)} cases -> {args.out}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("task", choices=["restaurants", "cases"])
    p.add_argument("--base-url", default="http://10.84.10.22:8003")
    p.add_argument("--model", default="kimi-k2.7-code")
    p.add_argument("--n", type=int, default=40)
    p.add_argument("--per-category", type=int, default=8)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    with httpx.Client() as client:
        if args.task == "restaurants":
            gen_restaurants(client, args)
        else:
            gen_cases(client, args)


if __name__ == "__main__":
    main()
