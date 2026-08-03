"""E5 对照：单 Agent 一次生成 vs 硬规则+多 Agent 议事会+审核（规划 11 节第 1 组）。

单侧：把原话+全部候选（不过滤）一次丢给 Step，让它直接选——模拟"角色 Prompt 包装"做法。
多侧：完整主链路（kitten 抽取 → 硬规则 → 议事会/规则 → 审核）。
核心指标：硬约束违规率（用确定性规则复核双方的最终选择）、耗时。

  ~/kitten/venv/bin/python scripts/eval_e5_single_vs_multi.py --n 20 --out-dir docs/benchmarks
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.constraint_engine import check_candidate, filter_candidates
from core.decision_schema import Candidate, DecisionSession
from core.model_client import ModelRouter
from core.orchestrator import run_decision
from skills.food.agents.extraction import parse_json_loose, unflatten

SINGLE_PROMPT = """用户说：{utterance}
候选餐厅：{candidates}
请直接替用户选一家，只输出 JSON：{{"candidate_id": "...", "reason": "一句话"}}"""


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cases", default="tests/synthetic_cases/cases.json")
    p.add_argument("--restaurants", nargs="+", default=[
        "skills/food/demo_data/restaurants.json", "skills/food/demo_data/restaurants_kimi.json"])
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--out-dir", default="docs/benchmarks")
    args = p.parse_args()

    pool, seen = [], set()
    for f in args.restaurants:
        for c in json.loads(Path(f).read_text(encoding="utf-8")):
            if c["id"] not in seen:
                seen.add(c["id"])
                pool.append(Candidate(**c))
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))[: args.n]
    router = ModelRouter()

    rows = []
    for case in cases:
        gt = case["ground_truth"]
        _, hard, soft, ctx = unflatten({
            **gt["hard_constraints"], **gt["soft_preferences"], **gt["context"]})
        # —— 单 Agent 一次生成（无规则保护）——
        brief = [{"id": c.id, "item": c.item, "price": c.price_total,
                  "eta": c.eta_minutes, "spicy": c.spicy_level, "tags": c.tags,
                  "ingredients": c.ingredients, "open": c.open_now} for c in pool[:30]]
        t0 = time.perf_counter()
        single_violation, single_pick = None, None
        try:
            content = await router.step.chat(
                [{"role": "user", "content": SINGLE_PROMPT.format(
                    utterance=case["utterance"],
                    candidates=json.dumps(brief, ensure_ascii=False))}],
                temperature=0.6, max_tokens=3600)
            single_pick = parse_json_loose(content).get("candidate_id")
            cand = next((c for c in pool if c.id == single_pick), None)
            if cand:
                ok, reasons = check_candidate(cand, hard, ctx)
                single_violation = (not ok, reasons)
            else:
                single_violation = (True, ["选择了不存在的候选(幻觉)"])
        except Exception as e:
            single_violation = (True, [f"失败: {type(e).__name__}"])
        t_single = time.perf_counter() - t0

        # —— 完整主链路 ——
        t0 = time.perf_counter()
        session = DecisionSession(session_id=f"e5_{case['case_id']}",
                                  raw_input=case["utterance"], hard_constraints=hard,
                                  soft_preferences=soft, context=ctx)
        session = await run_decision(session, pool, model=router)
        t_multi = time.perf_counter() - t0
        multi_violation = (False, [])
        if session.final_choice:
            cand = next(c for c in session.candidates
                        if c.id == session.final_choice.candidate_id)
            ok, reasons = check_candidate(cand, hard, ctx)
            multi_violation = (not ok, reasons)
        rows.append({
            "case_id": case["case_id"], "mode": session.decision_mode,
            "single": {"pick": single_pick, "violated": single_violation[0],
                       "why": single_violation[1], "t": round(t_single, 1)},
            "multi": {"pick": session.final_choice.candidate_id if session.final_choice else None,
                      "violated": multi_violation[0], "t": round(t_multi, 1)},
        })
        print(f"{case['case_id']}: single_viol={single_violation[0]} multi_viol={multi_violation[0]}",
              flush=True)

    summary = {
        "n": len(rows),
        "single_violation_rate": round(sum(r["single"]["violated"] for r in rows) / len(rows), 3),
        "multi_violation_rate": round(sum(r["multi"]["violated"] for r in rows) / len(rows), 3),
        "single_t_avg": round(statistics.mean(r["single"]["t"] for r in rows), 1),
        "multi_t_avg": round(statistics.mean(r["multi"]["t"] for r in rows), 1),
    }
    out = Path(args.out_dir) / "e5_single_vs_multi.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
