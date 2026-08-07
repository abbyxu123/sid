"""核心不变量测试：硬约束 0 违规是红线，任何合并前必须通过。"""
import asyncio
import json
from pathlib import Path

from core.auditor import deterministic_audit
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
from core.scoring import ScoringWeights

DEMO = Path(__file__).resolve().parents[1] / "skills/food/demo_data/restaurants.json"


def load() -> list[Candidate]:
    return [Candidate(**c) for c in json.loads(DEMO.read_text(encoding="utf-8"))]


def make_session(**kw) -> DecisionSession:
    return DecisionSession(session_id="t1", **kw)


def test_allergen_never_passes():
    hard = HardConstraints(allergens=["花生"])
    passed, rejected = filter_candidates(load(), hard)
    assert all("花生" not in c.ingredients for c in passed)
    assert any("花生" in "".join(r) for r in rejected.values())


def test_budget_and_time_hard():
    hard = HardConstraints(budget_max=40, eat_by_minutes=30)
    passed, _ = filter_candidates(load(), hard)
    assert passed, "demo 数据里必须存在可行解"
    assert all(c.price_total <= 40 and c.eta_minutes <= 30 for c in passed)


def test_demo_conflict_case():
    """文档 10 节标准演示任务：40 元内、辣、非面食、30 分钟。
    串串(排队45分钟/58元)必须被淘汰，烤鱼小份必须存活。"""
    hard = HardConstraints(budget_max=40, eat_by_minutes=30, diet_taboos=["面食"])
    passed, rejected = filter_candidates(load(), hard)
    ids = {c.id for c in passed}
    assert "r01_kaoyu_s" in ids
    assert "r02_chuanchuan" in rejected
    assert "r03_lanzhou" in rejected  # 面食


def test_rules_only_full_loop():
    """规则降级路径端到端：无模型也能从输入走到 candidate + 审核通过。"""
    session = make_session(
        raw_input="四十块以内想吃辣的，不吃面，半小时内",
        hard_constraints=HardConstraints(budget_max=40, eat_by_minutes=30, diet_taboos=["面食"]),
        soft_preferences=SoftPreferences(spicy="medium"),
        context=Context(state="normal"),
    )
    session = asyncio.run(run_decision(session, load(), model=None))
    assert session.state == SessionState.candidate
    assert session.final_choice is not None
    audit = deterministic_audit(session)
    assert audit.approve
    chosen = {c.id: c for c in session.candidates}[session.final_choice.candidate_id]
    assert chosen.price_total <= 40 and chosen.eta_minutes <= 30


def test_no_feasible_candidate_is_error_not_hallucination():
    session = make_session(hard_constraints=HardConstraints(budget_max=5))
    session = asyncio.run(run_decision(session, load(), model=None))
    assert session.state == SessionState.error
    assert session.final_choice is None


def test_weights_sum_reasonable():
    for state in ("normal", "tired", "low_patience", "fitness"):
        w = ScoringWeights.for_state(state)
        total = w.w_taste + w.w_budget + w.w_time + w.w_memory + w.w_novelty
        assert abs(total - 1.0) < 1e-6


def test_explore_mode_safe_random():
    """安全探索：novelty 用户走随机抽取，但硬约束过滤仍不可绕过。"""
    from core.decision_schema import SoftPreferences as SP
    session = make_session(
        hard_constraints=HardConstraints(allergens=["花生"], budget_max=45),
        soft_preferences=SP(novelty="bold"),
    )
    session = asyncio.run(run_decision(session, load(), model=None))
    assert session.decision_mode.value == "explore"
    assert session.state == SessionState.candidate
    chosen = {c.id: c for c in session.candidates}[session.final_choice.candidate_id]
    assert "花生" not in chosen.ingredients and chosen.price_total <= 45
    # 同 session 重放结果一致（可审计）
    again = make_session(
        hard_constraints=HardConstraints(allergens=["花生"], budget_max=45),
        soft_preferences=SP(novelty="bold"),
    )
    again = asyncio.run(run_decision(again, load(), model=None))
    assert again.final_choice.candidate_id == session.final_choice.candidate_id


def test_unflatten_tolerates_garbage():
    from skills.food.agents.extraction import unflatten
    goal, hard, soft, ctx = unflatten({
        "goal": None, "allergens": "花生", "budget_max": "四十",
        "spicy": "超级辣", "state": "困", "people": None, "channel": "堂食",
    })
    assert hard.allergens == ["花生"] and hard.budget_max is None  # 字符串过敏原必须接住不丢
    assert soft.spicy is None and ctx.state == "normal" and ctx.channel.value == "any"


def test_confirm_flow_produces_whitelisted_deeplink():
    """确认 → 执行深链：human_confirmed 之后才有 action，域名必须在白名单。"""
    import os
    os.environ["USE_MODEL"] = "0"
    from fastapi.testclient import TestClient

    from services.device_gateway.main import app
    c = TestClient(app)
    sid = c.post("/v1/session", json={"device_id": "t"}).json()["session_id"]
    c.post("/v1/input", json={"session_id": sid,
        "hard_constraints": {"budget_max": 40, "eat_by_minutes": 30}})
    c.post("/v1/device/event", json={"device_id": "t", "session_id": sid, "event": "right_ear"})
    r = c.post("/v1/confirm", json={"session_id": sid}).json()
    assert r["ok"] and r["url"].startswith("https://")
    assert r["url"].split("/")[2] in ("uri.amap.com", "h5.ele.me", "www.meituan.com")
    # 未确认状态不可执行
    sid2 = c.post("/v1/session", json={"device_id": "t"}).json()["session_id"]
    assert c.post("/v1/confirm", json={"session_id": sid2}).status_code == 409


