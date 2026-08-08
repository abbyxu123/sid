# Backend Gap TODO For CatTV MVP

Date: 2026-07-25

This document lists what the current backend already supports and what must be added so the small-screen MVP can match the product flow in `docs/mvp_spec.md`.

## Current Backend Capabilities

The existing backend already supports the core decision loop:

- `POST /v1/session`: create a decision session.
- `POST /v1/input`: accept text and/or structured food preferences.
- `POST /v1/voice`: accept raw voice input and route simple "confirm/change" commands.
- `hard_constraints`: allergens, diet taboos, hated items, budget max, eat-by minutes.
- `soft_preferences`: spicy level, cuisine preferences, temperature, novelty.
- `context`: location, time, people count, state, delivery/dine-in/any channel.
- deterministic hard-rule filtering before model scoring.
- cat council state and agent lines through SSE.
- candidate recommendation and cursor browsing.
- `POST /v1/device/event`: `left_ear`, `right_ear`, `both_ears`, `cancel`.
- `POST /v1/confirm`: returns action URL/app URL after user confirmation.
- `POST /v1/feedback`: records rating, repeat intent, and reject reason.
- `/v1/device/stream`: pushes small-screen device frames through WebSocket.
- `/sim` and `/console`: simulator and web control surfaces.
- `/v1/journal`: exposes existing memory/journal data for an early food-record screen.

## Required Gaps

### 1. UserProfile

Priority: P1

Purpose:

- Make the first-time experience feel personal.
- Enable lucky food and long-term memory later.
- Avoid forcing the user to re-enter basic preferences every round.
- Store optional care context such as fitness/diet/cycle preferences without making medical claims.

Suggested data shape:

```json
{
  "user_id": "local-user-01",
  "display_name": "Abby",
  "call_name": "Abby",
  "pronoun": "neutral",
  "birthday": "1998-08-08",
  "birth_time": "08:30",
  "care_profile": {
    "fitness_goal": "none",
    "dieting": false,
    "cycle_tracking_enabled": false,
    "cycle_note": "",
    "care_notes": []
  },
  "long_term_preferences": {
    "allergens": [],
    "diet_taboos": [],
    "hated": [],
    "favorite_cuisines": [],
    "default_budget_max": 40,
    "default_channel": "any"
  }
}
```

Suggested implementation:

- Add a lightweight local profile store first: JSON or SQLite is fine.
- Add `GET /v1/profile?device_id=...`.
- Add `POST /v1/profile`.
- When a session starts, merge profile defaults into empty constraints, but never override explicit user input.

Acceptance:

- A returning user sees their name/call name in UI.
- Default allergies/taboos can be applied before recommendation.
- Explicit session input has higher priority than saved defaults.
- Cycle/fitness/diet fields are optional, user-provided, and never treated as diagnosis.

### 2. Missing-Field Follow-Up

Priority: P1

Purpose:

- If the user says "I have no appetite" but omits important constraints, the cat should ask one short question instead of guessing too much.

Fields to check:

- allergy/taboo/hated item, especially if profile is empty.
- budget, when candidate pool has wide price spread.
- eat-by time, when context implies urgency.
- channel: delivery/dine-in/any, if unclear.
- scene: home cooking / delivery / dine out / any.
- distance radius, when delivery or dine-in is selected.
- people count, if group mode is selected.

Suggested response addition:

```json
{
  "state": "needs_clarification",
  "missing_fields": ["budget_max"],
  "question": "今天预算大概多少？",
  "quick_replies": ["30以内", "40以内", "60以内", "随便"]
}
```

Implementation note:

- The current `SessionState` enum does not include `needs_clarification`. Either add it in schema v1.1, or use `structuring` plus a `missing_fields` field in the session response.
- Keep only one question on the small screen at a time.

Acceptance:

- If required constraints are missing, UI can show page `06_clarify_question`.
- User quick reply can call `/v1/input` again with structured fields.

### 3. Blind Box Mode

Priority: P1

Purpose:

- User wants a game-like takeout blind box: the system pre-filters safe choices, hides the names, and lets the user open one.
- The blind box should feel exciting, but it must not violate allergies, taboos, budget, or time.
- If the user has selected several acceptable dishes first, blind box should pick only from that selected subset.

Suggested behavior:

```text
Input constraints
→ run hard-rule filtering
→ rank safe candidates
→ return 4 or 6 hidden boxes
→ user opens one
→ reveal dish
→ user can confirm / send to friend / play again
```

Suggested data shape:

```json
{
  "mode": "blind_box",
  "source": "safe_candidates",
  "boxes": [
    {"box_id": "box_1", "revealed": false, "hint": "warm / rice / medium spicy"},
    {"box_id": "box_2", "revealed": false, "hint": "light / soup / fast"}
  ],
  "safety_summary": ["避开花生", "40元以内", "30分钟内"]
}
```

