"""可解释加权评分器。LLM 不直接拍板：Agent 出分，评分器排序，Foreman 出主推荐+备选。

final_score = Σ(维度分 × 权重) − risk_penalty
任一 hard_constraint_pass == false 的候选在进入本模块前就已被淘汰。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .decision_schema import AgentScore, Candidate, FinalChoice

# Agent 名 → 权重键。新增 Agent 时同步更新这里与 ScoringWeights。
AGENT_WEIGHT_KEY = {
    "taste": "w_taste",
    "budget": "w_budget",
    "time": "w_time",
    "memory": "w_memory",
    "novelty": "w_novelty",
}

RISK_PENALTY_PER_FLAG = 0.05


class ScoringWeights(BaseModel):
    """权重随用户偏好和当前状态调整（如低耐心 → w_time 提高）。"""

    w_taste: float = 0.30
    w_budget: float = 0.25
    w_time: float = 0.25
    w_memory: float = 0.15
    w_novelty: float = 0.05

    @classmethod
    def for_state(cls, state: str) -> "ScoringWeights":
        if state == "low_patience":
            return cls(w_taste=0.20, w_budget=0.20, w_time=0.45, w_memory=0.10, w_novelty=0.05)
        if state == "tired":
            return cls(w_taste=0.25, w_budget=0.20, w_time=0.35, w_memory=0.15, w_novelty=0.05)
        if state == "indulge":  # 放纵吃：口味压倒一切
            return cls(w_taste=0.55, w_budget=0.10, w_time=0.15, w_memory=0.10, w_novelty=0.10)
        if state == "fitness":
            return cls(w_taste=0.35, w_budget=0.20, w_time=0.20, w_memory=0.20, w_novelty=0.05)
        return cls()


class RankedCandidate(BaseModel):
    candidate: Candidate
    final_score: float
    breakdown: dict[str, float] = Field(default_factory=dict)  # agent 名 → 加权前得分
    risks: list[str] = Field(default_factory=list)


def rank(
    candidates: list[Candidate],
    agent_scores: dict[str, list[AgentScore]],
    weights: ScoringWeights,
) -> list[RankedCandidate]:
    """聚合各 Agent 结构化评分，输出降序排名。缺失某 Agent 评分按 0.5 中性处理并记录。"""
    ranked: list[RankedCandidate] = []
    for c in candidates:
        total, breakdown, risks = 0.0, {}, []
        for agent, weight_key in AGENT_WEIGHT_KEY.items():
            per_agent = {s.candidate_id: s for s in agent_scores.get(agent, [])}
            s = per_agent.get(c.id)
            if s is None:
                breakdown[agent] = 0.5
                total += 0.5 * getattr(weights, weight_key)
                continue
            if not s.hard_constraint_pass:
                # Agent 声称违规 → 交 Auditor 复核规则；评分层保守直接淘汰
                risks.append(f"{agent} 判定硬约束不通过")
                total = -1.0
                break
            breakdown[agent] = s.score
            total += s.score * getattr(weights, weight_key)
            risks.extend(s.risks)
        if total < 0:
            continue
        total -= RISK_PENALTY_PER_FLAG * len(risks)
        ranked.append(
            RankedCandidate(candidate=c, final_score=round(total, 4), breakdown=breakdown, risks=risks)
        )
    ranked.sort(key=lambda r: r.final_score, reverse=True)
    return ranked


def to_final_choice(ranked: list[RankedCandidate]) -> FinalChoice | None:
    if not ranked:
        return None
    top = ranked[0]
    backup = ranked[1] if len(ranked) > 1 else None
    reasons = [f"{agent} 得分 {score:.2f}" for agent, score in sorted(top.breakdown.items(), key=lambda kv: -kv[1])[:3]]
    return FinalChoice(
        candidate_id=top.candidate.id,
        backup_id=backup.candidate.id if backup else None,
        reasons=reasons,
        risk_notes=top.risks,
        confidence=min(0.99, max(0.0, top.final_score)),
    )
