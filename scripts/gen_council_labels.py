"""议事会蒸馏数据工厂：Step 3.7 议事会跑训练用例，产出 Actor 评分教师标签（kitten ②）。

在 local AI host 上过夜运行（llama-server 需在线）：
  python3 scripts/gen_council_labels.py --data skills/food/kitten/train_verified.jsonl \
      --restaurants skills/food/demo_data/restaurants.json skills/food/demo_data/restaurants_kimi.json \
      --out skills/food/kitten/council_labels.jsonl --limit 400

每行输出：{case_id, agent, system, user, scores}——scores 即 Step 的结构化审议输出，
是 scorer kitten 的全部训练信号（"大猫开会教小猫"）。支持断点续传。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.constraint_engine import filter_candidates
from core.decision_schema import Candidate, DecisionSession
from core.model_client import ModelError, ModelRouter
from skills.food.agents.extraction import unflatten
from skills.food.agents.prompts import build_agent_messages

AGENTS = ["taste", "budget", "time", "memory"]


def build_session(row: dict) -> DecisionSession:
    goal, hard, soft, ctx = unflatten(row["target"])
    return DecisionSession(
        session_id=f"label_{row['id']}", raw_input=row["utterance"],
        goal=goal, hard_constraints=hard, soft_preferences=soft, context=ctx)


async def one_case(router, sem, row, pool, out_path, lock, agents=AGENTS) -> int:
    session = build_session(row)
    passed, _ = filter_candidates(pool, session.hard_constraints, session.context)
    if len(passed) < 2:
        return 0  # 没有比较意义
    if len(passed) > 6:
        # 规则分取前 5 + 随机 1：候选越多思考链越长，截断率和耗时都指数上涨
        from random import Random

        from core.orchestrator import rule_based_scores
        from core.scoring import ScoringWeights, rank
        ranked = rank(passed, rule_based_scores(session, passed),
                      ScoringWeights.for_state(session.context.state))
        top = [r.candidate for r in ranked[:5]]
        rest = [r.candidate for r in ranked[5:]]
        passed = top + Random(row["id"]).sample(rest, k=min(1, len(rest)))
    async def run_agent(agent: str) -> dict | None:
        async with sem:  # 信号量在单次调用层：4 个 Agent 并行吃满服务槽位
            for attempt in range(2):  # 失败重试一次——单角失败会让整个 case 无法用于蒸馏
                try:
                    scores = await router.agent_score(agent, session, passed)
                    break
                except Exception as e:
                    if attempt == 1:
                        print(f"case {row['id']} {agent}: {type(e).__name__}", flush=True)
                        return None
        messages = build_agent_messages(agent, session, passed)
        return {"case_id": row["id"], "agent": agent,
                "system": messages[0]["content"], "user": messages[1]["content"],
                "scores": [s.model_dump() for s in scores]}

    recs = [r for r in await asyncio.gather(*[run_agent(a) for a in agents]) if r]
    async with lock:
        with out_path.open("a", encoding="utf-8") as f:
            for rec in recs:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(recs)


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--restaurants", nargs="+", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=400)
    p.add_argument("--concurrency", type=int, default=4)  # Agent 调用级并发 = 服务槽位数
    args = p.parse_args()

    pool: list[Candidate] = []
    seen = set()
    for f in args.restaurants:
        for c in json.loads(Path(f).read_text(encoding="utf-8")):
            if c["id"] not in seen:
                seen.add(c["id"])
                pool.append(Candidate(**c))

    rows = [json.loads(l) for l in Path(args.data).read_text(encoding="utf-8").splitlines()]
    rows = rows[: args.limit]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # (case, agent) 粒度续传：已有部分角的 case 只补缺失的 Agent
    done_pairs: set[tuple] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done_pairs.add((r["case_id"], r["agent"]))
        print(f"resume: {len(done_pairs)} (case,agent) pairs done", flush=True)
    todo: list[tuple[dict, list[str]]] = []
    for r in rows:
        missing = [a for a in AGENTS if (r["id"], a) not in done_pairs]
        if missing:
            todo.append((r, missing))
    rows_missing = todo

    router = ModelRouter()
    router.kitten = None  # 教师必须是 Step 本尊
    sem = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()
    t0 = time.time()
    total = 0
    rows = rows_missing
    for i in range(0, len(rows), 20):
        chunk = rows[i:i + 20]
        results = await asyncio.gather(
            *[one_case(router, sem, r, pool, out_path, lock, agents=missing)
              for r, missing in chunk])
        total += sum(results)
        print(f"progress {i + len(chunk)}/{len(rows)} agent-records={total} "
              f"elapsed={time.time() - t0:.0f}s", flush=True)
    print(f"DONE total agent-records: {total}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
