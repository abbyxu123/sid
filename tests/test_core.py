"""核心不变量测试：硬约束 0 违规是红线，任何合并前必须通过。"""
import asyncio
import json
from pathlib import Path

from core.auditor import deterministic_audit
from core.constraint_engine import filter_candidates
from core.decision_schema import (
    Candidate,
    Channel,
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
    assert r["ok"] and r["url"].endswith(f"/console?sid={sid}")
    assert r["order_url"].startswith("https://")
    assert r["order_url"].split("/")[2] in ("uri.amap.com", "h5.ele.me", "www.meituan.com")
    # 未确认状态不可执行
    sid2 = c.post("/v1/session", json={"device_id": "t"}).json()["session_id"]
    assert c.post("/v1/confirm", json={"session_id": sid2}).status_code == 409


def test_default_confirm_prefers_h5_console_and_delivery_action():
    """硬件扫码入口应始终是 H5；用户没说到店时，外部动作默认走外卖搜索。"""
    import os
    os.environ["USE_MODEL"] = "0"
    from fastapi.testclient import TestClient

    from services.device_gateway.main import app
    c = TestClient(app)
    sid = c.post("/v1/session", json={"device_id": "t"}).json()["session_id"]
    c.post("/v1/input", json={"session_id": sid,
        "hard_constraints": {"budget_max": 100, "eat_by_minutes": 60}})
    c.post("/v1/device/event", json={"device_id": "t", "session_id": sid, "event": "right_ear"})
    r = c.post("/v1/confirm", json={"session_id": sid}).json()
    assert r["console_url"].endswith(f"/console?sid={sid}")
    assert r["action"] == "order_deeplink"
    assert r["url"].endswith(f"/console?sid={sid}")
    assert r["order_url"].startswith("https://h5.ele.me/")


def test_delivery_context_overrides_dine_in_candidate_action():
    """候选来自到店/拍照菜单时，只要场景是外卖，就不能直接把 QR/主动作变成地图。"""
    from services.tool_gateway.adapters import build_action

    candidate = Candidate(id="x", restaurant="附近小店", item="烤鱼小份",
                          price_total=36, eta_minutes=28, cuisine="川湘",
                          channel=Channel.dine_in)
    action = build_action(candidate, Channel.delivery)
    assert action.action == "order_deeplink"
    assert action.url.startswith("https://h5.ele.me/")


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


def test_raw_input_ingredient_preference_lifts_fish_candidate():
    """用户明确说想吃鱼时，食材偏好应影响排序而不是被普通辣味候选盖掉。"""
    session = make_session(
        raw_input="我想吃鱼 40分钟之内",
        hard_constraints=HardConstraints(budget_max=60, eat_by_minutes=40),
        soft_preferences=SoftPreferences(spicy="medium"),
    )
    session = asyncio.run(run_decision(session, load(), model=None))
    assert session.state == SessionState.candidate
    assert session.final_choice is not None
    assert session.final_choice.candidate_id == "r01_kaoyu_s"


def test_raw_input_ingredient_preference_keeps_swipe_options_on_topic():
    """用户说想吃鱼时，前几张可滑候选也必须围绕鱼/海鲜，不要第二张就跑到串串盖饭。"""
    session = make_session(
        raw_input="我想吃鱼 40分钟之内",
        hard_constraints=HardConstraints(budget_max=80, eat_by_minutes=40),
        soft_preferences=SoftPreferences(spicy="medium"),
    )
    session = asyncio.run(run_decision(session, load(), model=None))
    first_three = session.candidates[:3]
    assert len(first_three) >= 3
    assert all(
        "鱼" in c.item or "海鲜" in c.tags or "鱼" in c.ingredients
        for c in first_three
    )


def test_explore_keeps_ingredient_preference_pool_on_topic():
    """摇一摇/盲选也只能在用户原始品类里抽，不得从全安全池跳走。"""
    session = make_session(
        raw_input="我想吃鱼 40分钟之内",
        hard_constraints=HardConstraints(budget_max=80, eat_by_minutes=40),
        soft_preferences=SoftPreferences(novelty="bold"),
    )
    session = asyncio.run(run_decision(session, load(), model=None))
    first_three = session.candidates[:3]
    assert len(first_three) >= 3
    assert all(
        "鱼" in c.item or "海鲜" in c.tags or "鱼" in c.ingredients
        for c in first_three
    )


def test_raw_input_beef_preference_never_falls_back_to_mixed_pool():
    """牛肉候选少也不能回退全菜单，否则会在筛选结果里混入鸡肉/鱼/豆腐。"""
    session = make_session(
        raw_input="我想吃牛肉 40分钟之内",
        hard_constraints=HardConstraints(budget_max=80, eat_by_minutes=40),
    )
    session = asyncio.run(run_decision(session, load(), model=None))
    assert session.candidates
    assert all(
        "牛肉" in c.item or "牛肉" in c.ingredients or "牛肉" in c.tags
        for c in session.candidates
    )


def test_confirm_can_bind_h5_selected_candidate():
    """H5 本地切换/盲盒后，确认必须执行用户当前看到的那张卡。"""
    import os
    from urllib.parse import unquote

    os.environ["USE_MODEL"] = "0"
    from fastapi.testclient import TestClient

    from services.device_gateway.main import app
    c = TestClient(app)
    sid = c.post("/v1/session", json={"device_id": "phone"}).json()["session_id"]
    c.post("/v1/input", json={"session_id": sid,
        "text": "我想吃鱼",
        "hard_constraints": {"budget_max": 80, "eat_by_minutes": 40}})
    state = c.get(f"/v1/session/{sid}").json()
    target = next(x for x in state["candidates"] if x["id"] != state["candidates"][0]["id"])
    c.post("/v1/device/event", json={"device_id": "phone", "session_id": sid, "event": "right_ear"})
    r = c.post("/v1/confirm", json={"session_id": sid, "candidate_id": target["id"]}).json()
    assert r["action"] == "order_deeplink"
    assert r["url"].endswith(f"/console?sid={sid}")
    assert target["item"][:2] in unquote(r["order_url"])


def test_done_session_can_auto_return_idle():
    """二维码页超时后，后端推回 idle；旧固件也能退出喵单页。"""
    import os

    os.environ["USE_MODEL"] = "0"
    from fastapi.testclient import TestClient

    from services.device_gateway.main import app, auto_idle_after_done, sessions
    c = TestClient(app)
    sid = c.post("/v1/session", json={"device_id": "phone"}).json()["session_id"]
    c.post("/v1/input", json={"session_id": sid,
        "text": "我想吃鱼",
        "hard_constraints": {"budget_max": 80, "eat_by_minutes": 40}})
    c.post("/v1/device/event", json={"device_id": "phone", "session_id": sid, "event": "right_ear"})
    c.post("/v1/confirm", json={"session_id": sid})
    assert sessions[sid].state == SessionState.done
    asyncio.run(auto_idle_after_done(sid, delay_s=0))
    assert sessions[sid].state == SessionState.idle


def test_new_device_session_starts_idle_for_standby():
    """设备刚连上但用户没操作时，应允许固件自己的待机屏计时生效。"""
    import os

    os.environ["USE_MODEL"] = "0"
    from fastapi.testclient import TestClient

    from services.device_gateway.main import app
    c = TestClient(app)
    sid = c.post("/v1/session", json={"device_id": "cat-square-01"}).json()["session_id"]
    assert c.get(f"/v1/session/{sid}").json()["state"] == "idle"


def test_listening_followup_can_auto_return_idle():
    """追问后如果用户放下设备，不应永久停在 listening。"""
    import os

    os.environ["USE_MODEL"] = "0"
    from fastapi.testclient import TestClient

    from services.device_gateway.main import app, auto_idle_after_listening, sessions
    c = TestClient(app)
    sid = c.post("/v1/session", json={"device_id": "phone"}).json()["session_id"]
    c.post("/v1/input", json={"session_id": sid, "text": "随便来点"})
    assert sessions[sid].state == SessionState.listening
    asyncio.run(auto_idle_after_listening(sid, delay_s=0))
    assert sessions[sid].state == SessionState.idle


def test_done_left_ear_returns_idle_without_restarting_council():
    """二维码页点左半屏表示反悔返回，不再停在喵单或误开议事会。"""
    import os

    os.environ["USE_MODEL"] = "0"
    from fastapi.testclient import TestClient

    from services.device_gateway.main import app, sessions
    c = TestClient(app)
    sid = c.post("/v1/session", json={"device_id": "phone"}).json()["session_id"]
    c.post("/v1/input", json={"session_id": sid,
        "text": "我想吃鱼",
        "hard_constraints": {"budget_max": 80, "eat_by_minutes": 40}})
    c.post("/v1/device/event", json={"device_id": "phone", "session_id": sid, "event": "right_ear"})
    c.post("/v1/confirm", json={"session_id": sid})
    assert sessions[sid].state == SessionState.done
    c.post("/v1/device/event", json={"device_id": "phone", "session_id": sid, "event": "left_ear"})
    assert sessions[sid].state == SessionState.idle


def test_done_both_ears_does_not_restart_council():
    """二维码页顶部误触不应把已出单流程拉回今日推荐/议事会。"""
    import os

    os.environ["USE_MODEL"] = "0"
    from fastapi.testclient import TestClient

    from services.device_gateway.main import app, sessions
    c = TestClient(app)
    sid = c.post("/v1/session", json={"device_id": "phone"}).json()["session_id"]
    c.post("/v1/input", json={"session_id": sid,
        "text": "我想吃鱼",
        "hard_constraints": {"budget_max": 80, "eat_by_minutes": 40}})
    c.post("/v1/device/event", json={"device_id": "phone", "session_id": sid, "event": "right_ear"})
    c.post("/v1/confirm", json={"session_id": sid})
    assert sessions[sid].state == SessionState.done
    c.post("/v1/device/event", json={"device_id": "phone", "session_id": sid, "event": "both_ears"})
    assert sessions[sid].state == SessionState.done


def test_hungry_uses_fresh_mmwave_sample():
    """毫米波上报真实体征后，「饿不饿」必须带上传感器依据，而不是只返回手账兜底文案。"""
    import os

    os.environ["USE_MODEL"] = "0"
    from fastapi.testclient import TestClient

    from services.device_gateway.main import app
    c = TestClient(app)
    sample = {
        "present": True,
        "target_count": 1,
        "distance_cm": 42.5,
        "heart_bpm": 82,
        "respiration_bpm": 15,
        "illuminance_lux": 40.7,
        "source": "mr60bha2-usb",
    }
    assert c.post("/v1/sensor/mmwave", json=sample).json()["ok"] is True
    r = c.get("/v1/hungry").json()
    assert r["sensor"]["fresh"] is True
    assert r["sensor"]["heart_bpm"] == 82
    assert r["sensor"]["respiration_bpm"] == 15
    assert r["sensor"]["distance_cm"] == 42.5
    assert r["decision"] in {"hungry", "maybe_craving", "not_hungry"}
    assert "毫米波" in r["subtitle"]
