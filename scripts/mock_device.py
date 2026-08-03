"""模拟方形开发板：WS 收状态帧 + 命令行发耳朵事件。固件的参考实现/联调对练工具。

  pip install websockets httpx
  python scripts/mock_device.py --gateway http://<GATEWAY_LAN_IP>:8090
交互命令：l=左耳换一个  r=右耳确认  b=双耳开会  c=取消  t <文字>=发需求  q=退出
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx
import websockets

DEVICE_ID = "cat-square-mock"


async def listen_ws(ws_url: str):
    """固件参考：断线自动重连；每帧打印 state/display/haptic；任意文本可当心跳。"""
    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                print(f"[WS] connected {ws_url}")
                async for msg in ws:
                    f = json.loads(msg)
                    print(f"[WS] state={f['state']:11s} | {f['display']['title']} "
                          f"{f['display']['subtitle']} | haptic={f['haptic']} audio={f['audio']}")
        except Exception as e:
            print(f"[WS] disconnected ({type(e).__name__}), retry in 3s")
            await asyncio.sleep(3)


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gateway", default="http://127.0.0.1:8090")
    args = p.parse_args()
    ws_url = args.gateway.replace("http", "ws") + "/v1/device/stream"
    asyncio.create_task(listen_ws(ws_url))
    await asyncio.sleep(1)

    async with httpx.AsyncClient(base_url=args.gateway, timeout=180) as client:
        sid = (await client.post("/v1/session", json={"device_id": DEVICE_ID})).json()["session_id"]
        print(f"[HTTP] session {sid}\n命令: l/r/b/c/t <文字>/q")
        loop = asyncio.get_event_loop()
        while True:
            line = (await loop.run_in_executor(None, sys.stdin.readline)).strip()
            if not line:
                continue
            if line == "q":
                return
            if line.startswith("t "):
                r = await client.post("/v1/input", json={"session_id": sid, "text": line[2:]})
                d = r.json()
                fc = d.get("final_choice") or {}
                print(f"[HTTP] {d['state']} mode={d.get('decision_mode')} final={fc.get('candidate_id')}")
                continue
            event = {"l": "left_ear", "r": "right_ear", "b": "both_ears", "c": "cancel"}.get(line)
            if not event:
                print("未知命令")
                continue
            r = await client.post("/v1/device/event", json={
                "device_id": DEVICE_ID, "session_id": sid, "event": event,
                "timestamp": int(time.time() * 1000), "firmware_version": "mock-0.1"})
            print(f"[HTTP] event {event} -> {r.json()}")
            if event == "right_ear" and r.json().get("state") == "confirming":
                r2 = await client.post("/v1/confirm", json={"session_id": sid})
                print(f"[HTTP] confirm -> {r2.json()}")


if __name__ == "__main__":
    asyncio.run(main())
