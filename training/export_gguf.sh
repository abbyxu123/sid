#!/usr/bin/env bash
# merged HF 模型 → GGUF Q8_0 → llama-server :8081 可直接加载（在 local AI host 上运行）
# 用法: ./export_gguf.sh ~/kitten/runs/nlu-4b-r16/merged ~/kitten/gguf/kitten-nlu-4b
set -euo pipefail
MERGED=$1
OUT=$2
LLAMA=~/llama.cpp-main
mkdir -p "$(dirname "$OUT")"

# convert 脚本依赖：llama.cpp 自带 requirements（gguf, sentencepiece）
python3 "$LLAMA/convert_hf_to_gguf.py" "$MERGED" --outfile "${OUT}-f16.gguf" --outtype f16
"$LLAMA/build/bin/llama-quantize" "${OUT}-f16.gguf" "${OUT}-q8_0.gguf" Q8_0
rm "${OUT}-f16.gguf"
echo "GGUF ready: ${OUT}-q8_0.gguf"
echo "启动: ~/llama.cpp-main/build/bin/llama-server -m ${OUT}-q8_0.gguf -ngl 99 -fa on -c 4096 -np 4 --port 8081 --alias kitten-nlu"
