"""构建 kitten v2 多任务数据集：NLU 抽取 + 议事会蒸馏评分，一只学徒学两门课。

留出规则：council_labels 里 case_id 数值最大的 --holdout 个 case 不进训练集
（与 scripts/eval_scorer.py 的留出口径一致，防泄漏）。

  python3 scripts/build_mixed_dataset.py \
      --nlu skills/food/kitten/train_verified.jsonl \
      --scorer skills/food/kitten/council_labels.jsonl \
      --holdout 40 --out skills/food/kitten/train_v2_mixed.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))

from train_kitten import FIELD_ORDER, SYSTEM_PROMPT


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--nlu", required=True)
    p.add_argument("--scorer", required=True)
    p.add_argument("--holdout", type=int, default=40)
    p.add_argument("--scorer-repeat", type=int, default=1,
                   help="scorer 样本过采样倍数（样本量远小于 NLU 时用）")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    rows = []
    seen = set()
    for line in Path(args.nlu).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        utt = r["utterance"].strip()
        if utt in seen:
            continue
        seen.add(utt)
        target = {k: r["target"].get(k) for k in FIELD_ORDER}
        rows.append({"messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": utt},
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
        ]})
    n_nlu = len(rows)

    scorer_rows = [json.loads(l) for l in Path(args.scorer).read_text(encoding="utf-8").splitlines()]
    case_ids = sorted({int(r["case_id"]) for r in scorer_rows})
    holdout_ids = set(case_ids[-args.holdout:])
    n_scorer = 0
    for r in scorer_rows:
        if int(r["case_id"]) in holdout_ids:
            continue
        for _ in range(args.scorer_repeat):
            rows.append({"messages": [
                {"role": "system", "content": r["system"]},
                {"role": "user", "content": r["user"]},
                {"role": "assistant", "content": json.dumps(r["scores"], ensure_ascii=False)},
            ]})
            n_scorer += 1

    random.Random(42).shuffle(rows)
    out = Path(args.out)
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"mixed dataset: {len(rows)} rows (nlu={n_nlu}, scorer={n_scorer}, "
          f"holdout_cases={len(holdout_ids)}) -> {out}")


if __name__ == "__main__":
    main()
