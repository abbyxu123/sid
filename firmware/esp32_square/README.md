# 方形终端固件 — Waveshare ESP32-S3-Touch-AMOLED-2.16（实物已确认）

板子：2.16" AMOLED 480x480（Display CO5300 / Touch CST9220）、ESP32-S3、16MB Flash、
8MB PSRAM、ES8311+ES7210 喇叭双麦、IMU QMI8658、AXP2101 电池管理、USB-C、侧键 PWR/BOOT/+KEY。

## 烧录路径（推荐，半天内可跑通）
1. 下载微雪官方资料包（wiki 搜 "ESP32-S3-Touch-AMOLED-2.16"）——内含 Arduino/ESP-IDF
   demo 工程，CO5300 + CST9220 驱动、LVGL 移植、音频例程全都是现成的。
2. 用官方 LVGL demo 工程做底，把本目录 `noon_cat_terminal.ino` 的**协议层**移植进去：
   - ensureSession / postEvent / onWsEvent / ws.setReconnectInterval 原样可用
   - render() 换成 LVGL label/bg 更新（官方 demo 有现成中文字库示例 → 直接显示中文菜名）
   - 触摸四分区逻辑不变：左半=left_ear 右半=right_ear 顶栏=both_ears 底栏长按=cancel
3. `.ino` 里 4848S040 的显示初始化段**不适用于本板**，仅留作其他 RGB 板参考。

## 本板独有加分项（按性价比排序）
- **喵声**：ES8311 喇叭放 meow_confirm/meow_error（状态帧 audio 字段已定义，放两个 wav 即可）
- **摇一摇=安全探索**：QMI8658 检测 shake → POST /v1/input {"soft_preferences":{"novelty":"bold"}}
  ——产品"摇苹果树"玩法的实体入口，约 30 行
- **实体键**：+/KEY 侧键可绑 both_ears（机械按键党的仪式感）
- 电池供电无线摆桌 + AMOLED 纯黑底色省电（idle 屏保：黑底一对猫眼）

## 验收不变（docs/hardware_integration.md）
20 次事件无丢失 / 断网重连状态一致 / 屏幕按钮全流程可用
