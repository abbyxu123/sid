"""Scorer kitten 评测：在留出 case 上对比学徒 vs Step 议事会。

指标（按重要性）：
- top1_agree: 用各自四猫评分走同一个加权评分器后，主推荐是否一致（决策一致率，核心）
- score_mae: 各 Agent 对各候选评分的平均绝对误差
- hard_flag_agree: hard_constraint_pass 判断一致率
- json_ok / 延迟

  python3 scripts/eval_scorer.py --labels skills/food/kitten/council_labels.jsonl \
      --holdout 40 --kitten-url http://127.0.0.1:8081 --tag scorer_4b
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.decision_schema import AgentScore
from core.scoring import ScoringWeights, rank
from core.decision_schema import Candidate


def regroup(labels: list[dict]) -> dict[str, dict]:
    """council_labels.jsonl → {case_id: {agent: record}}，只保留四猫齐全的 case。"""
    by_case: dict[str, dict] = defaultdict(dict)
    for r in labels:
        by_case[str(r["case_id"])][r["agent"]] = r
    out = {}
    skipped_inconsistent = 0
    for cid, agents in by_case.items():
        if not set(agents) >= {"taste", "budget", "time", "memory"}:
            continue
        # 四猫必须看同一份候选列表（跨版本修补的 case 会不一致，评测失真，剔除）
        briefs = {a["user"].split("候选：", 1)[1] for a in agents.values()}
        if len(briefs) > 1:
            skipped_inconsistent += 1
            continue
        out[cid] = agents
    if skipped_inconsistent:
        print(f"skipped {skipped_inconsistent} cases with inconsistent candidate sets")
    return out


def candidates_from_user(user: str) -> list[Candidate]:
    """从 Agent prompt 的候选 JSON 段还原轻量 Candidate（够评分器用）。"""
    briefs = json.loads(user.split("候选：", 1)[1])
    return [Candidate(
        id=b["id"], restaurant=b.get("restaurant", ""), item=b.get("item", ""),
        price_total=b.get("price_total", 0), eta_minutes=b.get("eta_minutes", 0),
        cuisine=b.get("cuisine", ""), spicy_level=b.get("spicy", "none"),
        queue_minutes=b.get("queue_minutes", 0), tags=b.get("tags", []),
    ) for b in briefs]


async def kitten_scores(client, args, sem, rec: dict) -> tuple[list[AgentScore] | None, float]:
    async with sem:
        t0 = time.perf_counter()
        try:
            r = await client.post(
                f"{args.kitten_url}/v1/chat/completions",
                json={"model": args.kitten_model,
                      "messages": [{"role": "system", "content": rec["system"]},
                                   {"role": "user", "content": rec["user"]}],
                      "max_tokens": 150 + 80 * len(rec["scores"]),
                      "temperature": 0.2},
                timeout=120)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"] or ""
            start, end = content.find("["), content.rfind("]") + 1
            rows = json.loads(content[start:end])
            return [AgentScore(**x) for x in rows], time.perf_counter() - t0
        except Exception:
            return None, time.perf_counter() - t0


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--labels", required=True)
    p.add_argument("--holdout", type=int, default=40, help="用最后 N 个 case 做留出集")
    p.add_argument("--kitten-url", default="http://127.0.0.1:8081")
    p.add_argument("--kitten-model", default="kitten-nlu")
    p.add_argument("--tag", required=True)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--out-dir", default="docs/benchmarks")
    args = p.parse_args()

    labels = [json.loads(l) for l in Path(args.labels).read_text(encoding="utf-8").splitlines()]
    cases = regroup(labels)
    # 留出口径必须与 build_mixed_dataset 完全一致：原始文件全部 case_id 数值尾 N，
    # 之后再交叉可评集合——否则过滤会让两端错位造成训练/测试泄漏
    raw_ids = sorted({int(r["case_id"]) for r in labels})
    holdout_raw = {str(c) for c in raw_ids[-args.holdout:]}
    holdout = [c for c in cases if c in holdout_raw]
    print(f"cases total={len(cases)} holdout_raw={len(holdout_raw)} evaluable={len(holdout)}")

    sem = asyncio.Semaphore(args.concurrency)
    weights = ScoringWeights()
    top1_agree, maes, flag_agree, json_ok, lats = [], [], [], 0, []
    n_calls = 0
    async with httpx.AsyncClient() as client:
        for cid in holdout:
            agents = cases[cid]
            cands = candidates_from_user(agents["taste"]["user"])
            step_scores, kit_scores = {}, {}
            results = await asyncio.gather(
                *[kitten_scores(client, args, sem, agents[a]) for a in ("taste", "budget", "time", "memory")])
            ok = True
            for agent, (kscores, lat) in zip(("taste", "budget", "time", "memory"), results):
                n_calls += 1
                lats.append(lat)
                sscores = [AgentScore(**x) for x in agents[agent]["scores"]]
                step_scores[agent] = sscores
                if kscores is None:
                    ok = False
                    continue
                json_ok += 1
                kit_scores[agent] = kscores
                smap = {s.candidate_id: s for s in sscores}
                for k in kscores:
                    if k.candidate_id in smap:
                        maes.append(abs(k.score - smap[k.candidate_id].score))
                        flag_agree.append(k.hard_constraint_pass == smap[k.candidate_id].hard_constraint_pass)
            if not ok:
                continue
            r_step = rank(cands, step_scores, weights)
            r_kit = rank(cands, kit_scores, weights)
            if r_step and r_kit:
                top1_agree.append(r_step[0].candidate.id == r_kit[0].candidate.id)

    summary = {
        "tag": args.tag, "holdout_cases": len(holdout), "agent_calls": n_calls,
        "json_ok_rate": round(json_ok / max(n_calls, 1), 3),
        "top1_agree_rate": round(sum(top1_agree) / max(len(top1_agree), 1), 3),
        "score_mae": round(statistics.mean(maes), 4) if maes else None,
        "hard_flag_agree": round(sum(flag_agree) / max(len(flag_agree), 1), 3),
        "latency_avg_s": round(statistics.mean(lats), 2) if lats else None,
    }
    out = Path(args.out_dir) / f"scorer_{args.tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
