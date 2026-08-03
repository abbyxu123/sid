# Small Screen UX Flow

Date: 2026-07-25

This document describes the small hardware screen experience for CatTV. It is for UI generation, frontend implementation, and hardware/simulator alignment.

## Screen Target

New UI design target:

- Canvas: `448 x 368 px`
- Orientation: landscape
- Safe margin: at least `24 px`
- Avoid dense text. Important text should be rendered by code, not baked into AI-generated images.

Compatibility note:

- The current repo simulator `/sim` still describes a 480x480 square board.
- New art should be produced in the 448x368 landscape target first.
- Engineering can either adapt `/sim` to landscape or letterbox the landscape UI during hardware integration.

## Experience Rhythm

The screen should feel like a tiny cat machine, not a phone app:

```text
invite
→ choose "what to eat" or "am I hungry"
→ collect only what matters, mostly by voice
→ listen
→ ask one follow-up if needed
→ council theater
→ clear recommendation or short list
→ simple physical choice
→ optional blind-box final pick
→ phone handoff
→ receipt, journal, and memory
```

Use short captions and large visual states. The cat should carry emotion; the interface should not explain itself with long text.

## Page List

| Page | Folder name | Priority | Main action | Backend mapping |
|---|---|---|---|---|
| 01 | `01_idle_start` | P0 | Start decision | `POST /v1/session`, `idle` |
| 02 | `02_profile_setup` | P1 | Save name/profile | future `/v1/profile` |
| 03 | `03_care_profile` | P1 | Save optional care state | future `/v1/profile.care_profile` |
| 04 | `04_mode_scene_select` | P1 | Choose decision mode, dining scene, distance | normal now; blind/lucky/group/hungry planned |
| 05 | `05_preference_filter` | P0 | Set food constraints, people count, distance | `POST /v1/input` structured fields |
| 06 | `06_voice_input` | P0 | Speak/type today's thought | `POST /v1/input` or `/v1/voice` |
| 07 | `07_clarify_question` | P1 | Answer one missing field | future `missing_fields` response |
| 08 | `08_cat_council` | P0 | Watch agents discuss | `GET /v1/session/{id}/stream`, `council` |
| 09 | `09_council_bubbles` | P0 | Dynamic speech-bubble close-up | `agent_lines`, `auditor_lines` |
| 10 | `10_candidate_list` | P0 | Read recommendations or short list | `candidate` frame/session candidates |
| 11 | `11_choose_yes_no` | P0 | Change or confirm | `/v1/device/event` left/right |
| 12 | `12_blind_box` | P1 | Open hidden safe option | planned `blind_box`, temporary `explore` |
| 13 | `13_qr_order` | P0 | Scan with phone | `/v1/confirm` result URL |
| 14 | `14_receipt_done` | P0 | Receipt and feedback | `done`, `/v1/feedback` |
| 15 | `15_food_journal` | P1 | Browse meal history as a book | existing `/v1/journal`, needs small-screen view |
| 16 | `16_lucky_food` | P2 | See lucky food/color | planned `lucky_food` |
| 17 | `17_group_decision` | P2 | Merge 2-4 people's preferences | planned `group_decision` |
| 18 | `18_craving_check` | P2 | Hungry vs craving companion hint | planned `mmwave_status` |
| 19 | `19_home_cooking` | P2 | Home-cooking suggestion | planned home-cooking mode |
| 20 | `20_food_knowledge_note` | P2 | Food pairing/timing note | planned local knowledge base |

## Page Details

### 01 Idle Start

Purpose:

- First visual impression.
- Cat is waiting, slightly cheeky and warm.

UI:

- Main cat character.
- Large title: "What should I eat?"
- Two large choices:
  - "Pick food"
  - "Am I hungry?"
- One visible voice/paw wake affordance.
- Optional small status: local AI ready / offline fallback.

Backend:

- Creates or resumes session.
- Shows `idle` frame until user starts.

### 02 Profile Setup

Purpose:

- Personalize later lines and memory.

UI:

- Name/call-name field.
- Optional pronoun/call style: female, male, neutral, or skip.
- Optional birthday and birth time for later lucky food.
- Skip should be visible.

