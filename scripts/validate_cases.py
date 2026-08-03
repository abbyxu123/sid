"""校验合成测试集：真值必须能通过 Schema 解析，且在餐厅库中存在可行解。

  python scripts/validate_cases.py \
      --cases tests/synthetic_cases/cases.json \
      --restaurants skills/food/demo_data/restaurants.json skills/food/demo_data/restaurants_kimi.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.constraint_engine import filter_candidates
from core.decision_schema import (
    Candidate,
    Context,
    DecisionSession,
    HardConstraints,
    SessionState,
    SoftPreferences,
)
from core.orchestrator import run_decision


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cases", default="tests/synthetic_cases/cases.json")
    p.add_argument("--restaurants", nargs="+", default=["skills/food/demo_data/restaurants.json"])
    args = p.parse_args()

    pool: list[Candidate] = []
    seen: set[str] = set()
    for f in args.restaurants:
        for c in json.loads(Path(f).read_text(encoding="utf-8")):
            cand = Candidate(**c)
            if cand.id not in seen:
                seen.add(cand.id)
                pool.append(cand)
    print(f"餐厅池: {len(pool)} 家")

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    infeasible, errors = [], []
    mode_count: dict[str, int] = {}
    for case in cases:
        gt = case["ground_truth"]
        try:
            session = DecisionSession(
                session_id=case["case_id"],
                raw_input=case["utterance"],
                hard_constraints=HardConstraints(**gt["hard_constraints"]),
                soft_preferences=SoftPreferences(**gt["soft_preferences"]),
                context=Context(**gt["context"]),
            )
        except Exception as e:
            errors.append(f"{case['case_id']}: schema 解析失败 {e}")
            continue
        passed, _ = filter_candidates(pool, session.hard_constraints, session.context)
        if not passed:
            infeasible.append(f"{case['case_id']} ({gt['category']}): 无可行候选")
            continue
        session = asyncio.run(run_decision(session, pool, model=None))
        mode = session.decision_mode.value if session.decision_mode else "?"
        mode_count[mode] = mode_count.get(mode, 0) + 1
        if session.state != SessionState.candidate:
            errors.append(f"{case['case_id']}: 闭环未到 candidate ({session.state})")

    print(f"用例: {len(cases)} | 路由分布: {mode_count}")
    for line in infeasible + errors:
        print("  !!", line)
    if infeasible or errors:
        sys.exit(1)
    print("全部用例可行，闭环通过 ✓")


if __name__ == "__main__":
    main()
