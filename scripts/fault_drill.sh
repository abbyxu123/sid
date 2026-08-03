#!/usr/bin/env bash
# 故障注入演练：证明每一级降级都接得住。在本地网关或模型主机上运行。
# 场景A: kitten 下线 → 抽取/Actor 自动升级 Step，闭环仍成功
# 场景B: 双模型下线 + 自然语言 → 安全失败(error，不带空约束跑)
# 场景C: 双模型下线 + 结构化字段 → 纯规则闭环成功
set -uo pipefail
GW=http://127.0.0.1:8090
KITTEN_CMD='~/llama.cpp-main/build/bin/llama-server -m ~/kitten/gguf/kitten-v2-4b-q8_0.gguf -ngl 99 -fa on -c 4096 -np 4 --port 8081 --alias kitten-nlu'

new_session() { curl -s -X POST $GW/v1/session -H 'content-type: application/json' \
  -d '{"device_id":"drill"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["session_id"])'; }

echo "=== A. kill kitten -> 文本输入仍成功(升级 Step) ==="
tmux kill-window -t kitten:serve 2>/dev/null; pkill -f "kitten-v2-4b-q8_0" 2>/dev/null; sleep 3
SID=$(new_session)
T0=$SECONDS
curl -s -m 180 -X POST $GW/v1/input -H 'content-type: application/json' \
  -d "{\"session_id\":\"$SID\",\"text\":\"四十块以内想吃辣的，不吃面，半小时内\"}" \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print("A:",d["state"],d.get("decision_mode"),(d.get("final_choice") or {}).get("candidate_id"))'
echo "A elapsed: $((SECONDS-T0))s"

echo "=== B. kill step too -> 文本输入安全失败(error) ==="
STEP_PANE_ALIVE=$(pgrep -f "llama-server" | head -1)
pkill -f "llama-server"; sleep 5
SID=$(new_session)
curl -s -m 60 -X POST $GW/v1/input -H 'content-type: application/json' \
  -d "{\"session_id\":\"$SID\",\"text\":\"我对花生过敏随便来点\"}" \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print("B:",d["state"],"flags:",d["risk_flags"][:1])'

echo "=== C. 双下线 + 结构化字段 -> 纯规则闭环成功 ==="
SID=$(new_session)
curl -s -m 60 -X POST $GW/v1/input -H 'content-type: application/json' \
  -d "{\"session_id\":\"$SID\",\"hard_constraints\":{\"allergens\":[\"花生\"],\"budget_max\":40,\"eat_by_minutes\":30},\"soft_preferences\":{\"spicy\":\"medium\"}}" \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print("C:",d["state"],(d.get("final_choice") or {}).get("candidate_id"),"audit:",d["audit"]["approve"])'

echo "=== 恢复服务 ==="
tmux kill-session -t llm 2>/dev/null; tmux new-session -d -s llm "bash ~/step-server.sh"
tmux new-window -t kitten -n serve "$KITTEN_CMD > /tmp/kitten_server.log 2>&1 " 2>/dev/null || tmux new-session -d -s kitten -n serve "$KITTEN_CMD > /tmp/kitten_server.log 2>&1"
echo "restore kicked (step ~7min; kitten 等 step 就绪后如未起需重启一次)"
