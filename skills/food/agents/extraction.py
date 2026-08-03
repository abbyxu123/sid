"""结构化抽取任务定义：系统提示 + 扁平/嵌套转换。

这是 Step 与 kitten 共用的任务契约；training/train_kitten.py 内嵌了同一份
SYSTEM_PROMPT（local AI host 上独立运行），改动必须双向同步并重训。
"""
from __future__ import annotations

import json

from core.decision_schema import Context, HardConstraints, SoftPreferences

SYSTEM_PROMPT = """你是猫咪决策机的需求结构化模块。把用户的话解析成 JSON，字段：
goal(字符串), allergens(数组), diet_taboos(数组), hated(数组), budget_max(数字或null),
eat_by_minutes(数字或null), spicy("none"/"mild"/"medium"/"hot"/null), cuisines(数组),
novelty("conservative"/"balanced"/"bold"/null), people(数字), state("normal"/"tired"/"low_patience"/"fitness"/"late_night"/"indulge"), channel("delivery"/"dine_in"/"any")。
用户没提到的字段用 null/[]/默认值(people=1, state="normal", channel="any")。只输出 JSON。"""


def parse_json_loose(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in: {text[:80]!r}")
    return json.loads(text[start:end])


def unflatten(flat: dict) -> tuple[str, HardConstraints, SoftPreferences, Context]:
    """kitten/Step 的扁平输出 → Schema 对象。非法枚举值宽容降级为默认。"""
    def _list(key):
        v = flat.get(key)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            # 模型把数组写成字符串时宽容接住——尤其过敏原，静默丢弃是安全事故
            return [s.strip() for s in v.replace("、", ",").replace("，", ",").split(",") if s.strip()]
        return []

    def _num(key):
        v = flat.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    hard = HardConstraints(
        allergens=_list("allergens"), diet_taboos=_list("diet_taboos"),
        hated=_list("hated"), budget_max=_num("budget_max"),
        eat_by_minutes=int(_num("eat_by_minutes")) if _num("eat_by_minutes") else None,
    )
    spicy = flat.get("spicy")
    soft = SoftPreferences(
        spicy=spicy if spicy in ("none", "mild", "medium", "hot") else None,
        cuisines=_list("cuisines"),
        novelty=flat.get("novelty") if flat.get("novelty") in ("conservative", "balanced", "bold") else None,
    )
    state = flat.get("state")
    channel = flat.get("channel")
    ctx = Context(
        people=int(_num("people") or 1),
        state=state if state in ("normal", "tired", "low_patience", "fitness", "late_night", "indulge") else "normal",
        channel=channel if channel in ("delivery", "dine_in", "any") else "any",
    )
    return str(flat.get("goal") or ""), hard, soft, ctx


# ---- 规则降级解析（模型全部不可用时的最后一道）----
_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "半": 0.5}
_FOOD_WORDS = ("面食", "面条", "米线", "米粉", "海鲜", "香菜", "葱", "姜", "蒜",
               "牛肉", "猪肉", "羊肉", "鸡肉", "内脏", "甜食", "油炸", "生冷", "辣")


def rule_structure(text: str):
    """确定性关键词解析：kitten 与 Step 都失联时兜底主闭环。

    安全边界：文本里出现「过敏」但下面的模式解析不出过敏原时，抛 ValueError——
    宁可进 error 态让用户重说，也不能带着丢失的过敏信息继续推荐。
    """
    import re

    _STOP = set("点些会是都也不很有的了我你他她它这那")
    allergens = [a for a in re.findall(r"(?:对)?([一-鿿]{1,4}?)过敏", text)
                 if a and a[-1] not in _STOP and a not in _STOP]
    if "过敏" in text and not allergens:
        raise ValueError("检测到过敏表述但无法解析过敏原")
    taboos, hated = [], []
    for w in _FOOD_WORDS:
        if re.search(rf"(不要|不吃|别放|不能吃|忌){w}", text):
            (taboos if w in ("面食", "面条", "米线", "米粉", "海鲜", "内脏") else hated).append(w)
    def _cn2num(s: str):
        if not s:
            return None
        if s.isdigit():
            return float(s)
        n, unit = 0, 0
        if "十" in s:
            a, _, b = s.partition("十")
            n = _CN_NUM.get(a, 1) * 10 + (_CN_NUM.get(b, 0) if b else 0)
        else:
            n = _CN_NUM.get(s, 0)
        return float(n) if n else None

    budget = None
    m = re.search(r"([\d一二两三四五六七八九十]+)\s*(?:块|元)", text) or \
        re.search(r"([\d一二两三四五六七八九十]+)\s*以内", text)
    if m:
        budget = _cn2num(m.group(1))
    eat_by = None
    m = re.search(r"(\d+)\s*分钟", text)
    if m:
        eat_by = int(m.group(1))
    elif "半小时" in text or "半个小时" in text:
        eat_by = 30
    elif re.search(r"[一1]\s*(?:个)?小时", text):
        eat_by = 60
    spicy = None
    if re.search(r"不(?:要|吃|能吃)辣|不辣", text):
        spicy = "none"
        hated = [h for h in hated if h != "辣"]
    elif "微辣" in text:
        spicy = "mild"
    elif "辣" in text:
        spicy = "hot"
    max_dist = None
    m = re.search(r"(\d+)\s*米内", text)
    if m:
        max_dist = int(m.group(1))
    elif re.search(r"(\d+)\s*公里内", text):
        max_dist = int(re.search(r"(\d+)\s*公里内", text).group(1)) * 1000
    elif "附近" in text:
        max_dist = 1000
    novelty = "bold" if re.search(r"随便|都行|来点新|试试新|尝鲜", text) else None
    channel = "dine_in" if re.search(r"到店|堂食|附近吃|出去吃", text) else "any"
    hard = HardConstraints(allergens=allergens, diet_taboos=taboos, hated=hated,
                           budget_max=budget, eat_by_minutes=eat_by, max_distance_m=max_dist)
    soft = SoftPreferences(spicy=spicy, cuisines=[], novelty=novelty)
    ctx = Context(people=2 if re.search(r"两个人|俩人|双人", text) else 1,
                  state="normal", channel=channel)
    return text[:40], hard, soft, ctx
