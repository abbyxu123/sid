"""Decision Schema — 全项目唯一数据契约（V1.0，2026-07-16 冻结）。

规则：任何字段变更必须先改本文件 + docs/api_contract.md，再改代码/固件/UI。
硬件、前端、模型侧都以此为准，不得私自扩展字段。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


class DecisionMode(str, Enum):
    """路由结果。一键决定 = direct + context.state 为低耐心；二选一 = duel。"""

    direct = "direct"
    council = "council"
    explore = "explore"
    duel = "duel"


class Channel(str, Enum):
    delivery = "delivery"
    dine_in = "dine_in"
    any = "any"


class SessionState(str, Enum):
    """设备与后端共享的状态机，顺序即主链路。"""

    idle = "idle"
    listening = "listening"
    structuring = "structuring"
    council = "council"
    candidate = "candidate"
    confirming = "confirming"
    acting = "acting"
    done = "done"
    error = "error"


class DeviceEventType(str, Enum):
    left_ear = "left_ear"      # 换一个 / 拒绝当前候选
    right_ear = "right_ear"    # 接受候选 / 进入确认
    both_ears = "both_ears"    # 召集议事会 / 重新讨论
    cancel = "cancel"          # 双耳长按：取消本轮


class HardConstraints(BaseModel):
    """确定性硬规则的输入。模型不得改写、不得推翻。"""

    allergens: list[str] = Field(default_factory=list)      # 过敏原，如 ["花生"]
    diet_taboos: list[str] = Field(default_factory=list)    # 禁忌，如 ["猪肉", "面食"]
    budget_max: Optional[float] = None                      # 总价上限（元，含配送费）
    eat_by_minutes: Optional[int] = None                    # 最晚多少分钟内吃到
    max_distance_m: Optional[int] = None                    # 就餐半径（米，到店场景）
    hated: list[str] = Field(default_factory=list)          # 明确讨厌项（安全探索也要排除）


class SoftPreferences(BaseModel):
    spicy: Optional[str] = None          # none | mild | medium | hot
    cuisines: list[str] = Field(default_factory=list)
    temperature: Optional[str] = None    # hot | cold | any
    novelty: Optional[str] = None        # conservative | balanced | bold


class Context(BaseModel):
    location: str = ""
    time: str = ""
    people: int = 1
    state: str = "normal"                # normal | tired | low_patience | fitness | late_night
    channel: Channel = Channel.any


class Candidate(BaseModel):
    """本地 Demo 餐厅库中的一条可选项（餐厅×套餐粒度）。"""

    id: str
    restaurant: str
    item: str
    price_total: float                   # 含配送费/预估到店人均
    eta_minutes: int                     # 外卖=配送 ETA；到店=路程+排队
    cuisine: str
    spicy_level: str = "none"            # none | mild | medium | hot
    ingredients: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)   # 如 ["面食", "汤", "炸物"]
    distance_m: int = 0
    open_now: bool = True
    queue_minutes: int = 0
    channel: Channel = Channel.delivery


class AgentScore(BaseModel):
    """单 Agent 输出规范（文档 06 节原样）。所有专业 Agent 强制此格式。"""

    candidate_id: str
    hard_constraint_pass: bool
    score: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class AuditVerdict(BaseModel):
    approve: bool
    corrections: list[str] = Field(default_factory=list)
    rejected: dict[str, str] = Field(default_factory=dict)  # candidate_id -> 淘汰理由


class FinalChoice(BaseModel):
    candidate_id: str
    backup_id: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class ActionResult(BaseModel):
    action: str = ""                     # map_deeplink | order_deeplink | none
    url: str = ""
    app_url: str = ""                    # App scheme 深链（tbopen 等），前端优先尝试
    approved_by_user: bool = False
    ok: bool = False
    error: str = ""


class Feedback(BaseModel):
    rating: Optional[int] = None         # 1-5
    would_repeat: Optional[bool] = None
    reject_reason: str = ""


class DecisionSession(BaseModel):
    """一轮决策的完整状态。Foreman 持有；Ledger 逐事件落盘。"""

    session_id: str
    schema_version: str = SCHEMA_VERSION
    state: SessionState = SessionState.idle
    raw_input: str = ""                  # 用户原话，防止系统改写意图
    goal: str = ""
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    soft_preferences: SoftPreferences = Field(default_factory=SoftPreferences)
    context: Context = Field(default_factory=Context)
    decision_mode: Optional[DecisionMode] = None
    candidates: list[Candidate] = Field(default_factory=list)
    agent_scores: dict[str, list[AgentScore]] = Field(default_factory=dict)  # agent 名 -> 各候选评分
    risk_flags: list[str] = Field(default_factory=list)
    audit: Optional[AuditVerdict] = None
    final_choice: Optional[FinalChoice] = None
    human_confirmed: bool = False
    action_result: Optional[ActionResult] = None
    feedback: Optional[Feedback] = None
    cursor: int = 0                      # 当前展示第几个候选（左耳换一个用）


# ---- 设备协议（文档 08 节原样） ----

class DeviceEvent(BaseModel):
    """POST /v1/device/event 上行。"""

    device_id: str
    session_id: str = ""
    event: DeviceEventType
    timestamp: int = 0
    firmware_version: str = ""


class DeviceDisplay(BaseModel):
    title: str = ""
    subtitle: str = ""


class DeviceStateFrame(BaseModel):
    """WebSocket /v1/device/stream 下行。"""

    state: SessionState
    display: DeviceDisplay = Field(default_factory=DeviceDisplay)
    haptic: str = "none"                 # none | tap | double | long
    audio: str = "none"                  # none | meow_confirm | meow_error
    candidate: Optional[dict[str, Any]] = None  # {"id": ..., "confidence": ...}