Temporary implementation:

- Reuse `soft_preferences.novelty = "bold"` and existing `DecisionMode.explore`.
- Frontend can hide the returned candidates as boxes.
- If user-selected candidates exist, frontend can run the random reveal locally for the first product prototype.

Later implementation:

- Add a real `blind_box` decision mode and reveal endpoint.
- Add optional selected candidate IDs:

```json
{
  "session_id": "sess_xxx",
  "selected_candidate_ids": ["r01", "r08", "r11"],
  "box_count": 4
}
```

Acceptance:

- Blind box candidates all pass hard rules.
- The UI can show 4/6 covered options.
- Revealed option can still go through normal confirm and QR order handoff.

### 4. Lucky Food Mode

Priority: P2

Purpose:

- Give a healing "today's lucky food/color" result based on user profile, date, mood, and safe candidate pool.
- This is entertainment and decision flavor, not fortune-telling or health diagnosis.

Suggested data shape:

```json
{
  "mode": "lucky_food",
  "lucky_color": "green",
  "lucky_food": "avocado chicken salad",
  "reason": "今天适合清爽一点，减少选择负担。",
  "candidate_id": "r18_salad",
  "disclaimer": "娱乐建议，仅供点餐参考"
}
```

Implementation note:

- If using birth date/time or five-element language, keep it soft: "food inspiration", "lucky color", "gentle suggestion".
- Do not say the system diagnosed heatiness, illness, or hunger.
- Always choose from safe candidates after hard-rule filtering.

Acceptance:

- UI page `13_lucky_food` can render lucky color, lucky food, and one short reason.
- The result can continue to normal confirm/QR flow.

### 5. Group Decision Mode

Priority: P2

Purpose:

- 2-4 people are together and do not know what to eat.
- Each person can enter basic dislikes/allergies/wants. The system finds a compromise.
- Larger groups such as class/company should use group-level controls instead of requiring every person to fill a profile.

Suggested data shape:

```json
{
  "mode": "group_decision",
  "people": [
    {"name": "A", "allergens": [], "hated": ["noodles"], "wants": ["spicy"]},
    {"name": "B", "allergens": ["peanut"], "hated": [], "wants": ["fast"]}
  ],
  "shared_context": {
    "budget_max_per_person": 40,
    "channel": "delivery",
    "max_distance_m": 5000,
    "eat_by_minutes": 30
  }
}
```

Merge rules:

- Allergies and taboos are unioned as hard constraints.
- Budget uses the lowest explicit budget unless group budget is provided.
- Soft wants become scoring preferences, not hard rules.
- Explain the compromise in one sentence.

Acceptance:

- UI page `14_group_decision` can show each person's chips and final compromise.
- Any allergy from any person blocks unsafe candidates.

### 6. Dining Scene And Distance Radius

Priority: P1

Purpose:

- The same user may want delivery, dine-out, cook-at-home, or "anything".
- Delivery and dine-out need distance preference: nearby, 1 km, 5 km, 10 km, or no limit.

Current status:

- Existing `Context.channel` supports `delivery`, `dine_in`, and `any`.
- Existing `Candidate` includes `distance_m`, `queue_minutes`, and `channel`.

Suggested additions:

```json
{
  "context": {
    "people": 1,
    "state": "normal",
    "channel": "delivery",
    "scene": "delivery",
    "max_distance_m": 5000,
    "group_scale": "solo"
  }
}
```

Implementation note:

- If schema changes are too slow, frontend can encode radius in text first: "5公里以内外卖".
- For the first product prototype, filter by `distance_m` in rule scoring if candidate data has distance.

Acceptance:

- User can select delivery/dine-out/home/any.
- User can select distance radius for delivery/dine-out.
- Distance preference affects candidate display or at least agent explanation.

### 7. mmWave Status

Priority: P2

Purpose:

- Use the XIAO ESP32 C6 + MR60BHA2 mmWave kit as a presence/state signal for companion behavior.
- First version should use it to wake the screen, detect nearby user presence, and add soft context.
- Home screen can expose a playful "Am I hungry?" entry that combines meal history, user goal, and optional sensor context.

Do not claim:

- "The sensor knows the user is hungry."
- "The sensor diagnosed stress, illness, or health state."
- "Heart/breath data is medically accurate."

Suggested event shape:

```json
{
  "device_id": "mmwave-01",
  "near_device": true,
  "presence": "present",
  "motion_level": "low",
  "breathing_rate": 16,
  "heart_rate": 78,
  "confidence": 0.72,
  "timestamp": 1784212345
}
```

Suggested endpoint:

- `POST /v1/sensor/mmwave`
- `GET /v1/sensor/mmwave/latest`

Product use:

