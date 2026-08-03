# 硬件联调指南（给硬件工程师，7/19 Gate 3）

## 连接信息

- 网关：`http://<GATEWAY_LAN_IP>:8090`（板子必须连同一个 Wi-Fi）
- 远程调试可走 Tailscale：`http://<GATEWAY_TAILSCALE_IP>:8090`
- 协议全文：`docs/api_contract.md`（V1.0 冻结，未变更过）
- **参考实现**：`scripts/mock_device.py`——完整演示了 WS 重连、事件发送、确认流程，
  可以先跑它看真实报文，再对照写固件。

## 固件要做的三件事

1. **WS 长连**：`ws://<网关>/v1/device/stream`，收 JSON 状态帧驱动屏幕/震动/声音；
   断线重连（3s 退避即可）——重连成功后网关会**立刻重推当前帧**，不用担心丢状态。
2. **事件上报**：`POST /v1/device/event`，四种 event；`timestamp` 用毫秒并保证同一次
   物理按压只用一个值——网关按 `device_id:event:timestamp` 幂等去重，**重发安全**，
   网络抖动时放心重试（响应里 `duplicate: true` 表示是重复包）。
3. **确认动作**：右耳按下且收到 `state=confirming` 帧后，再 `POST /v1/confirm`
   （屏幕按钮同样调这两个接口，与耳朵完全等价）。

## 排错三板斧

```bash
curl http://<GATEWAY_LAN_IP>:8090/health        # 网关/模型在线状态
curl http://<GATEWAY_LAN_IP>:8090/v1/metrics    # 最近 20 条事件（你发的事件有没有到）
python3 scripts/mock_device.py --gateway ... # 用 mock 对照：mock 能通固件不通=固件问题
```

## 验收清单（文档 08 节门槛）

- [ ] 连续 20 次耳朵事件无丢失（metrics 里逐条可见）
- [ ] 断 WiFi 30s 重连后状态帧恢复且与后端一致
- [ ] 双耳 500ms 窗口 / 长按取消在固件侧判定，网关只认四种 event
- [ ] 屏幕按钮全流程可替代耳朵（机械结构故障回退）