def test_device_event_idempotent():
    """固件重发同一 timestamp 事件只生效一次（去抖/网络重试场景）。"""
    import os
    os.environ["USE_MODEL"] = "0"
    from fastapi.testclient import TestClient

    from services.device_gateway.main import app
    c = TestClient(app)
    sid = c.post("/v1/session", json={"device_id": "t"}).json()["session_id"]
    c.post("/v1/input", json={"session_id": sid,
        "hard_constraints": {"budget_max": 40, "eat_by_minutes": 30}})
    evt = {"device_id": "t", "session_id": sid, "event": "right_ear", "timestamp": 1784212345}
    r1 = c.post("/v1/device/event", json=evt).json()
    r2 = c.post("/v1/device/event", json=evt).json()
    assert r1["state"] == "confirming"
    assert r2.get("duplicate") is True and r2["state"] == "confirming"


def test_review_fixes_allergen_hardening():
    """评审修复回归：带空格/全角逗号的过敏原字符串、菜名子串匹配。"""
    from skills.food.agents.extraction import unflatten
    _, hard, _, _ = unflatten({"allergens": "花生， 虾"})
    assert hard.allergens == ["花生", "虾"]
    c = Candidate(id="x", restaurant="r", item="芒果布丁", price_total=10,
                  eta_minutes=10, cuisine="甜品")
    from core.constraint_engine import check_candidate
    ok, reasons = check_candidate(c, HardConstraints(allergens=["芒果"]))
    assert not ok and "芒果" in reasons[0]


def test_candidates_ordered_by_rank():
    """评审修复回归：candidates[0] 必须就是 final_choice（展示=执行=评分赢家）。"""
    session = make_session(
        hard_constraints=HardConstraints(budget_max=40, eat_by_minutes=30),
        soft_preferences=SoftPreferences(spicy="medium"),
    )
    session = asyncio.run(run_decision(session, load(), model=None))
    assert session.candidates[0].id == session.final_choice.candidate_id


def test_concrete_food_preference_limits_swipe_pool():
    """用户点名食材后，换一个/滑动候选不能混入无关菜品。"""
    fish = asyncio.run(run_decision(
        make_session(raw_input="今天想吃鱼", hard_constraints=HardConstraints(budget_max=150)),
        load(), model=None,
    ))
    assert fish.candidates
    assert all(
        any(term in text for term in ("鱼", "海鲜", "寿司", "刺身"))
        for candidate in fish.candidates
        for text in [" ".join([
            candidate.item, candidate.cuisine, *candidate.ingredients, *candidate.tags,
        ])]
    )

    beef = asyncio.run(run_decision(
        make_session(raw_input="我想吃牛肉", hard_constraints=HardConstraints(budget_max=150)),
        load(), model=None,
    ))
    assert beef.candidates
    assert all(
        "牛肉" in " ".join([candidate.item, *candidate.ingredients, *candidate.tags])
        for candidate in beef.candidates
    )

    no_match = asyncio.run(run_decision(
        make_session(raw_input="今天想吃蔬菜", hard_constraints=HardConstraints(budget_max=150)),
        load(), model=None,
    ))
    assert no_match.state == SessionState.error
    assert no_match.candidates == []


def test_done_page_returns_to_idle_after_30_seconds_or_left_action():
    import os

    os.environ["USE_MODEL"] = "0"
    from fastapi.testclient import TestClient

    from services.device_gateway.main import (
        DONE_AUTO_IDLE_SECONDS,
        app,
        auto_idle_after_done,
        sessions,
    )

    assert DONE_AUTO_IDLE_SECONDS == 30
    client = TestClient(app)
    sid = client.post("/v1/session", json={"device_id": "qr-timeout"}).json()["session_id"]
    client.post("/v1/input", json={
        "session_id": sid,
        "hard_constraints": {"budget_max": 80, "eat_by_minutes": 60},
    })
    client.post("/v1/device/event", json={
        "device_id": "qr-timeout", "session_id": sid, "event": "right_ear",
    })
    client.post("/v1/confirm", json={"session_id": sid})
    assert sessions[sid].state == SessionState.done
    asyncio.run(auto_idle_after_done(sid, delay_s=0))
    assert sessions[sid].state == SessionState.idle

    sessions[sid].state = SessionState.done
    client.post("/v1/device/event", json={
        "device_id": "qr-timeout", "session_id": sid, "event": "left_ear",
    })
    assert sessions[sid].state == SessionState.idle


def test_rules_mode_keeps_food_scope_across_voice_followup():
    """纯规则模式也要解析原话，追问预算后不能丢掉第一句的食物范围。"""
    import os

    os.environ["USE_MODEL"] = "0"
    from fastapi.testclient import TestClient

    import services.device_gateway.main as gateway

    gateway.USE_MODEL = False
    client = TestClient(gateway.app)
    sid = client.post("/v1/session", json={"device_id": "rules-voice"}).json()["session_id"]

    first = client.post("/v1/input", json={
        "session_id": sid,
        "text": "今天想吃鱼，不要辣",
    }).json()
    assert first["state"] == SessionState.listening
    assert first["soft_preferences"]["spicy"] == "none"

    second = client.post("/v1/input", json={
        "session_id": sid,
        "text": "一百五十元，六十分钟内",
    }).json()
    assert second["state"] == SessionState.candidate
    assert "想吃鱼" in second["raw_input"]
    assert "一百五十元" in second["raw_input"]
    assert second["soft_preferences"]["spicy"] == "none"
    assert second["candidates"]
    assert all(candidate["spicy_level"] == "none" for candidate in second["candidates"])
    assert all(
        any(term in [candidate["item"], candidate["cuisine"],
                     *candidate["ingredients"], *candidate["tags"]]
            for term in ("鱼", "海鲜", "寿司", "刺身"))
        for candidate in second["candidates"]
    )
