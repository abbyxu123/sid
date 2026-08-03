"""Kitten 结构化抽取器：Qwen3 LoRA SFT（在 local AI workstation 上运行）。

  ~/kitten/venv/bin/python train_kitten.py \
      --base /cc/models/Qwen3-4B-Instruct-2507 \
      --data train_raw.jsonl --out ~/kitten/runs/nlu-4b-r16

注意：训练前必须停 llama-server（Step 权重占 105G）。约 4k 样本 × 2 epoch，
GB10 bf16 LoRA 预计 1–2 小时。训练日志/loss 曲线保留（十日谈+证据）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasets import Dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

# 与 scripts/eval_extraction.py 严格一致
SYSTEM_PROMPT = """你是猫咪决策机的需求结构化模块。把用户的话解析成 JSON，字段：
goal(字符串), allergens(数组), diet_taboos(数组), hated(数组), budget_max(数字或null),
eat_by_minutes(数字或null), spicy("none"/"mild"/"medium"/"hot"/null), cuisines(数组),
novelty("conservative"/"balanced"/"bold"/null), people(数字), state("normal"/"tired"/"low_patience"/"fitness"/"late_night"/"indulge"), channel("delivery"/"dine_in"/"any")。
用户没提到的字段用 null/[]/默认值(people=1, state="normal", channel="any")。只输出 JSON。"""

FIELD_ORDER = ["goal", "allergens", "diet_taboos", "hated", "budget_max", "eat_by_minutes",
               "spicy", "cuisines", "novelty", "people", "state", "channel"]


def load_rows(path: str, task: str = "nlu") -> list[dict]:
    """nlu: {utterance, target} → 抽取 SFT；scorer: {system, user, scores} → Actor 蒸馏 SFT。"""
    rows, seen = [], set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if task == "messages":  # 预构建 {messages:[...]}（多任务混合数据集）
            rows.append({"messages": r["messages"]})
            continue
        if task == "scorer":
            key = r["user"] + r["agent"]
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "messages": [
                    {"role": "system", "content": r["system"]},
                    {"role": "user", "content": r["user"]},
                    {"role": "assistant", "content": json.dumps(r["scores"], ensure_ascii=False)},
                ]
            })
            continue
        utt = r["utterance"].strip()
        if utt in seen:
            continue
        seen.add(utt)
        target = {k: r["target"].get(k) for k in FIELD_ORDER}
        rows.append({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": utt},
                {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
            ]
        })
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--data", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--epochs", type=float, default=2.0)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--lora-r", type=int, default=16)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--grad-accum", type=int, default=2)
    p.add_argument("--max-len", type=int, default=1024)
    p.add_argument("--task", choices=["nlu", "scorer", "messages"], default="nlu")
    args = p.parse_args()

    if args.task == "scorer":
        args.max_len = max(args.max_len, 2048)  # 候选列表上下文更长
    rows = load_rows(args.data, args.task)
    print(f"train rows (deduped): {len(rows)}")
    ds = Dataset.from_list(rows)

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForCausalLM.from_pretrained(args.base, dtype="bfloat16", device_map="cuda")

    peft_cfg = LoraConfig(
        r=args.lora_r, lora_alpha=args.lora_r * 2, lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM",
    )
    cfg = SFTConfig(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=10,
        save_strategy="epoch",
        bf16=True,
        max_length=args.max_len,
        report_to="none",
    )
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds,
                         processing_class=tokenizer, peft_config=peft_cfg)
    trainer.train()
    trainer.save_model(args.out + "/adapter")

    print("merging adapter into base for GGUF export...")
    merged = trainer.model.merge_and_unload()
    merged.save_pretrained(args.out + "/merged")
    tokenizer.save_pretrained(args.out + "/merged")
    print("done:", args.out)


if __name__ == "__main__":
    main()
