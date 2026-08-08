# SID Product MVP Spec

Date: 2026-08-08

This is the canonical product-flow baseline for SID. It preserves the detailed
MVP journey while keeping the first sellable loop separate from later camera,
mmWave, location, pet, and manufacturing work.

## Product Positioning

SID is a portable AI hardware companion for adult daily life. The removable
cat head goes out with the user; the body base adds charging, speaker, and
stationary sensing at home. The first useful product focuses on food decisions,
food memory, and non-medical wellness context rather than generic emotional
companionship.

The product must feel useful without a phone, and become richer with H5,
mini-program, or international web/app access:

- Small screen with glanceable states and a pixel-cat personality.
- Voice-first input with physical change, confirm, cancel, and shake controls.
- Explicit food constraints, explainable recommendations, and long-term memory.
- QR handoff for detailed phone interaction, navigation, or ordering.
- Optional camera, mmWave, and location context with visible privacy controls.
- Adult human use first; pet identification, food records, behavior events, and
  location are a separate expansion track. There is no child product mode.

## Canonical Journey

```text
idle / wake
-> optional profile and care defaults
-> choose dining scene, people count, distance, time, and budget
-> speak a craving or constraints
-> ask at most one concise high-impact follow-up when required
-> deterministic safety filtering
-> taste, distance, time, memory, and budget agents compare safe candidates
-> show a short explainable candidate list
-> change, re-discuss, or shake within the filtered pool
-> one explicit confirmation
-> QR/H5/order/navigation handoff
-> receipt and feedback
-> journal and long-term preference memory
-> device returns to idle without deleting the phone receipt
```

The latest explicit statement in the current session wins over an old session
or saved preference. Allergies remain hard constraints unless the user edits
the profile directly. A UI selection must merge with spoken details; it must
never cause a spoken allergy, disliked ingredient, or wanted food to disappear.

## Decision Inputs

The decision contract must preserve all of these when provided:

- Wanted food or ingredient, cuisine, temperature, spice, and novelty.
- Extra ingredients and explicit dislikes.
- Allergies and dietary taboos.
- Budget, eat-by time, distance, current location, and queue tolerance.
- One person, two people, or a small group.
- Delivery, dining out, either, and later home cooking.
- Current state such as tired, low patience, fitness context, or late night.
- Optional menu image or food image.
- Saved preferences and recent meal feedback.

Input priority is: current explicit input, current structured controls, saved
profile, then system defaults. Hard constraints always outrank model output.

## Cat Roles

The small screen may compress roles, but the product logic keeps clear ownership:

| Role | Responsibility |
|---|---|
| Chair cat | Chooses direct, council, duel, or explore flow. |
| Taste cat | Wanted food, cuisine, spice, temperature, and extras. |
| Distance cat | Distance, delivery, travel time, and queue context. |
| Time cat | Eat-by deadline and current availability. |
| Budget cat | Total price and budget fit. |
| Memory cat | Recent meals, likes, dislikes, and repeat intent. |
| Safety/care cat | Allergies, taboos, and non-medical care boundaries. |
| Mood/lucky cat | Variety and filtered random choice; never bypasses safety. |

## Screen And Phone Flow

| Step | Surface | Priority | Required behavior |
|---|---|---:|---|
| 01 | Idle/home | P0 | Wake, record, short-press meeting, shake prompt. |
| 02 | Profile | P1 | Optional name and durable food defaults; always skippable. |
| 03 | Care profile | P1 | Optional adult fitness/care context; no diagnosis. |
| 04 | Scene | P1 | Delivery/dine-out/either, people, distance, time, budget. |
| 05 | Preference filter | P0 | Multiple taboos/allergies plus taste shortcuts. |
| 06 | Voice/text | P0 | Record or type natural language; retain the raw statement. |
| 07 | Clarification | P1 | Ask no more than one concise high-impact question. |
| 08 | Council | P0 | Show real agent progress without artificial replay delay. |
| 09 | Candidate | P0 | Show name, price, ETA, source, reason, and safety note. |
| 10 | Choose | P0 | Left/change, right/confirm, both/re-discuss; phone equivalent. |
| 11 | Filtered random | P1 | Shake only among current safe, relevant candidates. |
| 12 | QR handoff | P0 | Remain long enough to scan; return device to idle after 30 s. |
| 13 | Receipt/feedback | P0 | Recover on phone even after device auto-idles. |
| 14 | Food journal | P1 | Meal history, rating, repeat intent, and visible memory. |
| 15 | Hungry check | P2 | Advisory prompt based on recent records, not physiology claims. |
| 16 | Home cooking | P2 | Ingredient/recipe candidate source through the same safe flow. |
| 17 | Group matching | P2 | Shared safe set and taste matching with explicit consent. |
| 18 | Camera record | P1 | User/food/menu capture, local-first where practical. |
| 19 | Wellness context | P2 | Presence/respiration-like/heart-rate-like trends, non-medical. |
| 20 | Pet extension | P2 | Pet identity, food/event memory, behavior and location track. |

