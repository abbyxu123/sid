"""Gateway and ESP32 regressions for the stable product flow."""

import asyncio
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient

from core.decision_schema import (
    AgentScore,
    Channel,
    Context,
    DecisionMode,
    DecisionSession,
    FinalChoice,
    HardConstraints,
    SessionState,
    SoftPreferences,
)
from core.orchestrator import ingredient_preferences, run_decision
from services.device_gateway import main as gateway
from skills.food.agents.extraction import rule_structure


FIRMWARE = (
    Path(__file__).resolve().parents[1]
    / "firmware/esp32_amoled18/noon_cat_amoled18/noon_cat_amoled18.ino"
)
CONSOLE = (
    Path(__file__).resolve().parents[1]
    / "services/device_gateway/console.html"
)


class DisconnectedWebSocket:
    def __init__(self) -> None:
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, _text: str) -> None:
        return None

    async def receive_text(self) -> str:
        raise RuntimeError("WebSocket is not connected. Need to call accept first.")


def _finished_direct(session: DecisionSession) -> DecisionSession:
    candidate = gateway.load_candidates()[0]
    session.state = SessionState.candidate
    session.candidates = [candidate]
    session.final_choice = FinalChoice(candidate_id=candidate.id, confidence=0.8)
    session.decision_mode = DecisionMode.direct
    session.agent_scores = {
        "taste": [AgentScore(
            candidate_id=candidate.id,
            hard_constraint_pass=True,
            score=0.8,
            evidence=["符合口味"],
            confidence=0.8,
        )]
    }
    return session


def test_device_stream_cleans_up_runtime_disconnect() -> None:
    ws = DisconnectedWebSocket()

    asyncio.run(gateway.device_stream(ws))

    assert ws.accepted
    assert ws not in gateway.device_sockets


def test_firmware_standby_hold_can_continue_into_recording() -> None:
    source = FIRMWARE.read_text(encoding="utf-8")

    assert "wokeWithKey" in source
    assert "saverSwallow" not in source
    assert "if (wokeWithKey)" in source


def test_firmware_initializes_the_analog_microphone() -> None:
    source = FIRMWARE.read_text(encoding="utf-8")

    assert "es8311_microphone_config(h, false)" in source
    assert "es8311_microphone_gain_set(h, ES8311_MIC_GAIN_18DB)" in source


def test_firmware_shake_only_reopens_a_candidate_decision() -> None:
    source = FIRMWARE.read_text(encoding="utf-8")
    start = source.index("void checkShake()")
    end = source.index("void setup()", start)
    check_shake = source[start:end]

    assert 'if (curState != "candidate") return;' in check_shake


def test_firmware_wifi_watch_does_not_interrupt_active_connection() -> None:
    source = FIRMWARE.read_text(encoding="utf-8")
    start = source.index("void wifiWatch()")
    end = source.index("// 像素猫动画", start)
    wifi_watch = source[start:end]
    ws_start = source.index("void onWsEvent(")
    ws_end = source.index("// 触摸四分区", ws_start)
    ws_event = source[ws_start:ws_end]

    assert "wsFailSince && !ws.isConnected()" in wifi_watch
    assert "if (type == WStype_TEXT) {" in ws_event
    assert "wsFailSince = 0;" in ws_event


def test_latest_food_intent_overrides_an_earlier_asr_negation() -> None:
    assert ingredient_preferences("不要吃鱼，我要吃鱼") == ["鱼"]
    assert ingredient_preferences("我要吃鱼，后来不想吃鱼") == []


def test_local_rules_stream_each_agent_without_an_external_model() -> None:
    seen = []
    session = DecisionSession(
        session_id="local-agent-steps",
        raw_input="我要吃鱼",
        hard_constraints=HardConstraints(budget_max=150, eat_by_minutes=60),
    )

    async def on_agent(agent: str) -> None:
        seen.append(agent)

    result = asyncio.run(
        run_decision(
            session,
            gateway.load_candidates(),
            model=None,
            ledger_recent=[],
            on_agent=on_agent,
        )
    )

    assert seen == ["taste", "distance", "time", "memory", "budget"]
    assert result.state == SessionState.candidate
    assert result.candidates
    assert all("鱼" in [*candidate.ingredients, candidate.item]
               for candidate in result.candidates)


def test_done_frame_uses_configured_public_h5_url(monkeypatch) -> None:
    monkeypatch.setattr(gateway, "PUBLIC_BASE_URL", "https://sid.example.com")
    session = DecisionSession(session_id="public-h5", state=SessionState.done)

    frame = gateway.build_frame(session)

    assert frame.qr_url == "https://sid.example.com/console?sid=public-h5"


