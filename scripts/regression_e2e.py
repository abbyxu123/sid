"""连续决策回归：模拟 N 轮真实使用，覆盖 直推/文本抽取/探索/语音/确认/反馈。

Gate 4 要求"10 次连续完整彩排不翻车"——本脚本就是它的自动化版。
用法：
    .venv/bin/python scripts/regression_e2e.py [轮数=10] [--gw http://127.0.0.1:8090]
判定：
    - 每轮必须走到 candidate 且 candidates[0] == final_choice
    - 确认后必须 done 且给出下单深链（url + app_url）
    - 任何一轮异常即整体 FAIL（退出码 1）
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request

GW = "http://127.0.0.1:8090"
if "--gw" in sys.argv:
    GW = sys.argv[sys.argv.index("--gw") + 1]
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 10


def call(path: str, body: dict | bytes | None = None, method: str = "POST",
         ctype: str = "application/json", timeout: int = 180):
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    req = urllib.request.Request(GW + path, data=data, method=method,
                                 headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# 轮换场景：快车道（秒级），议事会长轮用 --council 单独加一轮（Step 一轮 ~3 分钟）
SCENARIOS = [
    ("direct-constraints", lambda: {"hard_constraints": {"budget_max": 40, "eat_by_minutes": 30},
                                    "soft_preferences": {"spicy": "medium"}}),
    ("text-kitten", lambda: {"text": "想吃点辣的，四十以内，半小时内，不要面食"}),
    ("direct-mild", lambda: {"hard_constraints": {"budget_max": 35, "eat_by_minutes": 45},
                             "soft_preferences": {"spicy": "mild"}}),
    ("explore-bold", lambda: {"soft_preferences": {"novelty": "bold"}}),
    ("dine-in", lambda: {"hard_constraints": {"budget_max": 60},
                         "context": {"channel": "dine_in"}}),   # 到店 → 高德导航深链
]
if "--council" in sys.argv:   # 紧预算触发冲突路由 → 真 Step 议事会
    SCENARIOS.append(("council-step", lambda: {"hard_constraints": {"budget_max": 26, "eat_by_minutes": 60},
                                               "soft_preferences": {"spicy": "medium"}}))

fails, lat_decide, lat_confirm = [], [], []
try:
    pcm = open("/tmp/voice_test.pcm", "rb").read()
except FileNotFoundError:
    pcm = None

for i in range(ROUNDS):
    name, mk = SCENARIOS[i % len(SCENARIOS)]
    tag = f"[{i+1}/{ROUNDS}] {name}"
    try:
        sid = call("/v1/session", {"device_id": f"regress-{i}"})["session_id"]
        t0 = time.time()
        if pcm is not None and i % 5 == 1 and name != "council-step":  # 每 5 轮混一次语音；不顶掉议事会场景
            tag += "+voice"
            d = call(f"/v1/voice?session_id={sid}&rate=16000", pcm,
                     ctype="application/octet-stream", timeout=240)
        else:
            body = {"session_id": sid, **mk()}
            d = call("/v1/input", body, timeout=240)
        lat_decide.append(time.time() - t0)
        assert d.get("state") == "candidate", f"state={d.get('state')}"
        fc = d.get("final_choice") or {}
        cands = d.get("candidates") or []
        assert cands and fc.get("candidate_id") == cands[0]["id"], "candidates[0] != final"
        # 换一个 → 确认 → 出单 → 反馈
        now_ms = int(time.time() * 1000)   # 幂等键必须全局唯一，固定值会被网关 409
        call("/v1/device/event", {"device_id": f"regress-{i}", "session_id": sid,
                                  "event": "left_ear", "timestamp": now_ms})
        call("/v1/device/event", {"device_id": f"regress-{i}", "session_id": sid,
                                  "event": "right_ear", "timestamp": now_ms + 1})
        t1 = time.time()
        c = call("/v1/confirm", {"session_id": sid})
        lat_confirm.append(time.time() - t1)
        assert c.get("ok") and c.get("url"), f"confirm={c}"
        assert (c.get("app_url", "").startswith("taobao://")
                or c.get("action") == "map_deeplink"), f"app_url={c.get('app_url')}"
        s = call(f"/v1/session/{sid}", method="GET", body=None)
        assert s.get("state") == "done", f"post-confirm state={s.get('state')}"
        call("/v1/feedback", {"session_id": sid, "rating": 4, "would_repeat": True})
        print(f"{tag}  ok  decide={lat_decide[-1]:.1f}s confirm={lat_confirm[-1]:.1f}s "
              f"pick={fc.get('candidate_id')}")
    except Exception as e:  # noqa: BLE001 —— 回归脚本要抓一切
        fails.append(f"{tag}: {type(e).__name__}: {e}")
        print(f"{tag}  FAIL  {e}")

print("\n===== 回归结果 =====")
print(f"通过 {ROUNDS - len(fails)}/{ROUNDS}")
if lat_decide:
    print(f"决策延迟  p50={statistics.median(lat_decide):.1f}s "
          f"max={max(lat_decide):.1f}s（含议事会剧场回放）")
if lat_confirm:
    print(f"确认延迟  p50={statistics.median(lat_confirm):.1f}s")
for f in fails:
    print("FAIL:", f)
sys.exit(1 if fails else 0)
