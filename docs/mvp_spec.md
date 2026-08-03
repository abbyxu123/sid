# SID Product MVP Spec

Date: 2026-08-03

This document is the product baseline after the competition phase. It keeps the full product ambition visible while separating the first shippable hardware loop from later branches.

## Product Positioning

SID is a small AI hardware companion for food memory and daily meal decisions. It helps the user answer "what should I eat now?", records what happened, and uses explicit preferences, context, and optional sensors to make the next decision easier.

The first product must feel like a real object, not just a web demo:

- Cat-head or cat-terminal hardware shape.
- Small screen with glanceable states.
- Voice-first input.
- Physical confirm/change controls.
- Food memory and gentle care profile.
- Optional body-state sensing that stays advisory, never diagnostic.

## First Product Loop

```text
User is unsure what to eat
→ wakes SID
→ speaks budget, mood, time, dislikes, allergy, scene, or vague craving
→ SID extracts constraints
→ hard rules remove unsafe or impossible candidates
→ scoring agents compare taste, budget, time, distance, memory, and care context
→ SID shows one or more explainable recommendations
→ user changes or confirms
→ SID creates QR/order/navigation handoff
→ user gives feedback
→ memory updates for the next decision
```

## Priority Levels

| Priority | Scope | Meaning |
|---|---|---|
| P0 | First reliable hardware loop | Must run end to end on a desk device or simulator. |
| P1 | Product coherence | Needed for a believable daily-use product. |
| P2 | Expansion branches | Useful for travel, fitness, family, and advanced sensing after the first loop is stable. |

## Feature Scope

| Feature | Priority | Current status | Product note |
|---|---|---|---|
| Idle opening screen | P0 | Supported | Shows SID waiting and ready to listen. |
| Voice input | P0 | Gateway endpoint exists | Hardware audio path needs noise suppression and UX polish. |
| Text input fallback | P0 | Supported | Useful for simulator, H5, and ASR failure. |
| Hard food constraints | P0 | Supported | Allergies, budget, time, disliked ingredients, and taboos must stay deterministic. |
| Recommendation scoring | P0 | Supported | Taste, budget, time, novelty, distance, and memory signals. |
| Recommendation audit | P0 | Supported | Final safety gate before display/handoff. |
| Confirm/change controls | P0 | Supported | UI and hardware event paths should be equivalent. |
| QR handoff | P0 | Supported | Handoff only; no automatic payment. |
| Food memory ledger | P0 | Supported | Local development data is ignored by git. |
| Small-screen simulator | P0 | Supported | Used for fast UI and API validation. |
| ESP32-S3 firmware | P0 | Supported variants | Needs ongoing device QA and enclosure-aware input tuning. |
| Profile and care profile | P1 | Partial/missing | Optional name, dietary notes, care state, cycle/fitness context. |
| Missing-field follow-up | P1 | Missing | Ask one concise question when a hard decision field is absent. |
| Food journal | P1 | Partial | Morning/noon/evening meal memory and feedback view. |
| Camera/phone image record | P1 | Planned | Start with phone/upload path before embedding a camera. |
| Environment noise handling | P1 | Hardware/software task | AFE/VAD/noise suppression required before open-space use. |
| mmWave wellness signal | P2 | Bridge design exists | Advisory presence, respiration-like, heart-rate-like context only. |
| Location context | P2 | Planned | Phone-assisted first; standalone GNSS/LTE-M only if outdoor use demands it. |
| Travel/business trip mode | P2 | Planned | Hotel, nearby restaurants, time windows, fatigue context. |
| Fitness/sport mode | P2 | Planned | Recovery-friendly food suggestions, no medical claims. |
| Family/child mode | P2 | Planned | Guardian-controlled logging and location, privacy-first. |
| Women-care mode | P2 | Planned | User-entered cycle/care notes, no diagnosis or fertility claims. |

## Hardware MVP

First build should stay modular:

- ESP32-S3 AMOLED board for screen, Wi-Fi, buttons, haptic, and basic audio.
- External or board-supported microphone path with AFE/VAD/noise suppression.
- Speaker or haptic feedback for short interaction cues.
- Optional Seeed/XIAO mmWave kit bridged over serial before custom PCB integration.
- Phone-assisted photo and location workflows before embedded camera/GNSS decisions.

Custom hardware should wait until the first loop proves daily value. The custom phase should solve enclosure, cat-ear mechanism, acoustic cavity, antenna placement, battery and charging, sensor placement, heat, assembly, and manufacturability.

## Safety And Privacy Boundaries

- No medical diagnosis from food, mmWave, heart-rate-like, respiration-like, cycle, or fitness data.
- No automatic ordering or payment.
- No hidden external action without user confirmation.
- No model may override hard constraints.
- Keep `.env`, local ledger, Wi-Fi credentials, device config, model weights, and raw private data out of git.
- For child/family use, guardian control and privacy design are required before any outdoor positioning feature ships.

## Acceptance Criteria

- A new user can complete the P0 meal-decision loop without touching code.
- The device always shows a clear next action.
- Every recommendation has visible reasons and visible safety boundaries.
- Confirm/change works from both simulator and device event paths.
- Feedback changes later memory behavior or appears in the ledger.
- If model services are unavailable, deterministic fallback still produces a safe recommendation.
- The repo can be cloned publicly without secrets, private data, model weights, or competition-only artifacts.