def test_firmware_accepts_gateway_qr_url_with_local_fallback() -> None:
    source = FIRMWARE.read_text(encoding="utf-8")

    assert 'd["qr_url"]' in source
    assert "currentQrUrl" in source
    assert 'urlBase() + "/console?sid=" + sessionId' in source


def test_firmware_confirms_a_candidate_with_one_right_press() -> None:
    source = FIRMWARE.read_text(encoding="utf-8")
    start = source.index("void postEvent(")
    end = source.index("void postExplore()", start)

    assert 'curState == "candidate" || curState == "confirming"' in source[start:end]


def test_hungry_card_does_not_interrupt_an_active_decision(monkeypatch) -> None:
    class Socket:
        def __init__(self):
            self.frames = []

        async def send_text(self, frame):
            self.frames.append(frame)

    sid = "active-hungry-guard"
    socket = Socket()
    gateway.sessions[sid] = DecisionSession(session_id=sid, state=SessionState.candidate)
    gateway.active_session_id = sid
    gateway.device_sockets.append(socket)
    monkeypatch.setattr(gateway.ledger, "append", lambda *_args, **_kwargs: None)
    try:
        asyncio.run(gateway.hungry())
        assert socket.frames == []
    finally:
        gateway.device_sockets.remove(socket)
        gateway.sessions.pop(sid, None)


def test_rule_structure_understands_chinese_hundreds_minutes_and_delivery() -> None:
    _goal, hard, _soft, context = rule_structure(
        "外卖，一百五十元以内，六十分钟内"
    )

    assert hard.budget_max == 150
    assert hard.eat_by_minutes == 60
    assert context.channel.value == "delivery"


def test_rule_structure_keeps_full_food_request() -> None:
    _goal, hard, soft, context = rule_structure(
        "我要吃鱼，不吃辣椒，多加香菜，不要折耳根，不要大蒜，不要葱，"
        "两个人，外卖，六十分钟，二公里内"
    )

    assert soft.wanted_ingredients == ["鱼"]
    assert soft.extra_ingredients == ["香菜"]
    assert set(hard.hated) >= {"辣椒", "折耳根", "大蒜", "葱"}
    assert hard.eat_by_minutes == 60
    assert hard.max_distance_m == 2000
    assert context.people == 2
    assert context.channel.value == "delivery"


def test_current_wanted_food_overrides_only_saved_dislike() -> None:
    session = DecisionSession(
        session_id="profile-priority",
        hard_constraints=HardConstraints(),
        soft_preferences=SoftPreferences(wanted_ingredients=["鱼"]),
    )

    gateway.apply_profile_defaults(session, {
        "allergens": ["花生"],
        "hated": ["鱼", "辣椒"],
        "wanted_ingredients": ["牛肉"],
    })

    assert session.hard_constraints.allergens == ["花生"]
    assert session.hard_constraints.hated == ["辣椒"]
    assert session.soft_preferences.wanted_ingredients == ["鱼"]


def test_spoken_food_rules_merge_with_explicit_h5_controls() -> None:
    _goal, parsed_hard, parsed_soft, _context = rule_structure(
        "我要吃鱼，不要大蒜"
    )

    hard, soft = gateway.merge_explicit_input(
        parsed_hard,
        parsed_soft,
        HardConstraints(budget_max=80, eat_by_minutes=45, max_distance_m=3000),
        SoftPreferences(spicy="mild"),
    )

    assert hard.hated == ["大蒜"]
    assert hard.budget_max == 80
    assert hard.eat_by_minutes == 45
    assert hard.max_distance_m == 3000
    assert soft.wanted_ingredients == ["鱼"]
    assert soft.spicy == "mild"


def test_explicit_h5_context_only_overrides_fields_the_user_touched() -> None:
    parsed = Context(people=2, state="tired", channel=Channel.any)
    explicit = Context(channel=Channel.delivery)

    merged = gateway.merge_explicit_context(parsed, explicit)

    assert merged.channel == Channel.delivery
    assert merged.people == 2
    assert merged.state == "tired"


