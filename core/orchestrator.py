"""Foreman（会长猫）：路由、编排、汇总、重试。

主链路：输入 → 结构化 → 硬规则过滤 → (直接推荐 | 议事会) → 评分 → 审核 → 候选展示。
本文件先提供确定性路由 + 规则降级路径（不依赖模型即可跑通闭环）；
LLM Agent 调用通过 model_client 注入，7/17 接 Step 3.7。
"""
from __future__ import annotations

from statistics import pstdev
from typing import Protocol

from .constraint_engine import filter_candidates
from .decision_schema import (
    AgentScore,
    Candidate,
    DecisionMode,
    DecisionSession,
    FinalChoice,
    SessionState,
)
from .scoring import ScoringWeights, rank, to_final_choice


INGREDIENT_PREFERENCES = (
    "鱼", "牛肉", "猪肉", "鸡肉", "鸡", "虾", "蟹", "豆腐", "蔬菜",
    "青菜", "生菜", "米饭", "寿司", "烤串", "串串", "面", "粥",
)
NEGATIVE_PREFIXES = ("不吃", "不要", "别吃", "讨厌", "过敏", "不能吃")


class ModelClient(Protocol):
    """模型侧实现此协议（core.model_client.ModelRouter）。"""

    async def council(
        self, agents: list[str], session: DecisionSession, candidates: list[Candidate],
        ledger_recent: list | None = None, sink: dict | None = None,
    ) -> dict[str, list[AgentScore]]: ...


def route(session: DecisionSession, passed: list[Candidate]) -> DecisionMode:
    """确定性路由：不是每次都开议事会。"""
    if len(passed) == 1:
        return DecisionMode.direct   # 唯一候选没有可权衡的，开会纯烧时间
    if any("menu_photo" in c.tags for c in passed):
        # 拍照菜品无结构化元数据，规则评分有便宜偏置——交给 LLM 议事会做口味判断
        return DecisionMode.council
    if session.soft_preferences.novelty in ("balanced", "bold"):
        return DecisionMode.explore
    if len(passed) == 2:
        return DecisionMode.duel
    if session.context.state in ("tired", "low_patience"):
        return DecisionMode.direct
    if _has_conflict(session, passed):
        return DecisionMode.council
    return DecisionMode.direct


def _has_conflict(session: DecisionSession, passed: list[Candidate]) -> bool:
    """冲突启发：预算/时间余量紧张，或候选在价格与速度维度上强烈此消彼长。"""
    hard = session.hard_constraints
    if hard.budget_max is not None and passed:
        if min(c.price_total for c in passed) > hard.budget_max * 0.8:
            return True
    if hard.eat_by_minutes is not None and passed:
        if min(c.eta_minutes for c in passed) > hard.eat_by_minutes * 0.7:
            return True
    if len(passed) >= 3:
        prices = [c.price_total for c in passed]
        etas = [float(c.eta_minutes) for c in passed]
        if pstdev(prices) > 12 and pstdev(etas) > 10:
            return True
    return False


def ingredient_preferences(raw_input: str) -> list[str]:
    """Extract lightweight ingredient cravings from the user's original wording."""
    prefs: list[str] = []
    for item in INGREDIENT_PREFERENCES:
        start = raw_input.find(item)
        if start < 0:
            continue
        prefix = raw_input[max(0, start - 4):start]
        if any(neg in prefix for neg in NEGATIVE_PREFIXES):
            continue
        prefs.append(item)
    return prefs


def candidate_matches_preference(candidate: Candidate, pref: str) -> bool:
    if pref == "鱼":
        terms = ("鱼", "海鲜", "寿司", "刺身")
        haystack = [candidate.item, candidate.cuisine, *candidate.ingredients, *candidate.tags]
        return any(term in text for term in terms for text in haystack)
    if pref in candidate.item or pref in candidate.cuisine:
        return True
    return any(pref in x or x in pref for x in [*candidate.ingredients, *candidate.tags])