Backend:

- Future `UserProfile`.
- Do not block P0 flow if skipped.

### 03 Care Profile

Purpose:

- Store optional self-reported state that can make recommendations feel more considerate.

UI:

- Optional care chips: fitness, dieting, regular meals, light food, spicy lover, period care.
- Cycle note only appears for users who choose to track it.
- Everything is skippable.
- Use privacy-safe, gentle visual language.

Backend:

- Future `UserProfile.care_profile`.
- Never treat care fields as diagnosis.

### 04 Mode And Scene Select

Purpose:

- Let the user choose why they are here.

Modes:

- Normal decision: "Just decide for me."
- Blind box: "Open a safe mystery meal."
- Lucky food: "Today's lucky food."
- Group decision: "We are eating together."
- Hunger/craving check: "Am I hungry?"

Dining scene choices:

- Delivery.
- Dine out.
- Cook at home.
- Any.

Distance choices for delivery/dine-out:

- Nearby / 1 km.
- 5 km.
- 10 km.
- No limit.

Backend:

- Normal decision uses existing flow.
- Blind box can temporarily use `novelty = "bold"` / `explore`.
- Lucky and group can render as concept screens until endpoints exist.

### 05 Preference Filter

Purpose:

- Capture non-negotiable rules before agents recommend food.

UI fields:

- Spice: none / mild / medium / hot.
- Avoid: allergy, taboo, disliked food.
- Budget.
- Time to eat.
- People count: 1, 2, 3-4, group, class/company.
- Channel: delivery / dine-in / home / any.
- Distance radius when delivery/dine-in is selected.
- Current state: normal, tired, fitness, diet, period care, low patience.

Backend:

- Maps to `hard_constraints`, `soft_preferences`, and `context`.
- Hard constraints are stronger than model output.

### 06 Voice Input

Purpose:

- Let users say the fuzzy part: mood, appetite, or "I don't know".

Examples:

- "I want something spicy but not noodles."
- "I have no appetite, pick something light."
- "I'm tired and want something fast."

Backend:

- `POST /v1/input` with text.
- `POST /v1/voice` for voice path.

### 07 Clarify Question

Purpose:

- Prevent the system from guessing important missing constraints.

UI:

- One cat bubble.
- One question only.
- 3-4 quick reply chips.

Examples:

- "Budget today?"
- "Need to eat within how many minutes?"
- "Any allergy I must avoid?"

Backend:

- Future missing-field response.

### 08 Cat Council

Purpose:

- Make the AI decision process visible and emotionally memorable.

UI:

- 8 visible cat roles around a tiny council table.
- 1-2 speech bubbles appear at a time.
- Keep each line short.
- Visible cats should include taste, map/forage, safety/care, memory, time, budget, mood/lucky, and chair.
- Speech bubbles can be playful, but must be grounded in actual constraints.

Suggested timing:

- 4-7 seconds for normal flow.
- Show progress through paw prints or cat portraits.

Backend:

- SSE provides `agent_lines`, `agents`, `auditor_lines`.
- UI may show 8 cats even if backend returns fewer active agents.

### 09 Council Bubbles

Purpose:

- Provide a close-up dynamic state while the council is running.

UI:

- Focus on one or two cats at a time.
- Bubbles appear quickly with short code-rendered lines.
- This can reuse the same background as `08_cat_council`.

Backend:

- Uses the same SSE `agent_lines` and `auditor_lines`.

### 10 Candidate List

Purpose:

- Present the recommendation as a confident next step or a short safe list.

UI:

- Dish image or stylized food icon.
- Name, or a short list of up to 6 safe candidates.
- Price.
- ETA / distance / home-cooking effort.
- One reason.
- One safety summary: "avoided peanuts / under budget / fast".
- If several candidates are shown, user can tap/select acceptable ones before blind box.

Backend:

- Reads `candidate`, `final_choice.reasons`, `risk_flags`, `audit`.

### 11 Choose Yes / No

Purpose:

- Make physical interaction clear.

UI:

- Left: "Change it".
- Right: "This one".
- Visual should align with left/right ear or left/right swipe.

Backend:

