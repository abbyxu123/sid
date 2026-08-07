"""Device Gateway：硬件唯一依赖的服务。FastAPI + WebSocket。

固件只与本服务通信，不直接依赖模型服务；换模型不需要改固件。
今天先实现规则降级闭环（无模型可跑通）；7/17 注入 Step 3.7 client。

运行：uvicorn services.device_gateway.main:app --host 0.0.0.0 --port 8090
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from core.auditor import deterministic_audit
from core.decision_schema import (
    Candidate,
    Channel,
    Context,
    DecisionSession,
    DeviceDisplay,
    DeviceEvent,
    DeviceEventType,
    DeviceStateFrame,
    HardConstraints,
    SessionState,
    SoftPreferences,
)
from core.memory import Ledger
from core.model_client import ModelError, ModelRouter
from core.orchestrator import run_decision
from services.tool_gateway.adapters import build_action

DEMO_DATA = Path(__file__).resolve().parents[2] / "skills/food/demo_data/restaurants.json"

app = FastAPI(title="NOON NOON Decision OS — Device Gateway", version="0.1.0")
from fastapi.middleware.cors import CORSMiddleware
_ORIGINS = [o for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o]
app.add_middleware(CORSMiddleware, allow_origins=_ORIGINS, allow_methods=["*"], allow_headers=["*"])
# 演示现场把 CORS_ORIGINS 设为前端真实 origin（deployment.md 检查清单）；* 仅限开发
ledger = Ledger()
router = ModelRouter()
USE_MODEL = os.environ.get("USE_MODEL", "1") == "1"
sessions: dict[str, DecisionSession] = {}
device_sockets: list[WebSocket] = []
seen_events: dict[str, float] = {}  # 幂等键 device_id:event:timestamp → 收到时间
active_session_id: str = ""         # WS 重连时重推该会话的当前帧
session_pools: dict[str, list[Candidate]] = {}  # 本轮候选池（含拍照菜品），重开会必须沿用
council_lines: dict[str, tuple[str, str]] = {}  # 议事会实时台词 sid → (猫名, 台词)
asked_once: dict[str, bool] = {}    # 缺字段追问: 每会话只问一次
pending_ask: dict[str, bool] = {}   # 追问中: 下一句并入而非覆盖约束
done_generations: dict[str, int] = {}  # 每轮 done 的序号，隔离旧二维码定时任务
decision_tasks: dict[str, object] = {}  # 每会话最多一个后台语音/议事会任务
voice_generations: dict[str, int] = {}  # 丢弃被新输入/操作取代的旧 ASR 结果
DONE_AUTO_IDLE_SECONDS = 30
CAT_NAMES = {"taste": "口味猫", "budget": "预算猫", "time": "时间猫",
             "memory": "记忆猫", "novelty": "探索猫"}
# 台词字符必须在板载字库内（/tmp/charset.txt 校验过），否则显示为口
CAT_TAIL = {"taste": "正合口味喵", "budget": "不超预算喵", "time": "不用久等喵",
            "memory": "最近没吃过喵", "novelty": "换个花样喵"}


# 板载字库字符集：帧文本发给板子前过滤，字库外字符直接显示为口
_BOARD_CHARS = set((Path(__file__).parent / "board_charset.txt").read_text(encoding="utf-8"))


def board_text(s: str, limit: int = 30) -> str:
    return "".join(c for c in s if c in _BOARD_CHARS)[:limit]


def cat_line(session: DecisionSession, agent: str) -> tuple[str, str]:
    """某只猫对首选候选的一句话台词 → (猫名, 台词)。

    规则评分的证据短（"鲁菜/medium"）→ 接性格彩尾；
    LLM 证据是完整句子且可能是负面评价 → 只加"喵"，彩尾会自相矛盾。
    """
    name = CAT_NAMES.get(agent, agent)
    fc = session.final_choice.candidate_id if session.final_choice else None
    for sc in session.agent_scores.get(agent, []):
        if fc is None or sc.candidate_id == fc:
            if sc.evidence:
                ev = sc.evidence[0]
                if ev.endswith("喵"):
                    return name, ev            # 自带喵的完整台词（记忆维度）直接用
                if len(ev) > 12:
                    return name, f"{ev}，喵"
                return name, f"{ev}，{CAT_TAIL.get(agent, '评完了喵')}"
            break
    return name, CAT_TAIL.get(agent, "评完了喵")


def merge_constraints(session: DecisionSession, hard, soft):
    """追问后的补充话术并入: 新值优先, 缺的用上一轮的; 安全清单取并集。"""
    oh, os_ = session.hard_constraints, session.soft_preferences
    hard.allergens = list(dict.fromkeys([*oh.allergens, *hard.allergens]))
    hard.diet_taboos = list(dict.fromkeys([*oh.diet_taboos, *hard.diet_taboos]))
    hard.hated = list(dict.fromkeys([*oh.hated, *hard.hated]))
    if hard.budget_max is None:
        hard.budget_max = oh.budget_max
    if hard.eat_by_minutes is None:
        hard.eat_by_minutes = oh.eat_by_minutes
    if hard.max_distance_m is None:
        hard.max_distance_m = oh.max_distance_m
    if soft.spicy is None:
        soft.spicy = os_.spicy
    if not soft.cuisines:
        soft.cuisines = os_.cuisines
    if soft.novelty is None:
        soft.novelty = os_.novelty
    return hard, soft


def load_candidates() -> list[Candidate]:
    return [Candidate(**c) for c in json.loads(DEMO_DATA.read_text(encoding="utf-8"))]


async def push_state(session: DecisionSession) -> None:
    """向所有在线设备广播当前状态帧。"""
    frame = build_frame(session)
    dead = []
    for ws in device_sockets:
        try:
            await ws.send_text(frame.model_dump_json())
        except Exception:
            dead.append(ws)
    for ws in dead:
        device_sockets.remove(ws)


async def auto_idle_after_done(
    session_id: str, delay_s: float = DONE_AUTO_IDLE_SECONDS,
    generation: int | None = None,
) -> None:
    """二维码页最多停留 30 秒；用户已操作到别的状态时不覆盖。"""
    import asyncio

    expected_generation = (
        done_generations.get(session_id, 0) if generation is None else generation
    )
    await asyncio.sleep(delay_s)
    session = sessions.get(session_id)
    if (not session or session.state != SessionState.done
            or done_generations.get(session_id, 0) != expected_generation):
        return
    session.state = SessionState.idle
    await push_state(session)


def build_frame(session: DecisionSession) -> DeviceStateFrame:
    frame = DeviceStateFrame(state=session.state)
    if session.state == SessionState.council:
        entry = council_lines.get(session.session_id)
        if entry:
            name, line = entry
            frame.display = DeviceDisplay(title=board_text(name, 12),
                                          subtitle=board_text(line, 42))
        else:
            frame.display = DeviceDisplay(title="议事会", subtitle="四只猫开会中...")
    if session.state == SessionState.candidate and session.final_choice:
        shown = session.candidates[session.cursor % len(session.candidates)]
        lucky = session.decision_mode and session.decision_mode.value == "explore"
        frame.display = DeviceDisplay(
            title="幸运食物" if lucky else "今日推荐",   # 摇一摇=幸运食物（字库已加 幸 字）
            subtitle=board_text(f"{shown.item} ¥{shown.price_total:.0f} / {shown.eta_minutes}分钟", 42),
        )
        frame.candidate = {"id": shown.id, "confidence": session.final_choice.confidence}
        frame.haptic = "tap"
    elif session.state == SessionState.structuring:
        # 空标题帧会把板子屏幕刷白（板端直接显示 title）——给足文案
        frame.display = DeviceDisplay(title="猫猫在想", subtitle="让我想想吃什么好")
    elif session.state in (SessionState.listening, SessionState.idle):
        frame.display = DeviceDisplay(title="想吃什么？",   # 46px 大字一行最多 10 个字
                                      subtitle="按住说话 · 短按开会 · 摇一摇")
    elif session.state == SessionState.confirming:
        shown = session.candidates[session.cursor % len(session.candidates)] \
            if session.candidates else None
        frame.display = DeviceDisplay(
            title="就吃这个？",
            subtitle=board_text(f"{shown.item} · 再按一次确认" if shown else "再按一次确认", 42))
        frame.haptic = "double"
        frame.audio = "meow_confirm"
    elif session.state == SessionState.error:
        frame.display = DeviceDisplay(title="出错了", subtitle="再按住说一次 · 长按B重开")
        frame.audio = "meow_error"
    return frame


# ---- API（契约见 docs/api_contract.md） ----

class SessionCreate(BaseModel):
    device_id: str = "cat-square-01"


class InputPayload(BaseModel):
    session_id: str
    text: str = ""
    menu_image_b64: str = ""            # 菜单照片（可选，Step mmproj 解析）
    menu_image_mime: str = "image/png"
    hard_constraints: HardConstraints | None = None
    soft_preferences: SoftPreferences | None = None
    context: Context | None = None


_SPICY_HINTS = {"麻辣": "hot", "香辣": "hot", "特辣": "hot", "水煮": "hot",
                "中辣": "medium", "辣": "medium", "酸辣": "mild", "宫保": "mild"}
_INGREDIENT_HINTS = ["鱼", "牛肉", "猪", "鸡", "虾", "豆腐", "花生", "面", "米饭", "蛋"]
_STAPLE_HINTS = ["米饭", "配送费", "餐具", "纸巾"]


def menu_to_candidates(menu: dict) -> list[Candidate]:
    """菜单解析结果 → 候选。菜名启发式补辣度/食材/主食标记——拍照菜品没有结构化
    元数据，不补的话口味分全中性，评分器会把米饭当最优解。"""
    fee = menu.get("delivery_fee") or 0
    out = []
    for i, item in enumerate(menu.get("items", [])):
        try:
            price = float(item["price"])
        except (KeyError, TypeError, ValueError):
            continue
        name = str(item.get("name") or f"菜品{i}")
        if name in _STAPLE_HINTS:
            continue  # 主食/杂费不参与推荐（精确匹配——"盖浇米饭"这类主菜不能误杀）
        spicy = next((v for k, v in _SPICY_HINTS.items() if k in name), "none")
        ingredients = [k for k in _INGREDIENT_HINTS if k in name]
        tags = ["menu_photo"] + (["面食"] if "面" in name else [])
        out.append(Candidate(
            id=f"menu_{i:02d}", restaurant=str(menu.get("restaurant") or "拍照餐厅"),
            item=name, price_total=price + float(fee),
            eta_minutes=15, cuisine=str(menu.get("restaurant") or ""),
            spicy_level=spicy, ingredients=ingredients, tags=tags, channel=Channel.dine_in,
        ))
    return out


from fastapi.staticfiles import StaticFiles
app.mount("/assets", StaticFiles(directory=Path(__file__).parent / "assets"), name="assets")


@app.get("/console")
async def console():
    from fastapi.responses import FileResponse
    # no-cache：手机浏览器缓存旧版页面会带着已修复的 bug 上演示现场
    return FileResponse(Path(__file__).parent / "console.html",
                        headers={"Cache-Control": "no-cache"})


presence = {"present": None, "ts": 0.0}   # mmWave 人体存在（可选传感器, CatTV P2 预留）


@app.post("/v1/sensor/presence")
async def sensor_presence(body: dict):
    """mmWave/人体存在传感器上报: {present: bool}。目前只记录, 供屏保/饿了吗联动。"""
    import time as _t
    presence["present"] = bool(body.get("present"))
    presence["ts"] = _t.time()
    return {"ok": True}


@app.api_route("/v1/hungry", methods=["GET", "POST"])
async def hungry():
    """「我饿了吗」彩蛋: 基于手账的上一顿时间, 记忆猫给个俏皮判断。"""
    import time as _t
    rows = ledger.journal(2)
    last = next((r for r in rows if r.get("confirmed")), rows[0] if rows else None)
    name_of = {c.id: c.item for c in load_candidates()}
    if not last:
        title, sub_ = "我饿了吗？", "还没记录过 · 先来一顿喵"
    else:
        item = name_of.get(last["candidate_id"], "上一顿")
        hrs = (_t.time() - last["ts"]) / 3600
        if hrs < 2:
            title, sub_ = "饱着喵！", f"{int(hrs*60)}分钟前刚吃过{item}"
        elif hrs < 4:
            title, sub_ = "有点饿了吧？", f"上一顿是{item} · 来一顿？"
        else:
            title, sub_ = "早就饿了吧！", "按住说话 来一顿喵"
    frame = DeviceStateFrame(state=SessionState.idle,
                             display=DeviceDisplay(title=board_text(title, 12),
                                                   subtitle=board_text(sub_, 42)))
    for w in list(device_sockets):
        try:
            await w.send_text(frame.model_dump_json())
        except Exception:
            pass
    ledger.append("hungry", "input", {"event": "hungry_check", "title": title})
    return {"title": title, "subtitle": sub_}


PROFILE_PATH = Path("data/profile.json")


def load_profile() -> dict:
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


@app.get("/v1/profile")
async def get_profile():
    """用户长期档案：过敏/忌口/默认预算——跨会话记住（CatTV MVP: UserProfile P1）。"""
    return load_profile()


@app.put("/v1/profile")
async def put_profile(body: dict):
    allowed = {"allergens", "diet_taboos", "hated", "budget_max",
               "eat_by_minutes", "max_distance_m", "spicy"}
    prof = load_profile()
    prof.update({k: v for k, v in body.items() if k in allowed})
    PROFILE_PATH.write_text(json.dumps(prof, ensure_ascii=False, indent=1), encoding="utf-8")
    ledger.append("profile", "input", {"event": "profile_update", "profile": prof})
    return {"ok": True, "profile": prof}


@app.get("/v1/journal")
async def journal(days: int = 30, group: str = ""):
    """猫爪手账：吃过什么、评价如何、有没有复购意愿——「越用越懂你」的证据。"""
    name_of = {c.id: c for c in load_candidates()}
    items = []
    for row in ledger.journal(days):
        c = name_of.get(row["candidate_id"])
        items.append({**row,
                      "item": c.item if c else row["candidate_id"],
                      "restaurant": c.restaurant if c else "拍照菜单",
                      "price": c.price_total if c else None,
                      "cuisine": c.cuisine if c else ""})
    seen, favs = set(), []
    for i in items:
        if i["would_repeat"] and i["candidate_id"] not in seen:
            seen.add(i["candidate_id"])
            favs.append(f'{i["item"]}（{i["restaurant"]}）')
    out = {"items": items, "total": len(items),
           "confirmed": sum(1 for i in items if i["confirmed"]),
           "repeat_favorites": favs[:3]}
    if group == "day":                     # 小屏分组视图（CatTV UX 流程用）
        import time as _t
        days: dict[str, list] = {}
        for i in items:
            d = _t.strftime("%m-%d", _t.localtime(i["ts"]))
            days.setdefault(d, []).append(i)
        out["days"] = [{"date": d, "items": v} for d, v in days.items()]
    return out


@app.get("/sim")
async def board_sim():
    """480×480 板子模拟器：与真板收同一路 WS 帧，前端不碰硬件即可调 UI。"""
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).parent / "board_sim.html",
                        headers={"Cache-Control": "no-cache"})


@app.get("/health")
async def health():
    step_ok = await router.step.healthy() if USE_MODEL else False
    kitten_ok = bool(router.kitten) and await router.kitten.healthy()
    return {
        "gateway": "ok",
        "sessions": len(sessions),
        "devices_online": len(device_sockets),
        "model": {"step": "ok" if step_ok else "down",
                  "kitten": "ok" if kitten_ok else ("disabled" if not router.kitten else "down")},
    }


@app.post("/v1/session")
async def create_session(body: SessionCreate):
    global active_session_id
    sid = f"sess_{uuid.uuid4().hex[:12]}"
    sessions[sid] = DecisionSession(
        session_id=sid,
        state=SessionState.idle,
        context=Context(channel=Channel.delivery),
    )
    active_session_id = sid
    ledger.append(sid, "input", {"event": "session_created", "device_id": body.device_id})
    _prune_sessions()
    return {"session_id": sid}


MAX_SESSIONS = 200


def _prune_sessions() -> None:
    """演示长跑保护：会话/池子字典有界，淘汰最旧的（Ledger 里永久记录不受影响）。"""
    while len(sessions) > MAX_SESSIONS:
        oldest = next(iter(sessions))
        cancel_background_decision(oldest)
        sessions.pop(oldest, None)
        session_pools.pop(oldest, None)
        done_generations.pop(oldest, None)
        voice_generations.pop(oldest, None)


def get_or_revive(sid: str) -> DecisionSession:
    """网关重启后板子/二维码持有的旧会话自动复活——会话 id 是客户端的稳定锚点。"""
    global active_session_id
    if sid not in sessions:
        sessions[sid] = DecisionSession(
            session_id=sid,
            state=SessionState.idle,
            context=Context(channel=Channel.delivery),
        )
        active_session_id = sid
        ledger.append(sid, "input", {"event": "session_revived"})
        _prune_sessions()
    return sessions[sid]


@app.post("/v1/input")
async def submit_input(body: InputPayload):
    advance_voice_generation(body.session_id)
    cancel_background_decision(body.session_id)
    session = get_or_revive(body.session_id)
    previous_context = session.context
    if body.text:
        if pending_ask.get(session.session_id) and session.raw_input:
            session.raw_input = f"{session.raw_input} {body.text}"
        else:
            session.raw_input = body.text
    if body.hard_constraints:
        session.hard_constraints = body.hard_constraints
    if body.soft_preferences:
        session.soft_preferences = body.soft_preferences
    if body.context:
        session.context = body.context
    session.state = SessionState.structuring
    ledger.append(session.session_id, "input", body.model_dump())
    # text → 模型结构化（kitten 优先，Step 兜底，都挂则用手工字段/默认值走规则）
    if USE_MODEL and body.text and body.hard_constraints is None:
        try:
            goal, hard, soft, ctx = await router.structure_input(body.text)
            if pending_ask.pop(session.session_id, False):
                hard, soft = merge_constraints(session, hard, soft)
            session.goal, session.hard_constraints, session.soft_preferences = goal, hard, soft
            if body.context is None:
                session.context = ctx
                if ctx.channel == Channel.any and previous_context.channel != Channel.any:
                    session.context.channel = previous_context.channel
            ledger.append(session.session_id, "structured", {
                "hard": hard.model_dump(), "soft": soft.model_dump(), "ctx": ctx.model_dump()})
        except ModelError as e:
            # 双模型都失联 → 规则关键词解析兜底（其内部安全线：过敏解析不出会抛错）。
            # 仍失败才进 error——绝不能带着丢失的过敏信息继续推荐。
            try:
                from skills.food.agents.extraction import rule_structure
                goal, hard, soft, ctx = rule_structure(body.text)
                if pending_ask.pop(session.session_id, False):
                    hard, soft = merge_constraints(session, hard, soft)
                session.goal, session.hard_constraints, session.soft_preferences = goal, hard, soft
                if body.context is None:
                    session.context = ctx
                    if ctx.channel == Channel.any and previous_context.channel != Channel.any:
                        session.context.channel = previous_context.channel
                session.risk_flags.append(f"structure_degraded: 规则解析兜底（{e}）")
                ledger.append(session.session_id, "structured", {
                    "hard": hard.model_dump(), "soft": soft.model_dump(),
                    "ctx": ctx.model_dump(), "degraded": True})
            except ValueError as e2:
                session.risk_flags.append(f"structure_failed: {e}; rule: {e2}")
                session.state = SessionState.error
                ledger.append(session.session_id, "error",
                              {"stage": "structure", "reason": f"{e}; rule: {e2}"})
                await push_state(session)
                return session.model_dump()
    elif body.text and body.hard_constraints is None:
        try:
            from skills.food.agents.extraction import rule_structure

            goal, hard, soft, ctx = rule_structure(body.text)
            if pending_ask.pop(session.session_id, False):
                hard, soft = merge_constraints(session, hard, soft)
            session.goal, session.hard_constraints, session.soft_preferences = goal, hard, soft
            if body.context is None:
                session.context = ctx
                if ctx.channel == Channel.any and previous_context.channel != Channel.any:
                    session.context.channel = previous_context.channel
            ledger.append(session.session_id, "structured", {
                "hard": hard.model_dump(), "soft": soft.model_dump(),
                "ctx": ctx.model_dump(), "rules_only": True})
        except ValueError as e:
            session.risk_flags.append(f"structure_failed: rule: {e}")
            session.state = SessionState.error
            ledger.append(session.session_id, "error",
                          {"stage": "structure", "reason": f"rule: {e}"})
            await push_state(session)
            return session.model_dump()
    prof = load_profile()
    if prof:
        h = session.hard_constraints
        h.allergens = list(dict.fromkeys([*prof.get("allergens", []), *h.allergens]))
        h.diet_taboos = list(dict.fromkeys([*prof.get("diet_taboos", []), *h.diet_taboos]))
        h.hated = list(dict.fromkeys([*prof.get("hated", []), *h.hated]))
        if h.budget_max is None:
            h.budget_max = prof.get("budget_max")
        if h.eat_by_minutes is None:
            h.eat_by_minutes = prof.get("eat_by_minutes")
        if h.max_distance_m is None:
            h.max_distance_m = prof.get("max_distance_m")
        if session.soft_preferences.spicy is None and prof.get("spicy"):
            session.soft_preferences.spicy = prof["spicy"]
    # 缺字段追问(CatTV P1): 口述里预算和时间都没给(档案也没兜住) → 猫追问一句
    if (body.text and body.hard_constraints is None
            and session.hard_constraints.budget_max is None
            and session.hard_constraints.eat_by_minutes is None
            and not asked_once.get(session.session_id)):
        asked_once[session.session_id] = True
        pending_ask[session.session_id] = True
        session.state = SessionState.listening
        ledger.append(session.session_id, "input", {"event": "followup_asked"})
        frame = DeviceStateFrame(state=SessionState.listening,
                                 display=DeviceDisplay(title="预算多少喵？",
                                                       subtitle="多久要吃上？按住说话告诉我"))
        for w in list(device_sockets):
            try:
                await w.send_text(frame.model_dump_json())
            except Exception:
                pass
        return {**session.model_dump(), "followup": "预算多少喵？多久要吃上？"}
    pool = load_candidates()
    if USE_MODEL and body.menu_image_b64:
        # 联动：识菜要 ~1.5 分钟，板子同步进"看菜单"思考屏（同卡路里的软硬一台戏）
        session.state = SessionState.structuring
        council_lines.pop(session.session_id, None)
        for w in list(device_sockets):
            try:
                await w.send_text(DeviceStateFrame(
                    state=SessionState.structuring,
                    display=DeviceDisplay(title="猫猫在看菜单",
                                          subtitle="认真看喵...要一会")).model_dump_json())
            except Exception:
                pass
        try:
            menu = await router.parse_menu_image(body.menu_image_b64, body.menu_image_mime)
            photo_cands = menu_to_candidates(menu)
            if photo_cands:
                pool = photo_cands + pool
            else:
                session.risk_flags.append("menu_parse_empty: 菜单未识别出可推荐菜品，已回落本地餐厅池")
            ledger.append(session.session_id, "structured",
                          {"menu_items": len(photo_cands), "restaurant": menu.get("restaurant")})
        except (ModelError, ValueError) as e:
            session.risk_flags.append(f"menu_parse_failed: {e}")
    session_pools[session.session_id] = pool

    async def on_agent(agent: str):
        name, line = cat_line(session, agent)
        council_lines[session.session_id] = (name, f"{line}（{len(session.agent_scores)}/4）")
        await push_state(session)

    session = await run_decision(session, pool,
                                 model=router if USE_MODEL else None,
                                 ledger_recent=ledger.recent_meals(),
                                 on_agent=on_agent)
    # 探索模式：瞬间抽完没有过程感 → 摇树小剧场（1.2s）再揭晓
    import asyncio as _aio
    if session.decision_mode and session.decision_mode.value == "explore":
        st_keep = session.state
        session.state = SessionState.council
        council_lines[session.session_id] = ("探索猫", "摇苹果树...摇下一个好吃的喵！")
        await push_state(session)
        await _aio.sleep(1.2)
        session.state = st_keep
    session.audit = deterministic_audit(session)
    if session.audit and not session.audit.approve:
        session.state = SessionState.error
    ledger.append(
        session.session_id,
        "choice",
        {
            "mode": session.decision_mode,
            "final": session.final_choice.model_dump() if session.final_choice else None,
            "audit": session.audit.model_dump() if session.audit else None,
            "rejected": session.risk_flags,
        },
    )
    await push_state(session)
    return session.model_dump()


def cancel_background_decision(session_id: str) -> None:
    import asyncio

    task = decision_tasks.get(session_id)
    current = asyncio.current_task()
    if task is not None and task is not current and not task.done():
        task.cancel()


def advance_voice_generation(session_id: str) -> int:
    generation = voice_generations.get(session_id, 0) + 1
    voice_generations[session_id] = generation
    return generation


def voice_generation_is_current(session_id: str, generation: int) -> bool:
    return voice_generations.get(session_id, 0) == generation


def schedule_background_decision(session_id: str, coroutine):
    import asyncio

    cancel_background_decision(session_id)
    task = asyncio.create_task(coroutine)
    decision_tasks[session_id] = task
    return task


def background_task_is_current(session_id: str) -> bool:
    import asyncio

    task = asyncio.current_task()
    tracked = decision_tasks.get(session_id)
    return tracked is None or tracked is task


async def mark_background_error(session_id: str, stage: str, error: Exception) -> None:
    if not background_task_is_current(session_id):
        return
    session = sessions.get(session_id)
    ledger.append(session_id, "error", {"stage": stage, "reason": str(error)})
    if not session:
        return
    session.risk_flags.append(f"{stage}: {error}")
    session.state = SessionState.error
    await push_state(session)


async def run_voice_decision(session_id: str, text: str) -> None:
    import asyncio

    try:
        await submit_input(InputPayload(session_id=session_id, text=text))
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - 后台异常必须收敛到可恢复状态
        await mark_background_error(session_id, "voice_bg", error)
    finally:
        if decision_tasks.get(session_id) is asyncio.current_task():
            decision_tasks.pop(session_id, None)


async def run_recouncil_decision(session_id: str) -> None:
    import asyncio

    try:
        session = sessions[session_id]
        updated = await run_decision(
            session,
            session_pools.get(session_id) or load_candidates(),
            model=router if USE_MODEL else None,
            ledger_recent=ledger.recent_meals(),
        )
        sessions[session_id] = updated
        await push_state(updated)
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - 后台异常必须收敛到可恢复状态
        await mark_background_error(session_id, "recouncil_bg", error)
    finally:
        if decision_tasks.get(session_id) is asyncio.current_task():
            decision_tasks.pop(session_id, None)


@app.post("/v1/device/event")
async def device_event(evt: DeviceEvent):
    advance_voice_generation(evt.session_id)
    session = get_or_revive(evt.session_id)
    # 幂等：网络抖动下固件重发同一事件（同 device+event+timestamp）只生效一次
    if evt.timestamp:
        key = f"{evt.device_id}:{evt.event.value}:{evt.timestamp}"
        import time as _time
        now = _time.time()
        for k in [k for k, ts in seen_events.items() if now - ts > 300]:
            seen_events.pop(k, None)
        if key in seen_events:
            return {"ok": True, "state": session.state, "duplicate": True}
        seen_events[key] = now
    ledger.append(evt.session_id, "device_event", evt.model_dump())

    if (evt.event in (DeviceEventType.left_ear, DeviceEventType.right_ear)
            and session.state == SessionState.error):
        session.state = SessionState.idle   # 错误态按任意耳=复位待命，不再反复推错帧
    elif evt.event == DeviceEventType.left_ear and session.state == SessionState.done:
        done_generations[session.session_id] = done_generations.get(session.session_id, 0) + 1
        session.state = SessionState.idle
    elif evt.event == DeviceEventType.left_ear and session.state == SessionState.candidate:
        session.cursor += 1
    elif evt.event == DeviceEventType.right_ear and session.state == SessionState.candidate:
        session.state = SessionState.confirming
    elif evt.event == DeviceEventType.both_ears and session.state in (
        SessionState.idle, SessionState.candidate, SessionState.listening,
        SessionState.error,
    ):
        # 重开议事会转后台：走 LLM 时耗时分钟级，攥着 HTTP 会让板子超时(-11 同款)
        session.decision_mode = None  # 沿用本轮候选池（含拍照菜品）
        session.state = SessionState.council
        council_lines.pop(evt.session_id, None)   # 立刻给"四只猫开会中..."开场帧
        schedule_background_decision(
            evt.session_id, run_recouncil_decision(evt.session_id)
        )
    elif evt.event == DeviceEventType.cancel and session.state != SessionState.acting:
        cancel_background_decision(evt.session_id)
        session.state = SessionState.idle
    await push_state(session)
    return {"ok": True, "state": session.state}


@app.post("/v1/confirm")
async def confirm(body: dict):
    advance_voice_generation(body.get("session_id", ""))
    session = sessions.get(body.get("session_id", ""))
    if not session:
        raise HTTPException(404, "session not found")
    if session.state != SessionState.confirming:
        raise HTTPException(409, f"state is {session.state}, not confirming")
    session.human_confirmed = True
    session.state = SessionState.acting
    ledger.append(session.session_id, "confirm", {"human_confirmed": True})
    await push_state(session)

    shown = session.candidates[session.cursor % len(session.candidates)]
    # 最终安全门：执行外部动作前用硬规则最后复核一次（纵深防御，任何上游失误到此为止）
    from core.constraint_engine import check_candidate
    ok, reasons = check_candidate(shown, session.hard_constraints, session.context)
    if not ok:
        session.state = SessionState.error
        ledger.append(session.session_id, "violation_blocked",
                      {"candidate": shown.id, "reasons": reasons})
        await push_state(session)
        raise HTTPException(409, f"最终安全门拦截: {reasons}")
    session.action_result = build_action(shown, session.context.channel,
                                         budget_max=session.hard_constraints.budget_max)
    session.state = SessionState.done if session.action_result.ok else SessionState.error
    generation = None
    if session.state == SessionState.done:
        generation = done_generations.get(session.session_id, 0) + 1
        done_generations[session.session_id] = generation
    ledger.append(session.session_id, "action", session.action_result.model_dump())
    await push_state(session)
    if session.state == SessionState.done:
        import asyncio

        asyncio.get_running_loop().create_task(
            auto_idle_after_done(session.session_id, generation=generation)
        )
    return {"ok": session.action_result.ok,
            "action": session.action_result.action,
            "url": session.action_result.url,
            "app_url": session.action_result.app_url}


@app.post("/v1/feedback")
async def feedback(body: dict):
    sid = body.get("session_id", "")
    advance_voice_generation(sid)
    if sid not in sessions:
        raise HTTPException(404, "session not found")
    session = sessions[sid]
    if session.state not in (SessionState.done, SessionState.idle):
        ledger.append(sid, "feedback", {
            **body, "ignored": True, "state": session.state.value,
        })
        return {"ok": True, "ignored": True, "state": session.state}
    ledger.append(sid, "feedback", body)
    session.state = SessionState.idle
    done_generations[sid] = done_generations.get(sid, 0) + 1
    # 联动：手机点了👍/👎，板子眨眼答应一声（记忆猫入账的实感）
    liked = bool(body.get("would_repeat"))
    frame = DeviceStateFrame(
        state=SessionState.idle,
        display=DeviceDisplay(title="记住了喵！",
                              subtitle="下次再推它" if liked else "下回记着换"))
    for w in list(device_sockets):
        try:
            await w.send_text(frame.model_dump_json())
        except Exception:
            pass
    return {"ok": True}


_ASR = {"model": None}


@app.on_event("startup")
async def _warm_asr():
    """启动即预热 whisper：冷加载 20-40s 会让板子第一次语音 HTTP 超时(-11)。"""
    import asyncio as _aio

    def _load():
        try:
            _asr(b"\x00\x00" * 16000, 16000)   # 1 秒静音跑通全链路（模型加载+VAD）
            print("[ASR] whisper 预热完成")
        except Exception as e:  # noqa: BLE001
            print(f"[ASR] 预热失败: {e}")

    _aio.get_event_loop().run_in_executor(None, _load)


def _asr(pcm_bytes: bytes, rate: int) -> str:
    """CPU ASR（faster-whisper small, int8）——懒加载，不与 GPU 冲突。"""
    import numpy as np
    if _ASR["model"] is None:
        from faster_whisper import WhisperModel
        _ASR["model"] = WhisperModel("small", device="cpu", compute_type="int8")
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if rate != 16000 and len(audio):
        idx = (np.arange(0, len(audio), rate / 16000)).astype(int)
        audio = audio[idx[idx < len(audio)]]
    segments, _ = _ASR["model"].transcribe(
        audio, language="zh", beam_size=1, vad_filter=True,
        # 点餐领域词表偏置：不加时"面食"常被解码成"面试"
        initial_prompt="点外卖场景：预算多少块以内，几分钟内吃上，想吃辣的，"
                       "不要面食，不吃香菜，米线、烤鱼、黄焖鸡、砂锅、麻辣烫、外卖。")
    text = "".join(seg.text for seg in segments).strip()
    for wrong, right in (("面试", "面食"), ("免税", "面食")):   # 实测误听映射
        text = text.replace(wrong, right)
    return text


@app.post("/v1/voice")
async def voice_input(request: Request, session_id: str = "", rate: int = 16000):
    """板载语音：原始 int16 PCM body → ASR → 走标准输入管线。"""
    voice_generation = advance_voice_generation(session_id)
    cancel_background_decision(session_id)
    pcm = await request.body()
    if len(pcm) < 8000:
        raise HTTPException(400, "audio too short")
    import asyncio as _aio
    text = await _aio.get_event_loop().run_in_executor(None, _asr, pcm, rate)
    if not voice_generation_is_current(session_id, voice_generation):
        ledger.append(session_id or "anon", "input", {
            "event": "voice_ignored", "reason": "superseded",
        })
        return {"accepted": False, "ignored": True, "reason": "superseded"}
    ledger.append(session_id or "anon", "input", {"event": "voice", "asr": text})
    if not text:
        raise HTTPException(422, "没听清")
    # 语音口令：确认/换一个 直接映射为动作，其余进决策管线
    compact = text.replace("。", "").replace("，", "").strip()
    if any(k in compact for k in ("就吃这个", "就这个", "确认", "就它了", "可以下单")):
        await device_event(DeviceEvent(device_id="voice", session_id=session_id,
                                       event=DeviceEventType.right_ear, timestamp=0))
        return await confirm({"session_id": session_id})
    if any(k in compact for k in ("换一个", "换个", "不要这个", "下一个")):
        return await device_event(DeviceEvent(device_id="voice", session_id=session_id,
                                              event=DeviceEventType.left_ear, timestamp=0))
    # 闲聊拦截：没有任何吃饭信号（食物字/预算数字/饿）就不硬推荐，回一句猫式问候
    _FOOD_SIGNAL = set(
        "吃饿辣饭面米菜汤锅烤鱼肉鸡虾蟹粥饼串炒蒸炸卤麻烫寿司沙拉轻食"
        "随便外卖点单配送预算元块分钟小时"
    )
    _NUMBER_SIGNAL = set("零〇一二两三四五六七八九十百千万")
    if (len(compact) <= 14 and not any(ch.isdigit() for ch in compact)
            and not (_NUMBER_SIGNAL & set(compact))
            and not (_FOOD_SIGNAL & set(compact))):
        frame = DeviceStateFrame(state=SessionState.idle,
                                 display=DeviceDisplay(title="你好喵！",
                                                       subtitle="按住说话 告诉我想吃什么"))
        for w in list(device_sockets):
            try:
                await w.send_text(frame.model_dump_json())
            except Exception:
                pass
        ledger.append(session_id or "anon", "input", {"event": "chitchat", "text": text})
        return {"chitchat": True, "reply": "你好喵！想吃什么跟我说", "state": "idle"}
    # 决策转后台立即回 200：慢网络下抽取+剧场会拖过板子 HTTP 超时(-11)；
    # 板子 UI 本就由 WS 帧驱动，不需要这个响应体
    schedule_background_decision(session_id, run_voice_decision(session_id, text))
    return {"accepted": True, "asr": text}


@app.post("/v1/calorie")
async def calorie(body: dict):
    """卡路里彩蛋（规划 09 节边界：只给区间+不确定项，不给虚假精确值，非健康建议）。"""
    if not USE_MODEL:
        raise HTTPException(503, "model offline")
    prompt = ("这是一张食物照片。识别可能的菜品，估算热量区间（必须是区间如 550-750 kcal，"
              "不得给单一精确值），列出影响估算的不确定项（分量/用油/配料）。"
              "以一句话输出，格式：菜名｜约X-Y kcal｜不确定项。最后注明：仅供参考，非健康建议。")

    async def _board(frame: DeviceStateFrame):
        for w in list(device_sockets):
            try:
                await w.send_text(frame.model_dump_json())
            except Exception:
                pass

    # 联动①：手机一上传，板子同步进"猫猫在看"思考屏（软硬件一台戏）
    await _board(DeviceStateFrame(state=SessionState.structuring,
                                  display=DeviceDisplay(title="猫猫在看",
                                                        subtitle="是什么好吃的...在数卡路里")))
    try:
        content = await router.step.chat(
            [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{body.get('image_b64','')}"}},
                {"type": "text", "text": prompt}]}],
            temperature=0.6, max_tokens=3000)   # Step reasoning ~1500 tok, 1200 会被思考吃光返回空
        ledger.append(body.get("session_id", "anon"), "input", {"event": "calorie", "result": content[:200]})
        # 联动②：结果同步上板——热量区间做大字（candidate 帧=开心猫+上扬喵）
        import re as _re
        m = _re.search(r"(\d+)\s*[-–~]\s*(\d+)\s*k?cal", content, _re.I)
        big = f"约{m.group(1)}-{m.group(2)}大卡" if m else "看好了喵"
        await _board(DeviceStateFrame(
            state=SessionState.candidate,
            display=DeviceDisplay(title="卡路里", subtitle=board_text(big, 42))))
        return {"text": content.strip()}
    except ModelError as e:
        await _board(DeviceStateFrame(state=SessionState.error,
                                      display=DeviceDisplay(title="没看清",
                                                            subtitle="再拍一张试试")))
        raise HTTPException(502, str(e))


@app.get("/v1/metrics")
async def metrics():
    """演示证据面板数据源（结尾证据画面：模型/Agent/安全/结果四行）。"""
    choices = ledger.recent(kind="choice", limit=200)
    audits_failed = sum(
        1 for c in choices
        if (c["payload"].get("audit") or {}).get("approve") is False
    )
    confirms = ledger.recent(kind="confirm", limit=200)
    step_ok = await router.step.healthy() if USE_MODEL else False
    kitten_ok = bool(router.kitten) and await router.kitten.healthy()
    return {
        "model": {
            "step_3_7_flash": "local model service online" if step_ok else "offline",
            "kitten_local": "online" if kitten_ok else "offline",
        },
        "safety": {
            "third_party_model_api_calls": 0,
            # shipped = 通过全部防线仍执行了违规动作的次数；blocked 是防线成功拦截数
            "hard_constraint_violations_shipped": 0
            if not ledger.recent(kind="violation_shipped", limit=1) else
            len(ledger.recent(kind="violation_shipped", limit=200)),
            "blocked_by_audit": audits_failed,
            "blocked_by_final_gate": len(ledger.recent(kind="violation_blocked", limit=200)),
            "external_actions_user_confirmed": len(confirms),
            "auto_payments": 0,
        },
        "decisions_total": len(choices),
        "ledger_appended": True,
        "recent_events": ledger.recent(limit=20),
    }


@app.get("/v1/session/{session_id}")
async def get_session(session_id: str):
    """扫码晚进场的手机端拉全量会话（喵单页数据源）。"""
    return get_or_revive(session_id).model_dump()


@app.get("/v1/session/{session_id}/stream")
async def session_stream(session_id: str):
    """SSE：Agent 状态与候选流——前端议事会动画的数据源。
    每 0.5s 推一帧会话快照；state 进入终态后再推一帧结束。"""
    import asyncio as _asyncio

    from fastapi.responses import StreamingResponse

    get_or_revive(session_id)

    async def gen():
        last = None
        for _ in range(600):  # 最长 5 分钟
            s = sessions.get(session_id)
            if s is None:
                break
            _DISPLAY = {"listening": "collecting", "structuring": "thinking",
                        "acting": "done"}  # 对齐产品总纲的八屏词表
            _INFRA = ("structure_failed", "council_failed", "menu_parse", "agents_rejected_all")
            fc_id = s.final_choice.candidate_id if s.final_choice else None
            # 淘汰类 flag（候选id: 理由）；基础设施降级 flag 单独走 degraded 字段
            rejections = [f for f in s.risk_flags if not f.startswith(_INFRA)]
            frame = {
                "state": s.state.value,
                "display_state": _DISPLAY.get(s.state.value, s.state.value),
                "mode": s.decision_mode.value if s.decision_mode else None,
                "agents": {a: len(v) for a, v in s.agent_scores.items()},
                # 每只猫对【最终推荐】的一句话（议事会页面台词素材）
                "agent_lines": {
                    a: next((x.evidence[0] for x in v
                             if x.candidate_id == fc_id and x.evidence), "")
                    for a, v in s.agent_scores.items()
                },
                # 审核猫台词：只念真实的候选淘汰理由
                "auditor_lines": [f"淘汰 {f.split(':')[0]}：{f.split(':', 1)[1].strip()}"
                                  for f in rejections[:3] if ":" in f],
                "degraded": [f for f in s.risk_flags if f.startswith(_INFRA)],
                "candidate": s.final_choice.model_dump() if s.final_choice else None,
                "audit": s.audit.model_dump() if s.audit else None,
            }
            if frame != last:
                yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"
                last = frame
            if s.state in (SessionState.done, SessionState.error):
                break
            await _asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.websocket("/v1/device/stream")
async def device_stream(ws: WebSocket):
    await ws.accept()
    device_sockets.append(ws)
    # 断线重连后立即重推当前会话状态帧，设备与后端状态强一致
    session = sessions.get(active_session_id)
    if session:
        try:
            await ws.send_text(build_frame(session).model_dump_json())
        except Exception:
            pass
    try:
        while True:
            await ws.receive_text()  # 心跳/ACK；内容暂不处理
    except WebSocketDisconnect:
        pass
    except RuntimeError as error:
        if "WebSocket is not connected" not in str(error):
            raise
    finally:
        if ws in device_sockets:
            device_sockets.remove(ws)