## Priority And Current Status

| Capability | Priority | Current status |
|---|---:|---|
| Stable device state machine and idle screen | P0 | Implemented; hardware QA continues. |
| Voice and text input | P0 | Implemented with local ASR fallback. |
| Hard constraints and final safety gate | P0 | Implemented. |
| Local multi-agent decision and explanations | P0 | Implemented without cloud dependency. |
| Candidate change, re-discuss, shake, one-press confirm | P0 | Implemented. |
| QR/H5 handoff and receipt recovery | P0 | Implemented. |
| Feedback and food journal | P0/P1 | Implemented; richer grouping remains. |
| Scene, people, distance, multi-taboo H5 input | P1 | Implemented. |
| Optional profile and care context | P1 | Basic API/H5 implemented; account sync remains. |
| One missing-field follow-up | P1 | Implemented; copy and trigger tuning remain. |
| Menu/food image upload | P1 | Prototype path exists; embedded camera integration remains. |
| Mini-program | P1 | Planned after the responsive web flow is stable. |
| Noise suppression/VAD | P1 | Hardware/software integration task. |
| Home-cooking candidate source | P2 | Planned. |
| mmWave wellness context | P2 | Presence bridge exists; vital-like data integration remains. |
| GNSS/location context | P2 | Planned; phone-assisted and standalone paths stay separate. |
| Group taste matching | P2 | Planned. |
| Pet expansion | P2 | Planned after the human food loop is validated. |

## Hardware MVP

- Removable cat-head core with ESP32-S3 screen, controls, microphone, Wi-Fi,
  haptic/audio cues, battery, and attachment interface.
- Static body base with charging, larger speaker cavity, and mmWave placement.
- Camera module integrated only after framing, privacy indicator, thermal, and
  power tests pass.
- GNSS tested as an optional outdoor module; it is not a substitute for a data
  connection and is not required for food delivery distance.
- Magnetic, hanging, and desktop placements must not block microphone, antenna,
  camera, or radar fields of view.

Custom PCB and enclosure freeze happen only after the software loop, acoustic
path, antenna placement, battery/charging, camera field of view, radar placement,
heat, assembly, and service access are verified together.

## Safety And Privacy Boundaries

- No medical diagnosis or emergency guarantee from food, camera, mmWave,
  heart-rate-like, respiration-like, cycle, fitness, or pet data.
- No automatic ordering or payment; every external action needs confirmation.
- No model or random mode may override allergies or hard constraints.
- Camera and microphone use require visible active state and user control.
- Human/pet identity and raw images are opt-in, deletable, and minimized.
- Keep `.env`, ledgers, credentials, device secrets, model weights, and raw
  private data out of git.

## Acceptance Criteria

- A new adult user can finish the complete P0 loop without touching code.
- Device and H5 always show a clear next action and do not become stuck.
- Spoken details and structured controls survive together in the decision.
- Requesting fish cannot return a candidate with no fish relevance.
- Multiple dislikes/allergies remain active through change, shake, and re-discuss.
- Confirm/change behavior is equivalent on hardware and phone.
- QR remains scannable, the device returns to idle, and the phone receipt remains.
- Feedback appears in the journal and affects later memory behavior.
- With model services offline, local rules still produce a relevant safe result.
- The repository contains no credentials, private user data, or obsolete product claims.
