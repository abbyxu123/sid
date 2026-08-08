# API 契约 V1.0（2026-07-16 冻结）

数据结构唯一来源：`core/decision_schema.py`。**改字段先改 schema + 本文档，再改代码/固件/UI。**

> 2026-08-08 产品流程补充：资料、单次补问、人数/场景/距离、人体存在、手账和 QR/H5 交接已经进入当前网关。盲盒多选、多人匹配、居家做饭和完整毫米波数据仍见 `docs/backend_gap_todo.md`。

> 2026-08-07 输入补充：`soft_preferences` 增加 `wanted_ingredients`（本次明确想吃）与 `extra_ingredients`（多加/多放）。当次明确条件优先于长期档案；档案过敏与饮食禁忌仍始终生效。摇一摇只在本轮硬约束与点名食物过滤后的候选池中随机。

Device Gateway 默认端口 **8090**（网关 Wi-Fi IP `<GATEWAY_LAN_IP>`，开发板与网关需同一网段；
远程开发可走 Tailscale `<GATEWAY_TAILSCALE_IP>`）。模型服务 llama-server 在 **8080**（alias `step-local`），
固件**只连 8090**，永远不直连 8080。

## REST

| 接口 | 方法 | 用途 | 请求体 | 返回 |
|---|---|---|---|---|
| `/health` | GET | 网关/模型/设备状态 | — | `{gateway, sessions, devices_online, model}` |
| `/v1/session` | POST | 创建一轮决策 | `{device_id}` | `{session_id}` |
| `/v1/input` | POST | 文字/结构化偏好（语音转写、菜单图后续同入口） | `InputPayload`（见下） | 完整 `DecisionSession` |
| `/v1/voice` | POST | PCM 语音识别并进入同一输入流程 | 二进制 PCM + query `session_id,rate` | 接收/命令结果 |
| `/v1/device/event` | POST | 耳朵/屏幕按钮事件 | `DeviceEvent` | `{ok, state}` |
| `/v1/confirm` | POST | 确认候选，触发工具执行 | `{session_id}` | `{ok}` |
| `/v1/feedback` | POST | 吃后评分/是否复购/拒绝原因 | `{session_id, rating, would_repeat, reject_reason}` | `{ok}` |
| `/v1/profile` | GET/PUT | 可选长期资料、偏好与关怀上下文 | 部分资料字段 | `{ok, profile}` 或资料 |
| `/v1/journal` | GET | 饮食手账与复购记忆 | query `days,group` | 手账列表/分组 |
| `/v1/hungry` | GET/POST | 基于最近记录的非医学提示 | — | `{title, subtitle}` |
| `/v1/sensor/presence` | POST | 毫米波人体存在上报 | `{present}` | `{ok}` |
| `/v1/metrics` | GET | 演示证据面板 | — | 指标 + 最近事件 |

`InputPayload`：
```json
{
  "session_id": "sess_xxx",
  "text": "四十块以内想吃辣的，不吃面，半小时内能吃到",
  "hard_constraints": {"allergens": [], "diet_taboos": ["面食"], "budget_max": 40, "eat_by_minutes": 30, "max_distance_m": 3000, "hated": []},
  "soft_preferences": {"spicy": "medium", "cuisines": [], "wanted_ingredients": ["鱼"], "extra_ingredients": ["香菜"], "novelty": null},
  "context": {"people": 2, "state": "normal", "channel": "delivery"}
}
```
`text` 与结构化字段可只给其一：只给 `text` 时后端用模型做结构化抽取（7/17 起）；
两者同时提供时必须合并。手机端明确选择的标量高于抽取结果，安全清单和食材清单取并集，不能因为选择了预算/场景而丢掉语音中的过敏、忌口或想吃食材。

## 设备上行事件（固件 → 网关）

`POST /v1/device/event`
```json
{"device_id": "cat-square-01", "session_id": "sess_xxx",
 "event": "left_ear | right_ear | both_ears | cancel",
 "timestamp": 1784212345, "firmware_version": "0.3.0"}
```

语义（与文档 08 节一致）：

| 事件 | 动作 | 允许状态 |
|---|---|---|
| `left_ear` | 换一个候选 | candidate |
| `right_ear` | 接受 → confirming | candidate |
| `both_ears` | 召集议事会/重新讨论 | idle, candidate |
| `cancel`（双耳长按） | 取消本轮回 idle | 任何非 acting 状态 |

要求：固件侧去抖、双耳 500ms 判定窗口；事件需可重放（幂等：同一 timestamp+event 重复提交只生效一次——TODO 网关侧 7/19 实现）。

## 设备下行状态（网关 → 固件，WebSocket）

`ws://<gateway>:8090/v1/device/stream`，每次状态变化推一帧：
```json
{"state": "idle|listening|structuring|council|candidate|confirming|acting|done|error",
 "display": {"title": "今日推荐", "subtitle": "香辣烤鱼小份 ¥36 / 26分钟"},
 "haptic": "none|tap|double|long", "audio": "none|meow_confirm|meow_error",
 "candidate": {"id": "r01_kaoyu_s", "confidence": 0.91}}
```
固件把收到的任何文本当心跳回执即可；断线重连由固件负责，重连后网关重推当前帧（TODO 7/19）。

## 状态机

```
idle → listening → structuring → (council) → candidate ⇄ (left_ear 换一个)
candidate → confirming → acting → done
任何状态 --cancel--> idle；任何失败 → error（可 both_ears 重试）
```
