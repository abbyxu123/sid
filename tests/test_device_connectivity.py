"""Device connection regressions shared by the gateway and ESP32 firmware."""

import asyncio
from pathlib import Path

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