def focus_candidates_by_preference(
    session: DecisionSession, candidates: list[Candidate],
) -> list[Candidate]:
    """Keep swipe options on-topic when the user states a concrete craving."""
    prefs = ingredient_preferences(session.raw_input)
    if not prefs:
        return candidates
    focused = [
        c for c in candidates
        if any(candidate_matches_preference(c, pref) for pref in prefs)
    ]
    return focused if focused else candidates


def _explore(session: DecisionSession, passed: list[Candidate],
             ledger_recent: list | None) -> DecisionSession:
    """安全探索（文档 09 节）：过敏/禁忌/预算/时间过滤后的安全池内随机；
    近期吃过的排除；抽中仍需用户确认（左耳换、右耳接受）。"""
    import random

    recent_items = set()
    for rec in ledger_recent or []:
        final = (rec.get("payload") or {}).get("final") or {}
        if final.get("candidate_id"):
            recent_items.add(final["candidate_id"])
    fresh = [c for c in passed if c.id not in recent_items] or passed
    fresh = focus_candidates_by_preference(session, fresh)
    rng = random.Random(session.session_id)  # 会话内确定，可重放审计
    level = session.soft_preferences.novelty or "balanced"
    if level == "conservative":
        # 换店不换口味：偏好菜系优先
        prefer = [c for c in fresh if c.cuisine in session.soft_preferences.cuisines] or fresh
    else:
        prefer = fresh
    pick = rng.choice(prefer)
    backup = rng.choice([c for c in fresh if c.id != pick.id]) if len(fresh) > 1 else None
    session.agent_scores = {}
    session.final_choice = FinalChoice(
        candidate_id=pick.id, backup_id=backup.id if backup else None,
        reasons=[f"安全探索（{level}）：从 {len(fresh)} 个安全候选中抽取", "硬约束已全部过滤"],
        risk_notes=[], confidence=0.6,
    )
    rest = [c for c in fresh if c.id not in (pick.id, backup.id if backup else None)]
    session.candidates = [pick] + ([backup] if backup else []) + rest
    session.state = SessionState.candidate
    session.cursor = 0
    return session


def rule_based_scores(
    session: DecisionSession, candidates: list[Candidate],
    ledger_recent: list | None = None,
) -> dict[str, list[AgentScore]]:
    """规则降级路径：模型不可用时，用确定性打分完成闭环（也是对照实验的 baseline）。

    记忆维度：最近吃过的降权——否则同约束下赢家永远是同一道菜（用户实测吐槽）。
    """
    recent_ids: list[str] = []
    for rec in ledger_recent or []:
        final = (rec.get("payload") or {}).get("final") or {}
        cid = final.get("candidate_id")
        if cid:
            recent_ids.append(cid)
    hard = session.hard_constraints
    ingredient_prefs = ingredient_preferences(session.raw_input)
    scores: dict[str, list[AgentScore]] = {"taste": [], "budget": [], "time": [],
                                           "memory": []}
    for c in candidates:
        levels = {"none": 0, "mild": 1, "medium": 2, "hot": 3}
        want = session.soft_preferences.spicy
        if want:
            d = abs(levels.get(c.spicy_level, 0) - levels.get(want, 0))
            taste = max(0.25, 1.0 - 0.25 * d)  # 梯度距离：想吃辣时不辣的菜必须掉分
        else:
            taste = 0.5
        if session.soft_preferences.cuisines and c.cuisine in session.soft_preferences.cuisines:
            taste = min(1.0, taste + 0.15)
        matched_prefs = [p for p in ingredient_prefs if candidate_matches_preference(c, p)]
        if matched_prefs:
            taste = 1.0
        elif ingredient_prefs:
            taste = min(taste, 0.35)
        budget = 0.5
        if hard.budget_max:
            budget = max(0.0, min(1.0, 1.0 - c.price_total / hard.budget_max * 0.8))
        tscore = 0.5
        if hard.eat_by_minutes:
            tscore = max(0.0, min(1.0, 1.0 - c.eta_minutes / hard.eat_by_minutes * 0.8))
        if c.id in recent_ids[:3]:
            mem, mev = 0.15, "最近吃过，换个口味喵"
        elif c.id in recent_ids[:10]:
            mem, mev = 0.4, "上回吃过喵"
        else:
            mem, mev = 0.8, "好久没吃，想它了喵"
        for name, val, ev in (
            ("taste", taste, matched_prefs[:1] or [f"{c.cuisine}/{c.spicy_level}"]),
            ("budget", budget, [f"总价 ¥{c.price_total:.0f}"]),
            ("time", tscore, [f"预计 {c.eta_minutes} 分钟"]),
            ("memory", mem, [mev]),
        ):
            scores[name].append(
                AgentScore(
                    candidate_id=c.id, hard_constraint_pass=True, score=round(val, 2),
                    evidence=ev, confidence=0.6,
                )
            )
    return scores


