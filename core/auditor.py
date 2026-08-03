"""审核猫：独立复核所有 Agent 输出。不与 Foreman 共用思考链。

第一道是确定性复核（规则重放），第二道才是 LLM 事实核查（7/18 接入）。
"""
from __future__ import annotations

from .constraint_engine import check_candidate
from .decision_schema import AuditVerdict, DecisionSession


def deterministic_audit(session: DecisionSession) -> AuditVerdict:
    """用硬规则重放每个候选：任何 Agent 都不能让违规候选溜进最终选择。"""
    corrections: list[str] = []
    rejected: dict[str, str] = {}

    for c in session.candidates:
        ok, reasons = check_candidate(c, session.hard_constraints, session.context)
        if not ok:
            rejected[c.id] = "; ".join(reasons)

    for agent, scores in session.agent_scores.items():
        for s in scores:
            if s.candidate_id in rejected and s.hard_constraint_pass:
                corrections.append(
                    f"{agent} 对 {s.candidate_id} 判定通过，但规则复核不通过：{rejected[s.candidate_id]}"
                )

    if session.final_choice and session.final_choice.candidate_id in rejected:
        corrections.append("最终选择违反硬约束，必须重选")
        return AuditVerdict(approve=False, corrections=corrections, rejected=rejected)

    return AuditVerdict(approve=True, corrections=corrections, rejected=rejected)
