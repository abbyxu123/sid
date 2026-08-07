"""专业 Agent 的 prompt 模板与输出 Schema。

原则（对应规划 06 节）：
- 每个 Agent 独立会话、边界清晰的小任务，结束即重置上下文；
- 输出强制 JSON Schema（llama-server response_format），低温度靠 schema 而非祈祷；
- Actor 不需要长思考链——系统提示明确要求直接给结论。
"""
from __future__ import annotations

import json

from core.decision_schema import Candidate, DecisionSession

# 单 Agent 输出的 JSON Schema（数组：每候选一条）
AGENT_OUTPUT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string"},
            "hard_constraint_pass": {"type": "boolean"},
            "score": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            "risks": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "unknowns": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["candidate_id", "hard_constraint_pass", "score", "evidence", "confidence"],
    },
}

SYSTEM_COMMON = (
    "你是猫咪决策机的{role}。只做一件事：{duty}。"
    "直接给结论，不要展开推理过程。对每个候选输出一条 JSON 记录，evidence 每条不超过 15 字。"
)

AGENT_ROLES = {
    "taste": {
        "role": "口味评估猫",
        "duty": "按用户口味偏好（辣度/菜系/口感/温度）为每个候选打 0-1 分",
        "context_fields": ["soft_preferences"],
    },
    "budget": {
        "role": "预算评估猫",
        "duty": "核对总价（含配送费）与预算的余量，评估超支风险，为每个候选打 0-1 分",
        "context_fields": ["hard_constraints"],
    },
    "distance": {
        "role": "定位距离猫",
        "duty": "根据距离、配送或步行可达性评估便利度，为每个候选打 0-1 分",
        "context_fields": ["hard_constraints", "context"],
    },
    "time": {
        "role": "时间评估猫",
        "duty": "评估配送/路程/排队耗时与用户时间窗口的匹配度，为每个候选打 0-1 分",
        "context_fields": ["hard_constraints", "context"],
    },
    "memory": {
        "role": "记忆猫",
        "duty": "根据近期饮食记录评估重复度与复购意愿，为每个候选打 0-1 分（重复吃过降分，曾好评升分）",
        "context_fields": ["ledger_recent"],
    },
    "novelty": {
        "role": "探索猫",
        "duty": "在安全范围内评估新鲜感：没吃过的菜系/店加分，说明为什么值得尝试",
        "context_fields": ["soft_preferences", "ledger_recent"],
    },
    "auditor": {
        "role": "审核猫",
        "duty": "独立复核各评估结果：找出违反硬约束、与候选事实矛盾或凭空捏造的结论",
        "context_fields": ["hard_constraints"],
    },
}


def candidate_brief(c: Candidate) -> dict:
    """给 Agent 看的候选摘要——只给该任务需要的字段，控制上下文长度。"""
    return {
        "id": c.id, "restaurant": c.restaurant, "item": c.item,
        "price_total": c.price_total, "eta_minutes": c.eta_minutes,
        "distance_m": c.distance_m,
        "cuisine": c.cuisine, "spicy": c.spicy_level,
        "queue_minutes": c.queue_minutes, "tags": c.tags,
    }


def build_agent_messages(
    agent: str, session: DecisionSession, candidates: list[Candidate],
    ledger_recent: list | None = None,
) -> list[dict]:
    spec = AGENT_ROLES[agent]
    ctx: dict = {}
    if "soft_preferences" in spec["context_fields"]:
        ctx["用户偏好"] = session.soft_preferences.model_dump(exclude_none=True)
    if "hard_constraints" in spec["context_fields"]:
        ctx["硬约束"] = session.hard_constraints.model_dump(exclude_none=True)
    if "context" in spec["context_fields"]:
        ctx["场景"] = session.context.model_dump()
    if "ledger_recent" in spec["context_fields"]:
        # 全量 payload 会把 prompt 撑到 3 万+ token（200 条封顶）且超出学徒 2048 ctx，
        # 议事会被拖到分钟级——只保留决策要点，最近 25 条
        compact = []
        for rec in (ledger_recent or [])[:25]:
            p = rec.get("payload") or {}
            if rec.get("kind") == "choice" and p.get("final"):
                compact.append({"吃过": p["final"].get("candidate_id")})
            elif rec.get("kind") == "feedback":
                compact.append({"评分": p.get("rating"), "复购": p.get("would_repeat"),
                                "原因": (p.get("reject_reason") or "")[:20]})
        ctx["近期记录"] = compact
    user = (
        f"背景：{json.dumps(ctx, ensure_ascii=False)}\n"
        f"候选：{json.dumps([candidate_brief(c) for c in candidates], ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": SYSTEM_COMMON.format(role=spec["role"], duty=spec["duty"])},
        {"role": "user", "content": user},
    ]