async def run_decision(
    session: DecisionSession,
    all_candidates: list[Candidate],
    model: ModelClient | None = None,
    ledger_recent: list | None = None,
    on_agent=None,
) -> DecisionSession:
    """执行一轮决策到 candidate 状态。model=None 时走规则降级路径。"""
    passed, rejected = filter_candidates(
        all_candidates, session.hard_constraints, session.context
    )
    # 追加而非覆盖：上游可能已写入 menu_parse_failed 等标记
    session.risk_flags = session.risk_flags + [
        f"{cid}: {'; '.join(rs)}" for cid, rs in rejected.items()]
    if not passed:
        session.state = SessionState.error
        return session

    session.decision_mode = route(session, passed)
    session.state = SessionState.council
    session.candidates = passed

    if session.decision_mode == DecisionMode.explore:
        return _explore(session, passed, ledger_recent)

    # 快路径策略：direct（含一键决定）用确定性规则评分，秒回；
    # 只有 council/explore/duel 才召集 LLM 议事会（kitten ② 落地后 Actor 换学徒）。
    weights = ScoringWeights.for_state(session.context.state)
    council_pool = passed
    if model is None or session.decision_mode == DecisionMode.direct:
        session.agent_scores = rule_based_scores(session, passed, ledger_recent)
    else:
        # 议事会前置粗筛：候选太多时用规则分先取前 6（直觉粗筛 → 深思终审），
        # 否则 Step 每只猫要为全部候选写评分，菜单拍照场景会拖到 5 分钟级
        if len(passed) > 6:
            pre = rank(passed, rule_based_scores(session, passed, ledger_recent), weights)
            council_pool = [r.candidate for r in pre[:6]]
            session.risk_flags.append(f"council_prefilter: {len(passed)} -> 6 规则预筛")
        agents = ["taste", "budget", "time", "memory"]
        try:
            session.agent_scores = {}
            await model.council(agents, session, council_pool,
                                ledger_recent=ledger_recent, sink=session.agent_scores,
                                on_agent=on_agent)
        except Exception:
            # 模型不可用绝不阻塞主闭环：整体降级到规则评分
            session.risk_flags.append("council_failed: 降级规则评分")
            council_pool = passed
            session.agent_scores = rule_based_scores(session, passed, ledger_recent)

    ranked = rank(council_pool, session.agent_scores, weights)
    if not ranked and passed:
        # Agent 误杀全部候选（硬规则已保证 passed 合法）→ 规则评分兜底，绝不空手
        session.risk_flags.append("agents_rejected_all: 降级规则评分")
        session.agent_scores = rule_based_scores(session, passed, ledger_recent)
        ranked = rank(passed, session.agent_scores, weights)
    session.final_choice = to_final_choice(ranked)
    # 展示/执行顺序必须与评分结果一致：candidates[0] 就是最终选择，左耳按排名向后换
    ordered = [r.candidate for r in ranked] or passed
    session.candidates = focus_candidates_by_preference(session, ordered)
    if session.final_choice and session.candidates:
        ids = {c.id for c in session.candidates}
        if session.final_choice.candidate_id not in ids:
            session.final_choice.candidate_id = session.candidates[0].id
        if len(session.candidates) > 1:
            session.final_choice.backup_id = session.candidates[1].id
    session.state = SessionState.candidate if session.final_choice else SessionState.error
    session.cursor = 0
    return session