- Wake screen when user approaches.
- If meal history says user has not eaten for many hours, gently ask whether they want help choosing food.
- If history says the user ate recently, show a playful "hungry or just craving?" screen.
- If the user selected fitness/diet mode, use gentler self-discipline copy rather than shaming.

Acceptance:

- Sensor data is optional. The main food decision flow works without it.
- UI page `15_craving_check` can render a soft companion message from latest status/history.
- Copy never claims that heart rate or breathing proves hunger.

### 8. Food Journal

Priority: P1

Purpose:

- Users should be able to browse what they ate like a small book/handbook.
- Memory Cat should use this history when explaining recommendations.

Current status:

- `/v1/journal` exists.
- Ledger records choices and feedback.

Suggested response shape for small screen:

```json
{
  "days": [
    {
      "date": "2026-07-25",
      "meals": [
        {"slot": "morning", "item": "soy milk", "note": "light"},
        {"slot": "noon", "item": "spicy chicken rice", "note": "liked"},
        {"slot": "evening", "item": "salad", "note": "balanced"}
      ]
    }
  ]
}
```

Implementation note:

- First product prototype can group existing ledger entries by date.
- Later version can infer morning/noon/evening from timestamp.

Acceptance:

- UI page `16_food_journal` can flip between days/meals.
- Recommendation can mention a simple memory note, e.g. "you had noodles yesterday."

### 9. Home Cooking Suggestion

Priority: P2

Purpose:

- If the user chooses "cook at home", CatTV should still decide what to eat instead of only linking to delivery.
- It can suggest a simple meal direction based on memory, preferences, and dietary variety.

Suggested data shape:

```json
{
  "mode": "home_cooking",
  "suggestion": {
    "item": "tomato egg rice",
    "effort": "easy",
    "reason": "最近蔬菜偏少，今天补一点清爽的。",
    "ingredients": ["tomato", "egg", "rice"]
  }
}
```

Implementation note:

- Do not require full recipe generation for MVP.
- A small local list of home-cooking suggestions is enough.

Acceptance:

- UI page `17_home_cooking` can render one home-cooking suggestion.
- The suggestion still respects allergies/taboos/hated items.

### 10. Food Pairing Knowledge Note

Priority: P2

Purpose:

- Provide a gentle local note when a known food pairing/timing reminder is relevant.
- This should be a curated knowledge base, not open-ended medical advice.

Suggested rule shape:

```json
{
  "rule_id": "local_note_001",
  "trigger_tags": ["alcohol", "medicine"],
  "severity": "info",
  "message": "如果正在服药，饮酒前请先确认药品说明或问医生。",
  "source": "curated_local_rule"
}
```

Implementation note:

- Use conservative copy.
- Do not show uncertain or alarming rules.
- If the note touches medicine, pregnancy, allergies, or chronic illness, tell the user to check professional guidance.

Acceptance:

- UI page `18_food_knowledge_note` can show one short note.
- The note never blocks the P0 recommendation unless it is also a hard constraint such as an allergy.

### 11. QR Order Handoff

Priority: P0

Current status:

- `POST /v1/confirm` returns `url` and `app_url`.

Frontend work:

- Generate a QR code from `url`.
- Show a fallback text/link if QR generation fails.
- If inside a blocked browser environment, tell the user to open in system browser.

Backend work:

- No new backend is required for the first implementation.
- Optional later route: `/order/{session_id}` can show a phone-friendly handoff page.

Acceptance:

- User confirmation never triggers payment.
- QR points to a human-controlled order/navigation step.

## Product Positioning Boundary

Keep all docs and UI copy aligned with this version:

- Local AI hardware product.
- Local model service plus trained small "kitten" model.
- Multi-agent decision architecture.
- Hardware/simulator screen.

Avoid:

- Other cloud-model-provider positioning.
- Any claim that a cloud API is required for the core product loop.

## Engineer Checklist

- [x] Add profile storage and profile API.
- [x] Add optional basic care profile fields; expand only with explicit consent UX.
- [x] Add one missing-field follow-up response; a dedicated schema state remains optional.
- [x] Add dining scene, people count, and distance controls to H5/context payloads.
- [x] Make filtered random/explore mode renderable from safe candidates.
- [ ] Support optional selected-candidate blind box.
- [ ] Add lucky food response shape or stub data.
- [ ] Add group decision payload design before implementation.
- [x] Add optional mmWave presence sensor endpoint.
- [x] Add day grouping support on top of `/v1/journal`; small-screen rendering remains.
- [ ] Add home-cooking suggestion mode or local stub.
- [ ] Add curated food-pairing note data shape.
- [x] Ensure QR handoff and post-idle receipt recovery exist in frontend.
- [ ] Keep UI implementation aligned with the canonical page/state mapping.
- [x] Keep payment and health boundaries explicit.
