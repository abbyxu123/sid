# Agent 延迟基准（2026-07-16，local AI host spark-b72e 实测）

环境：Step 3.7 Flash IQ4_XS，llama-server 128K ctx / `-np 4`，与 ComfyUI 共驻（114G/121G）。
脚本：`scripts/bench_concurrency.py`，Agent 评分 prompt，max_tokens=1200，temp=1.0，每组 3 轮。

## 原始数据

| 模式 | 并发 | 平均延迟 | 最大延迟 | 聚合吞吐 | JSON 成功率 |
|---|---|---|---|---|---|
| 自由输出 | 1 | 40.7–45.9s | 45.9s | 26.1–27.1 tok/s | 0.67 (2/3轮全对) |
| 自由输出 | 4 | 73.7–81.5s | 85.1s | 50.6–53.0 tok/s | 0.75–1.00 |
| json_schema | 1 | 38.8–46.4s | 46.4s | 25.9–27.1 tok/s | 0.67 |
| json_schema | 4 | 72.2–74.4s | 83.3s | 49.7–52.8 tok/s | 0.75–1.00 |

补充 A/B（同 prompt，`chat_template_kwargs.enable_thinking=false`）：
reasoning 1583–1764ch vs 默认 1984–2016ch——**该开关在 Step/llama.cpp 下基本无效**。
简单 prompt（单字段打分）reasoning 仅 251–333ch（~6–8s）——**思考链长度跟任务复杂度走**。

## 结论（决定架构）

1. **Step 3.7 的深度推理应该用在刀刃上**：Agent 评分这类反射性任务也会触发完整思考链
   （~2000ch ≈ 700+ tok），单调用 ~40–46s、4 路并发墙钟 72–85s——把它用于逐候选打分是
   对深思能力的浪费，也达不到议事会 <25s 目标。聚合吞吐 ~51 tok/s（1.9× 单流），
   continuous batching 有效。⇒ 深思（结构化/仲裁/复核/多模态）归 Step，反射归蒸馏学徒。
2. **json_schema 约束不解决截断**：reasoning 先花预算，max_tokens=1200 时多轮 content 被
   截断（json_ok=false 全部来自截断而非格式错误）。Step 调用一律 max_tokens ≥1500，
   且 Actor prompt 必须极简（每次只评一个维度、少给字段）。
3. **mmproj 视觉一次通过**：合成菜单图 9 菜品+配送费+店名 100% 提取，28.9s，JSON 合法
   （`scripts/test_menu_vision.py`）。→ 建议菜单拍照升级为 Must，进 Demo 脚本。
4. **Kitten 训练线从"加分项"升级为"必要路径"**：专业 Actor 交给由 Step 议事会输出**蒸馏**
   而成的无思考链学徒（Qwen3-4B，预期 2–4s/调用 → 4 并发 <10s），Step 3.7 专注它不可替代的
   位置：多模态理解、结构化、冲突仲裁、Auditor 复核，并作为**教师模型**产出学徒的全部训练
   信号。对照实验框架："Step-only vs Step+蒸馏学徒协同"与"原始 Qwen vs Step 蒸馏后"，
   后者的差值直接量化 Step 的教学贡献。详见 training_plan.md 的叙事口径。

## 7/17 更新：kitten 首战结果（结构化抽取，40 条验收集）

| 模型 | 字段准确率 | 完全匹配 | JSON 合法 | 平均延迟 | p95 |
|---|---|---|---|---|---|
| Step 3.7 Flash（深思基线） | 88.4% | 40% | 97.5% | 48.5s | 89.7s |
| Qwen3-4B 原始（未训练） | 88.9% | 38% | 100% | 3.55s | 4.4s |
| **Kitten**（Qwen3-4B + local AI host LoRA 蒸馏训练） | **95.7%** | **72.5%** | 100% | **2.21s** | 2.4s |

训练：4000 条质检数据（Kimi 逆向生成 + 全量校验），LoRA r16，500 步 2 epoch，
loss 2.76→0.16，GB10 上 7.2s/步 ≈ 60 分钟；Q8_0 GGUF 4.3GB 与 Step 共驻 :8081。
微调带来 +6.8pt 字段准确率 / +34.5pt 完全匹配——这就是"专项训练在 local AI host 上完成"的证据。
剩余误差集中在 diet_taboos/hated 边界（0.8/0.8）——语言上"不吃X"本就无法区分禁忌与讨厌，
属任务固有歧义（Step 同样只有 0.75/0.725），产品层两者都做硬过滤，无实际影响。

## 短期缓解（kitten 就绪前，7/17–18 主链路先跑通用）

- Actor prompt 单维度化 + 输出字段砍到 3 个（目标 completion ~600 tok → 单调用 ~22s，4 路 ~45s）；
- 议事会只在冲突场景触发（路由已实现），简单场景走 direct（1 次 Step 调用或纯规则）；
- UI 全程显示各 Agent 实时状态，避免用户面对空白等待（产品侧已有此设计）。