def test_profile_keeps_optional_product_identity_and_care_context(
    monkeypatch, tmp_path
) -> None:
    profile_path = tmp_path / "profile.json"
    monkeypatch.setattr(gateway, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(gateway.ledger, "append", lambda *_args, **_kwargs: None)
    client = TestClient(gateway.app)

    response = client.put("/v1/profile", json={
        "display_name": "Abby",
        "care_profile": {
            "fitness_goal": "balanced",
            "cycle_note_enabled": False,
        },
        "hated": ["折耳根", "大蒜"],
    })

    assert response.status_code == 200
    assert response.json()["profile"]["display_name"] == "Abby"
    assert response.json()["profile"]["care_profile"]["fitness_goal"] == "balanced"
    assert client.get("/v1/profile").json()["hated"] == ["折耳根", "大蒜"]


def test_h5_collects_the_detailed_mvp_decision_context() -> None:
    source = CONSOLE.read_text(encoding="utf-8")

    assert 'data-k="channel" data-v="delivery"' in source
    assert 'data-k="channel" data-v="dine_in"' in source
    assert 'data-k="people" data-v="1"' in source
    assert 'data-k="people" data-v="2"' in source
    assert 'data-k="distance" data-v="3000"' in source
    assert 'hard_constraints: buildHardConstraints()' in source
    assert 'soft_preferences: buildSoftPreferences()' in source
    assert 'context: buildContext()' in source
    assert 'return Object.keys(c).length ? c : null' in source


def test_h5_supports_multiple_taboo_and_allergy_choices() -> None:
    source = CONSOLE.read_text(encoding="utf-8")

    assert 'data-k="taboo" data-multi="true"' in source
    assert 'data-k="allergy" data-multi="true"' in source
    assert "function selectedValues(key)" in source


def test_h5_restores_receipt_after_device_auto_idle() -> None:
    source = CONSOLE.read_text(encoding="utf-8")

    assert 'd.action_result && d.action_result.ok' in source
    assert 'restoreReceipt(d)' in source


def test_voice_treats_chinese_numbers_as_food_intent(monkeypatch) -> None:
    captured = {}

    async def fake_submit(payload):
        captured["text"] = payload.text
        return {"state": "candidate"}

    monkeypatch.setattr(gateway, "_asr", lambda _pcm, _rate: "一百五十元，六十分钟内")
    monkeypatch.setattr(gateway, "submit_input", fake_submit)
    pcm = b"".join(
        int((i % 2000) - 1000).to_bytes(2, "little", signed=True)
        for i in range(5000)
    )
    client = TestClient(gateway.app)
    sid = client.post("/v1/session", json={"device_id": "cn-number-voice"}).json()["session_id"]

    response = client.post(
        f"/v1/voice?session_id={sid}&rate=16000",
        content=pcm,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 200
    assert response.json().get("chitchat") is not True
    assert captured == {"text": "一百五十元，六十分钟内"}


def test_direct_rules_flow_has_no_scripted_replay_delay(monkeypatch) -> None:
    async def fake_run(session, *_args, **_kwargs):
        return _finished_direct(session)

    monkeypatch.setattr(gateway, "USE_MODEL", False)
    monkeypatch.setattr(gateway, "run_decision", fake_run)
    client = TestClient(gateway.app)
    sid = client.post("/v1/session", json={"device_id": "fast-direct"}).json()["session_id"]

    started = perf_counter()
    response = client.post("/v1/input", json={
        "session_id": sid,
        "hard_constraints": {"budget_max": 100, "eat_by_minutes": 60},
    })

    assert response.status_code == 200
    assert perf_counter() - started < 0.5


def test_voice_background_failure_pushes_error_state(monkeypatch) -> None:
    sid = "voice-background-error"
    gateway.sessions[sid] = DecisionSession(session_id=sid, state=SessionState.structuring)

    async def fail(_payload):
        raise RuntimeError("voice failed")

    monkeypatch.setattr(gateway, "submit_input", fail)
    asyncio.run(gateway.run_voice_decision(sid, "想吃鱼"))

    assert gateway.sessions[sid].state == SessionState.error


def test_recouncil_background_failure_pushes_error_state(monkeypatch) -> None:
    sid = "recouncil-background-error"
    gateway.sessions[sid] = DecisionSession(session_id=sid, state=SessionState.council)

    async def fail(*_args, **_kwargs):
        raise RuntimeError("council failed")

    monkeypatch.setattr(gateway, "run_decision", fail)
    asyncio.run(gateway.run_recouncil_decision(sid))

    assert gateway.sessions[sid].state == SessionState.error


def test_new_background_decision_cancels_the_old_one(monkeypatch) -> None:
    sid = "background-replaced"
    gateway.sessions[sid] = DecisionSession(session_id=sid, state=SessionState.listening)

    async def scenario():
        old_started = asyncio.Event()

        async def fake_submit(payload):
            if payload.text == "old":
                old_started.set()
                await asyncio.sleep(60)
                gateway.sessions[sid].state = SessionState.error
            else:
                gateway.sessions[sid].state = SessionState.candidate

        monkeypatch.setattr(gateway, "submit_input", fake_submit)
        old_task = gateway.schedule_background_decision(
            sid, gateway.run_voice_decision(sid, "old")
        )
        await old_started.wait()
        new_task = gateway.schedule_background_decision(
            sid, gateway.run_voice_decision(sid, "new")
        )
        await new_task
        await asyncio.sleep(0)
        return old_task

    old_task = asyncio.run(scenario())

    assert old_task.cancelled()
    assert gateway.sessions[sid].state == SessionState.candidate


def test_stale_asr_command_cannot_confirm_a_new_round(monkeypatch) -> None:
    import threading

    sid = "stale-asr-command"
    gateway.sessions[sid] = DecisionSession(session_id=sid, state=SessionState.listening)
    asr_started = threading.Event()
    release_asr = threading.Event()

    def delayed_asr(_pcm: bytes, _rate: int) -> str:
        asr_started.set()
        release_asr.wait(timeout=5)
        return "确认"

    class VoiceRequest:
        async def body(self) -> bytes:
            return b"\0" * 8000

    async def scenario():
        monkeypatch.setattr(gateway, "_asr", delayed_asr)
        old_voice = asyncio.create_task(gateway.voice_input(VoiceRequest(), session_id=sid))
        while not asr_started.is_set():
            await asyncio.sleep(0.001)
        await gateway.submit_input(gateway.InputPayload(
            session_id=sid,
            hard_constraints=HardConstraints(budget_max=80, eat_by_minutes=60),
        ))
        release_asr.set()
        result = await old_voice
        return result

    result = asyncio.run(scenario())

    assert result["ignored"] is True
    assert gateway.sessions[sid].state == SessionState.candidate


def test_feedback_updates_session_state_to_idle() -> None:
    sid = "feedback-idle"
    gateway.sessions[sid] = DecisionSession(session_id=sid, state=SessionState.done)
    client = TestClient(gateway.app)

    response = client.post("/v1/feedback", json={
        "session_id": sid,
        "would_repeat": True,
    })

    assert response.status_code == 200
    assert gateway.sessions[sid].state == SessionState.idle


def test_stale_feedback_cannot_interrupt_a_new_round() -> None:
    sid = "stale-feedback"
    gateway.sessions[sid] = DecisionSession(session_id=sid, state=SessionState.candidate)
    client = TestClient(gateway.app)

    response = client.post("/v1/feedback", json={
        "session_id": sid,
        "would_repeat": True,
    })

    assert response.status_code == 200
    assert response.json()["ignored"] is True
    assert gateway.sessions[sid].state == SessionState.candidate


def test_old_done_timer_cannot_close_a_new_round() -> None:
    sid = "done-generation"
    gateway.sessions[sid] = DecisionSession(session_id=sid, state=SessionState.done)
    gateway.done_generations[sid] = 2

    asyncio.run(gateway.auto_idle_after_done(sid, delay_s=0, generation=1))
    assert gateway.sessions[sid].state == SessionState.done

    asyncio.run(gateway.auto_idle_after_done(sid, delay_s=0, generation=2))
    assert gateway.sessions[sid].state == SessionState.idle


def test_new_done_generation_is_set_before_done_push() -> None:
    sid = "done-push-race"
    candidate = gateway.load_candidates()[0]
    session = DecisionSession(
        session_id=sid,
        state=SessionState.confirming,
        candidates=[candidate],
    )
    gateway.sessions[sid] = session
    gateway.done_generations[sid] = 1

    class OldTimerAtPush:
        async def send_text(self, _text: str) -> None:
            if (session.state == SessionState.done
                    and gateway.done_generations[sid] == 1):
                session.state = SessionState.idle

    socket = OldTimerAtPush()
    gateway.device_sockets.append(socket)
    try:
        asyncio.run(gateway.confirm({"session_id": sid}))
    finally:
        gateway.device_sockets.remove(socket)

    assert session.state == SessionState.done
    assert gateway.done_generations[sid] == 2


def test_negative_food_phrase_is_not_treated_as_a_craving() -> None:
    assert ingredient_preferences("不想吃鱼，想吃牛肉") == ["牛肉"]


def test_common_food_scope_and_negative_food_are_enforced() -> None:
    salad = asyncio.run(gateway.run_decision(
        DecisionSession(session_id="salad", raw_input="今天想吃轻食"),
        gateway.load_candidates(),
        model=None,
    ))
    assert salad.candidates
    assert all(
        "轻食" in " ".join([
            candidate.item, candidate.restaurant, candidate.cuisine,
            *candidate.ingredients, *candidate.tags,
        ])
        for candidate in salad.candidates
    )

    _goal, hard, _soft, _context = rule_structure("不想吃鱼")
    assert "鱼" in hard.hated
