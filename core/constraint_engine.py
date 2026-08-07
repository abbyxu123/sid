"""确定性硬规则层：过敏、禁忌、预算、时间由规则保护，模型不能推翻。

这是评委必看项之一：hard_constraint 违规率目标 0%。
任何候选进入 Agent 评估之前必须先过这里；Auditor 事后还会用同一套规则复核。
"""
from __future__ import annotations

from .decision_schema import Candidate, Channel, Context, HardConstraints


def check_candidate(
    c: Candidate, hard: HardConstraints, ctx: Context | None = None
) -> tuple[bool, list[str]]:
    """返回 (是否通过, 未通过原因列表)。原因用于可解释展示与 Ledger。"""
    reasons: list[str] = []

    for allergen in hard.allergens:
        # 过敏是最高红线：菜名子串 + 食材/标签子串都查（宁可误杀不可漏过）
        if (allergen in c.item
                or any(allergen in ing for ing in c.ingredients)
                or any(allergen in t for t in c.tags)):
            reasons.append(f"含过敏原「{allergen}」")

    for taboo in hard.diet_taboos:
        if taboo in c.ingredients or taboo in c.tags or taboo == c.cuisine:
            reasons.append(f"触发禁忌「{taboo}」")

    for hate in hard.hated:
        if hate in c.ingredients or hate in c.tags or hate in c.item:
            reasons.append(f"用户明确不吃「{hate}」")

    if hard.budget_max is not None and c.price_total > hard.budget_max:
        reasons.append(f"总价 ¥{c.price_total:.0f} 超预算 ¥{hard.budget_max:.0f}")

    if hard.eat_by_minutes is not None and c.eta_minutes > hard.eat_by_minutes:
        reasons.append(f"预计 {c.eta_minutes} 分钟，超出最晚 {hard.eat_by_minutes} 分钟")

    if hard.max_distance_m is not None and c.distance_m and c.distance_m > hard.max_distance_m:
        reasons.append(f"距离 {c.distance_m}m 超出半径 {hard.max_distance_m}m")

    if not c.open_now:
        reasons.append("当前未营业")

    if ctx is not None and ctx.channel != Channel.any and c.channel != ctx.channel:
        reasons.append(f"渠道不符（需要{ctx.channel.value}）")

    return (not reasons, reasons)


def filter_candidates(
    candidates: list[Candidate], hard: HardConstraints, ctx: Context | None = None
) -> tuple[list[Candidate], dict[str, list[str]]]:
    """硬规则过滤。返回 (通过的候选, {淘汰候选 id: 原因})。"""
    passed: list[Candidate] = []
    rejected: dict[str, list[str]] = {}
    for c in candidates:
        ok, reasons = check_candidate(c, hard, ctx)
        if ok:
            passed.append(c)
        else:
            rejected[c.id] = reasons
    return passed, rejected