- Left sends `left_ear`.
- Right sends `right_ear`, then confirmation flow.

Protocol note:

- Keep backend/hardware convention stable: left means change/reject, right means accept/confirm.

### 12 Blind Box

Purpose:

- A safe gamble: the system already filtered the candidates; the user chooses a hidden box.

UI:

- 4 or 6 covered boxes.
- Tiny hints can be shown without revealing exact dish.
- After open: continue to candidate/confirm flow.
- If the user selected multiple dishes on the recommendation page, boxes should only contain those selected dishes.
- If the user did not select, boxes come from backend safe candidates.

Backend:

- Planned real blind box.
- Temporary: use safe candidates from explore mode.

### 13 QR Order

Purpose:

- Move from hardware to phone without automatic payment.

UI:

- QR code area.
- Short title: "Scan to continue."
- Safety copy: "You confirm on your phone."

Backend:

- `POST /v1/confirm` returns `url` and `app_url`.
- Frontend generates QR code from `url`.

### 14 Receipt Done

Purpose:

- Give closure and memory.

UI:

- Receipt paper.
- Dish, price, ETA.
- Reason and avoided risks.
- Feedback: like / not again / remember this.

Backend:

- Session state `done`.
- `POST /v1/feedback`.

### 15 Food Journal

Purpose:

- Let the user browse meal memory like a small journal/book.

UI:

- Book or receipt album visual.
- Left/right swipe flips days or meals.
- Morning / noon / evening / snack slots.
- Each entry shows food name, date, and quick feeling icon.

Backend:

- Current `/v1/journal` can provide early data.
- Future journal can group entries by day and meal time.

### 16 Lucky Food

Purpose:

- Healing entertainment result.

UI:

- Lucky color.
- Lucky direction may be shown as a playful label if available.
- Lucky food.
- One gentle reason.

Boundary:

- No medical diagnosis.
- No serious fortune-telling claim.
- Always choose a safe candidate.
- Treat metaphysics as a game mechanic similar to horoscope/MBTI-style fun.

### 17 Group Decision

Purpose:

- Several people decide together.

UI:

- 2-4 participant chips.
- Each person: wants / avoids / budget.
- For larger groups, show group-level controls instead of many individual forms.
- Final compromise and why.

Backend:

- Future group payload and merge rules.

### 18 Craving Check

Purpose:

- A playful companion screen using meal history and optional mmWave status.

UI:

- Cat asks whether this is hunger or craving.
- Tone must be funny but not shameful.
- Show simple inputs/status: last meal, current goal, optional sensor status.

Boundary:

- The sensor is not a hunger detector.
- It only provides optional context such as presence or calm/active state.

### 19 Home Cooking

Purpose:

- If the user chooses "cook at home", CatTV recommends a simple meal direction instead of an order link.

UI:

- Home kitchen/cat note visual.
- "You have not eaten vegetables recently" style memory note.
- Simple dish suggestion, effort level, and optional ingredient checklist.

Backend:

- Future home-cooking mode.
- Can initially reuse memory and local candidate data with `channel = home`.

### 20 Food Knowledge Note

Purpose:

- Show a gentle local knowledge reminder after a meal/order when relevant.

UI:

- Small note card or sticky note from Safety/Care Cat.
- One short reminder only.

Boundary:

- This is not medical advice.
- Use curated local rules only.
- Avoid alarming copy. If a rule is uncertain, do not show it.

## Copy Tone

Preferred:

- "Let's steal the decision trouble."
- "One more question."
- "The cats are arguing."
- "This one is safe and fast."
- "Scan to continue on your phone."
- "Hungry, or just craving a little drama?"
- "I can remember this for next time."
- "This is a care note, not a diagnosis."

Avoid:

- "We know you are hungry."
- "You are unhealthy."
- "AI has ordered for you."
- "Fortune says you must eat this."
- "Your heart rate proves you should eat."
- "This food cures period pain."

## UI Implementation Rules

- Render important text in frontend code.
- Keep generated backgrounds text-free where possible.
- Use transparent PNGs for cats, food, buttons, bubbles, and effects.
- Keep button hit areas large.
- Do not rely on tiny labels.
- One primary action per screen.
