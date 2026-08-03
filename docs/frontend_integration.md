# 前端接入指南（给 Abby）

> 2026-07-25 更新：本文描述“当前已有后端接口怎么接”。最新产品 MVP、15 个小屏页面、P0/P1/P2 优先级和 UI 交接规则请先看：
>
> - `docs/mvp_spec.md`
> - `docs/small_screen_ux_flow.md`
> - `docs/backend_gap_todo.md`
> - `docs/ui_asset_handoff_sop.md`
>
> 旧 `/sim` 仍是 480×480 模拟器；新 UI 出图目标是 448×368 横屏，小屏适配见 `docs/small_screen_ux_flow.md`。

页面跑在你自己电脑上，只有 API 请求打到 local AI host 网关。不用 SSH、不用部署。

## 一、连上网关

| 场景 | baseURL |
|---|---|
| 人在场（和网关同 Wi-Fi） | `http://<GATEWAY_LAN_IP>:8090` |
| 远程开发 | `http://<GATEWAY_TAILSCALE_IP>:8090`（装 Tailscale + 接受共享邀请） |

验通：浏览器开 `<baseURL>/health`，应见 `{"model": {"step": "ok", "kitten": "ok"}}`。
CORS 已放开，本地 dev server 直连即可。

## 二、六屏 ↔ 接口对照

| 屏 | 调用 | 拿什么 |
|---|---|---|
| 1 小猫小偷入口 | `POST /v1/session {device_id:"web-01"}` | `session_id`（存住，全程用） |
| 2 沙发筛选 | `POST /v1/input {session_id, hard_constraints, soft_preferences, context}` | 完整会话对象；`context.state` 支持 `indulge`(放纵吃) |
| 2' 语音/文字 | `POST /v1/input {session_id, text: "四十块以内想吃辣的…"}` | 同上（kitten 2 秒结构化）；`menu_image_b64` 传菜单照片 |
| 3 看电视/换一个 | `POST /v1/device/event {event:"left_ear"…}` | Yes/No 左右滑就发 left/right_ear，和硬件完全等价 |
| 4 猫咪议事会 | `GET /v1/session/{id}/stream`（SSE） | 每 0.5s 一帧：`display_state`(你的词表)、`agents`(谁交卷了)、`agent_lines`(每只猫对最终推荐的一句话)、`auditor_lines`(审核猫淘汰台词)、`degraded`(降级提示,别渲染成淘汰) |
| 5 端菜+猫爪确认 | 帧里的 `candidate`{id,backup_id,reasons,confidence} → `POST /v1/confirm` | 返回 `{action, url}` = 地图/订单深链，新标签打开 |
| 6 喵单/手账 | `POST /v1/feedback {session_id, rating, would_repeat, reject_reason}` | 记忆猫下轮会引用 |
| 证据面板（演示结尾） | `GET /v1/metrics` | 模型在线/零第三方API/违规0/拦截数/确认数 |

## 三、SSE 用法（议事会动画核心）

```js
const es = new EventSource(`${base}/v1/session/${sid}/stream`);
es.onmessage = (e) => {
  const f = JSON.parse(e.data);
  // f.display_state: idle|collecting|thinking|council|candidate|confirming|done|error
  // f.agents: {taste: 6, budget: 6, ...} 出现即该猫交卷 → 点亮头像
  // f.agent_lines: {taste: "川菜/hot", budget: "总价 ¥36", ...} 猫的气泡台词
  // f.auditor_lines: ["淘汰 r02_chuanchuan：总价 ¥58 超预算…"] 审核猫台词
  if (["done", "error"].includes(f.state)) es.close();
};
```

节奏参考（做动画时长用）：简单模式全程 ~3s；议事会 ~7s；带菜单照片 +30s（拍照解析动画留足）。

## 四、演示剧本对应

标准冲突用例（发这句 text 即可复现）：`我想吃辣的，但只有三十块预算，25分钟内必须吃上，不吃面食`
→ 走议事会，审核猫台词会包含烤鱼被淘汰的理由；剧本里的候选 B 香辣鸡腿饭在数据里（r11_jitui）。

## 五、480×480 板子模拟器（/sim）——不碰硬件调板子 UI

浏览器打开 `<baseURL>/sim`，就是一块和真板行为一致的"虚拟板子"：

- **同一路数据**：它和实体板连的是同一个 WS（`ws://<baseURL>/v1/device/stream`），
  网关广播状态帧，两边同时亮——对着真板调视觉零时差。
- **1:1 复刻固件**：像素猫 5 套图案与动画节奏（400ms 帧）、状态色
  （议事会紫/推荐橙/确认绿/完成青/出错红）、猫名 46px 大标题 + 台词 32px 副标题、
  每只猫专属音色的合成喵叫（口味高亢/预算低沉/时间两连/记忆拖长/探索上扬）。
- **控制台即遥控器**：输入框回车=对猫说话（真实走 kitten 抽取）；
  换一个/就吃这个/重新开会 = 与硬件按键等价的 device/event；摇一摇=安全探索；
  确认下单=POST /v1/confirm（在 confirming 态后可用）。

### 用它开发板子 UI 的两条路

1. **直接改 `services/device_gateway/board_sim.html`**：改样式/动画/布局刷新即见，
   定稿后后端把视觉参数移植回 LVGL 固件（板子字库有限，中文文案请只用
   `services/device_gateway/board_charset.txt` 里出现过的字符，否则真板显示为口）。
2. **自己的页面直连 WS**：帧格式就是模拟器日志区滚动的 JSON——
   `{state, display:{title, subtitle}, haptic, audio, candidate}`，
   `state=done` 时隐藏猫、显示二维码（内容 = `<baseURL>/console?sid=<session_id>`）。

### 注意

- 帧是**广播**的：多开几个 /sim 页签会互相看到同一决策的帧，联调时正好，勿当 bug。
- 真板尺寸 480×480 圆角屏，安全边距建议 ≥24px；标题超 10 个汉字会折行，台词控制在 20 字内最稳。
- 音频需要页面上先点一下任意按钮（浏览器自动播放策略）；🔇 按钮可静音。
