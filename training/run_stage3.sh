#!/usr/bin/env bash
# stage3：kitten v2 多任务训练（NLU+scorer 蒸馏）+ 1.7B 对照 + 全家桶评测 + 恢复服务
# 前提：council_labels.jsonl 已生成。在 local AI host 上运行，日志 ~/kitten/stage3.log
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVAL_DIR="${EVAL_DIR:-$ROOT_DIR/eval}"
mkdir -p "$EVAL_DIR"
cd "$ROOT_DIR"
VENV=~/kitten/venv/bin
export TORCH_COMPILE_DISABLE=1 TORCHDYNAMO_DISABLE=1
export CPATH=$HOME/pydev/extract/usr/include/python3.12:$HOME/pydev/extract/usr/include

echo "=== [1/7] build mixed dataset ==="
$VENV/python scripts/build_mixed_dataset.py \
    --nlu skills/food/kitten/train_verified.jsonl \
    --scorer skills/food/kitten/council_labels.jsonl \
    --holdout 40 --scorer-repeat 3 --out ~/kitten/train_v2_mixed.jsonl

echo "=== [2/7] stop model servers ==="
pkill -f "llama-server" || true
sleep 15; free -g | head -2

echo "=== [3/7] train kitten v2 (4B, multi-task) ==="
$VENV/python training/train_kitten.py --task messages \
    --base ~/kitten/models/Qwen3-4B-Instruct-2507 \
    --data ~/kitten/train_v2_mixed.jsonl \
    --out ~/kitten/runs/kitten-v2-4b 2>&1 | tee ~/kitten/train_v2.log | tail -5

echo "=== [4/7] train 1.7B NLU (对照组) ==="
$VENV/python training/train_kitten.py --task nlu \
    --base ~/kitten/models/Qwen3-1.7B \
    --data ~/kitten/train_verified.jsonl \
    --out ~/kitten/runs/nlu-1.7b 2>&1 | tee ~/kitten/train_17b.log | tail -5

echo "=== [5/7] export GGUF ==="
for pair in "kitten-v2-4b kitten-v2-4b" "nlu-1.7b kitten-nlu-17b"; do
    set -- $pair
    $VENV/python ~/llama.cpp-main/convert_hf_to_gguf.py ~/kitten/runs/$1/merged \
        --outfile ~/kitten/gguf/$2-f16.gguf --outtype f16
    ~/llama.cpp-main/build/bin/llama-quantize ~/kitten/gguf/$2-f16.gguf ~/kitten/gguf/$2-q8_0.gguf Q8_0
    rm -f ~/kitten/gguf/$2-f16.gguf
done

echo "=== [6/7] serve + evals ==="
~/llama.cpp-main/build/bin/llama-server -m ~/kitten/gguf/kitten-v2-4b-q8_0.gguf \
    -ngl 99 -fa on -c 4096 -np 4 --port 8081 --alias kitten-nlu > /tmp/kitten_server.log 2>&1 &
~/llama.cpp-main/build/bin/llama-server -m ~/kitten/gguf/kitten-nlu-17b-q8_0.gguf \
    -ngl 99 -fa on -c 4096 -np 4 --port 8082 --alias kitten-17b > /tmp/kitten17_server.log 2>&1 &
for port in 8081 8082; do
    for i in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:$port/health | grep -q ok && break; sleep 5; done
done
cd "$ROOT_DIR"
$VENV/python scripts/eval_extraction.py --base-url http://127.0.0.1:8081 --model kitten-nlu \
    --cases tests/synthetic_cases/cases.json --tag kitten_v2_nlu --concurrency 4 \
    --max-tokens 600 --out-dir "$EVAL_DIR" || true
$VENV/python scripts/eval_extraction.py --base-url http://127.0.0.1:8082 --model kitten-17b \
    --cases tests/synthetic_cases/cases.json --tag kitten_17b_nlu --concurrency 4 \
    --max-tokens 600 --out-dir "$EVAL_DIR" || true
$VENV/python scripts/eval_scorer.py --labels skills/food/kitten/council_labels.jsonl \
    --holdout 40 --kitten-url http://127.0.0.1:8081 --tag scorer_v2 --out-dir "$EVAL_DIR" || true
pkill -f "llama-server.*8082" || true

echo "=== [7/7] restore Step ==="
tmux kill-session -t llm 2>/dev/null || true
tmux new-session -d -s llm "bash ~/step-server.sh"
echo STAGE3_DONE > /tmp/stage3.done
echo "ALL DONE"
