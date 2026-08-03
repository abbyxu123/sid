# SID Local Model Training Plan

Goal: keep SID responsive while preserving safety and explainability. Large models can handle hard reasoning, multimodal understanding, and audit. Smaller local models can handle fast structured extraction and routine scoring after supervised fine-tuning.

## Training Targets

### 1. NLU Kitten

Task: convert natural food requests into `DecisionRequest` JSON.

Input examples:

- "想吃点辣的，四十块以内，不要面食。"
- "出差刚到酒店，附近十分钟内，有点累，不想太油。"
- "健身完想补点蛋白，别太贵。"

Output fields:

- `goal`
- `hard_constraints`
- `soft_preferences`
- `context`

Value:

- Keeps voice-first interaction fast.
- Reduces dependence on slow model calls for simple extraction.
- Makes fallback behavior easier to test.

### 2. Scorer Kitten

Task: score candidate foods for taste, budget, time, memory, distance, novelty, and care context.

Value:

- Enables faster "one more option" and "blind box" interactions.
- Lets the larger model focus on conflict resolution and final audit.
- Keeps scoring behavior measurable through regression tests.

### 3. Preference Update

Task: turn feedback and meal history into lightweight preference updates.

Value:

- Reduces repetition.
- Learns spice, texture, cuisine, budget, time, and scene preferences.
- Supports food journal and long-term personalization.

## Data Sources

- Synthetic request/candidate cases in `tests/synthetic_cases/`.
- Food demo data in `skills/food/demo_data/`.
- Training records in `skills/food/kitten/`.
- Future opt-in anonymized product data, after privacy controls are designed.

Do not train on private local ledgers unless they are explicitly exported, reviewed, and sanitized.

## Training Flow

1. Generate or curate labeled examples.
2. Split train/eval sets with no leakage.
3. Fine-tune a small instruction model with LoRA.
4. Export the merged model to a local-serving format.
5. Run extraction and scoring evaluations.
6. Compare against deterministic fallback and larger-model outputs.
7. Enable through a feature flag such as `USE_KITTEN=1`.

## Deployment Shape

- Larger model service: complex reasoning, image/menu understanding, conflict arbitration, and final audit.
- Smaller model service: NLU extraction and routine scoring.
- Deterministic rules: hard constraints, safety gate, and fallback.

The system should remain useful when model services are offline. Safety rules must not depend on model availability.

## Evaluation Metrics

- Field-level extraction accuracy.
- Exact structured-output match.
- Hard-constraint violation rate.
- Recommendation latency.
- Fallback success rate.
- Memory update correctness.
- Regression pass rate.

## Operational Notes

- Keep model weights out of git.
- Keep training logs and evaluation summaries small enough for repository history.
- Store large artifacts externally with clear version notes.
- Use `training/run_stage3.sh` and `training/export_gguf.sh` as development scripts, not production automation.
