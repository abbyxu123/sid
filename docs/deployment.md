# 部署说明（本地 AI 工作站）

## 服务拓扑与端口

| 端口 | 服务 | 角色 | 内存 |
|---|---|---|---|
| 8080 | llama-server: Step 3.7 Flash IQ4_XS + mmproj | 深思：多模态/议事会/审核 | ~105G |
| 8081 | llama-server: kitten (Qwen3-4B LoRA, Q8_0) | 直觉：结构化抽取/快评分 | ~5G |
| 8090 | device_gateway (FastAPI+WS) | 硬件唯一入口 | <1G |

设备（方形开发板）与 local AI host 须同一网段（local AI host WiFi `wlP9s9`）；固件只连 8090。

## 启动顺序（重要）

```bash
# 1. Step 3.7（tmux 会话 llm；冷加载约 7 分钟；有 mmproj 的视觉版为默认档）
tmux new-session -d -s llm "bash ~/step-server.sh"

# 2. kitten（秒级加载）
tmux new-window -t kitten -n serve \
  "~/llama.cpp-main/build/bin/llama-server -m ~/kitten/gguf/<最新kitten>.gguf \
   -ngl 99 -fa on -c 4096 -np 4 --port 8081 --alias kitten-nlu"

# 3. 网关
cd /path/to/sid
USE_MODEL=1 USE_KITTEN=1 KITTEN_MODEL=kitten-nlu \
  ~/kitten/venv/bin/python -m uvicorn services.device_gateway.main:app \
  --host 0.0.0.0 --port 8090
```

验收：`curl :8090/health` 应返回 `{"model": {"step": "ok", "kitten": "ok"}}`。

## 环境变量开关（全部可一键关闭，关闭后主闭环仍完整）

| 变量 | 默认 | 作用 |
|---|---|---|
| `USE_MODEL` | 1 | 0 = 纯规则模式（模型全下线也能跑完整闭环，演示保底） |
| `USE_KITTEN` | — | 1 = 抽取走 kitten（失败自动升级 Step） |
| `KITTEN_ACTORS` | — | 1 = 议事会 Actor 也走 kitten（需 scorer 蒸馏版） |
| `STEP_BASE_URL` / `KITTEN_BASE_URL` | :8080 / :8081 | 模型服务地址 |
| `AGENT_CONCURRENCY` | 3 | 议事会并发槽位 |

## 训练复现（kitten）

见 `docs/training_plan.md` 与 `training/`。要点：训练前必须停两个 llama-server
（Step 权重 105G，共存必 OOM）；`TORCH_COMPILE_DISABLE=1` + `CPATH` 指向解包的
python3.12 头文件（无 root 修法，详见 devlog Day5）；单次 4B LoRA 约 60-90 分钟。

## 已知回退路径

- 模型服务挂 → 网关自动降级规则评分，闭环不中断（`risk_flags` 记录降级原因）
- kitten 抽取失败 → 自动升级 Step 重试 → 再失败走手工结构化字段
- 议事会单 Agent 失败 → 缺席中性处理；全灭 → 规则评分兜底
- 设备断连 → 屏幕按钮与手机端等价操作（协议见 docs/api_contract.md）
