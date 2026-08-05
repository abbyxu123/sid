"""Device connection regressions shared by the gateway and ESP32 firmware."""

import asyncio
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient

from core.decision_schema import AgentScore, DecisionMode, FinalChoice, SessionState
from services.device_gateway import main as gateway


FIRMWARE = (
    Path(__file__).resolve().parents[1]
    / "firmware/esp32_amoled18/noon_cat_amoled18/noon_cat_amoled18.ino"
)


class DisconnectedWebSocket:
    """Small fake for Starlette's runtime error after a peer disconnects."""

    def __init__(self) -> None:
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, _text: str) -> None:
        return None

    async def receive_text(self) -> str:
        raise RuntimeError("WebSocket is not connected. Need to call accept first.")


def test_device_stream_cleans_up_runtime_disconnect() -> None:
    ws = DisconnectedWebSocket()

    asyncio.run(gateway.device_stream(ws))

    assert ws.accepted
    assert ws not in gateway.device_sockets


def test_firmware_disconnect_keeps_websocket_client_initialized() -> None:
    source = FIRMWARE.read_text(encoding="utf-8")
    start = source.index("if (type == WStype_DISCONNECTED)")
    end = source.index("if (type != WStype_TEXT)", start)
    disconnect_handler = source[start:end]

    assert "wsStarted = false;" not in disconnect_handler
    assert "ws.setReconnectInterval(3000);" in source


def test_firmware_uses_board_reference_microphone_gain() -> None:
    source = FIRMWARE.read_text(encoding="utf-8")

    assert "es8311_microphone_gain_set(h, ES8311_MIC_GAIN_18DB)" in source
    assert "es8311_microphone_gain_set(h, ES8311_MIC_GAIN_36DB)" not in source


def test_firmware_standby_hold_can_continue_into_recording() -> None:
    source = FIRMWARE.read_text(encoding="utf-8")

    assert "wokeWithKey" in source
    assert "saverSwallow" not in source
    assert "if (wokeWithKey)" in source


def test_voice_rejects_clipped_flatline_before_asr(monkeypatch) -> None:
    monkeypatch.setattr(gateway, "_asr", lambda _pcm, _rate: "想吃鱼")
    pcm = int(30840).to_bytes(2, "little", signed=True) * 5000
    client = TestClient(gateway.app)
    sid = client.post("/v1/session", json={"device_id": "flatline"}).json()["session_id"]

    response = client.post(
        f"/v1/voice?session_id={sid}&rate=16000",
        content=pcm,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "audio signal invalid"


def _finish_session(session, *, direct: bool = False):
    candidate = gateway.load_candidates()[0]
    session.state = SessionState.candidate
    session.candidates = [candidate]
    session.final_choice = FinalChoice(candidate_id=candidate.id, confidence=0.8)
    if direct:
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


def test_model_disabled_text_still_uses_rule_structure(monkeypatch) -> None:
    observed = {}

    async def fake_run(session, *_args, **_kwargs):
        observed["budget"] = session.hard_constraints.budget_max
        observed["minutes"] = session.hard_constraints.eat_by_minutes
        return _finish_session(session)

    monkeypatch.setattr(gateway, "USE_MODEL", False)
    monkeypatch.setattr(gateway, "run_decision", fake_run)
    client = TestClient(gateway.app)
    sid = client.post("/v1/session", json={"device_id": "rules-offline"}).json()["session_id"]

    response = client.post(
        "/v1/input",
        json={"session_id": sid, "text": "想吃辣的，四十元以内，半小时内"},
    )

    assert response.status_code == 200
    assert "followup" not in response.json()
    assert observed == {"budget": 40, "minutes": 30}


def test_offline_followup_answer_continues_to_candidate(monkeypatch) -> None:
    observed = {}

    async def fake_run(session, *_args, **_kwargs):
        observed["budget"] = session.hard_constraints.budget_max
        observed["channel"] = session.context.channel.value
        return _finish_session(session)

    monkeypatch.setattr(gateway, "USE_MODEL", False)
    monkeypatch.setattr(gateway, "run_decision", fake_run)
    client = TestClient(gateway.app)
    sid = client.post("/v1/session", json={"device_id": "offline-followup"}).json()["session_id"]

    first = client.post("/v1/input", json={"session_id": sid, "text": "外卖"})
    second = client.post("/v1/input", json={"session_id": sid, "text": "40块钱"})

    assert first.status_code == 200
    assert first.json()["followup"] == "预算多少喵？多久要吃上？"
    assert second.status_code == 200
    assert "followup" not in second.json()
    assert second.json()["state"] == "candidate"
    assert observed == {"budget": 40, "channel": "delivery"}


def test_voice_treats_delivery_as_food_intent(monkeypatch) -> None:
    captured = {}

    async def fake_submit(payload):
        captured["text"] = payload.text
        return {"state": "candidate"}

    monkeypatch.setattr(gateway, "_asr", lambda _pcm, _rate: "外卖")
    monkeypatch.setattr(gateway, "submit_input", fake_submit)
    pcm = b"".join(int((i % 2000) - 1000).to_bytes(2, "little", signed=True) for i in range(5000))
    client = TestClient(gateway.app)
    sid = client.post("/v1/session", json={"device_id": "delivery-voice"}).json()["session_id"]

    response = client.post(
        f"/v1/voice?session_id={sid}&rate=16000",
        content=pcm,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 200
    assert response.json().get("chitchat") is not True
    assert captured == {"text": "外卖"}


def test_direct_product_flow_has_no_scripted_replay_delay(monkeypatch) -> None:
    async def fake_run(session, *_args, **_kwargs):
        return _finish_session(session, direct=True)

    monkeypatch.setattr(gateway, "run_decision", fake_run)
    client = TestClient(gateway.app)
    sid = client.post("/v1/session", json={"device_id": "fast-direct"}).json()["session_id"]

    started = perf_counter()
    response = client.post(
        "/v1/input",
        json={
            "session_id": sid,
            "hard_constraints": {"budget_max": 100, "eat_by_minutes": 60},
        },
    )

    assert response.status_code == 200
    assert perf_counter() - started < 0.5


def test_default_asr_model_matches_working_baseline() -> None:
    assert gateway.ASR_MODEL == "small"
