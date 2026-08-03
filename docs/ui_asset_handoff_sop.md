# UI Asset Handoff SOP

Date: 2026-07-25

This SOP explains how to hand off generated UI art to engineering so the frontend and device simulator can use it without guessing.

## Root Folder

Place small-screen assets here:

```text
assets/ui_small_screen/
```

Use page-number plus function names. Do not use vague folders such as `final`, `new`, `cat`, or `screen`.

```text
assets/ui_small_screen/
  01_idle_start/
  02_profile_setup/
  03_care_profile/
  04_mode_scene_select/
  05_preference_filter/
  06_voice_input/
  07_clarify_question/
  08_cat_council/
  09_council_bubbles/
  10_candidate_list/
  11_choose_yes_no/
  12_blind_box/
  13_qr_order/
  14_receipt_done/
  15_food_journal/
  16_lucky_food/
  17_group_decision/
  18_craving_check/
  19_home_cooking/
  20_food_knowledge_note/
```

## Required Files Per Page

Each page folder should contain:

```text
preview_full.png
bg_no_text.png
layout_reference.png
notes.md
```

Meaning:

| File | Required | Purpose |
|---|---|---|
| `preview_full.png` | yes | Final visual reference, including sample text. Engineers use this to understand the intended composition. |
| `bg_no_text.png` | yes | Background without text. Frontend places real dynamic text on top. |
| `layout_reference.png` | yes | Annotated image showing text zones, button zones, QR zone, and safe margins. |
| `notes.md` | yes | Page purpose, interactions, backend mapping, and asset list. |

## Optional Asset Files

Use transparent PNGs for reusable elements:

```text
cat_idle.png
cat_talking.png
cat_thinking.png
cat_confirm.png
cat_receipt.png
food_current.png
btn_primary.png
btn_left_change.png
btn_right_confirm.png
bubble_left.png
bubble_right.png
icon_budget.png
icon_time.png
icon_safety.png
fx_paw_loading_01.png
fx_paw_loading_02.png
```

Rules:

- File names must be lowercase English with underscores.
- Avoid spaces, Chinese punctuation, brackets, or generated-image timestamps.
- Use `_transparent` only when necessary; transparent PNG is assumed for cutouts.
- Do not bake important text into buttons. Prefer code-rendered text.

## `notes.md` Template

Each page folder should include a short note:

```markdown
# 07 Cat Council

Priority: P0

Purpose:
Show cat agents discussing the user's food decision.

Backend:
- `GET /v1/session/{session_id}/stream`
- Uses `agent_lines`, `auditor_lines`, `display_state`

Interactions:
- No direct button required during council.
- Optional cancel/back can send `cancel`.

Dynamic text zones:
- title: x=24 y=24 w=400 h=44
- speech bubble: x=48 y=238 w=352 h=76

Assets:
- `preview_full.png`
- `bg_no_text.png`
- `cat_taste.png`
- `cat_budget.png`
- `cat_time.png`
- `cat_memory.png`
- `bubble_left.png`
- `fx_paw_loading_01.png`
```

## UI Generation Prompt

Use the full prompt in `docs/gpt_ui_generation_prompt.md` when generating final previews. The short version below is kept as a compact fallback:

```text
Design a complete small hardware screen UI for SID, a healing cat-themed food decision machine running as a local AI hardware product. The screen is landscape 448x368 px with at least 24 px safe margin. It is not a phone app and not a web landing page. The style is warm, cozy, game-like, and readable on a tiny physical screen.

Generate these pages:
01 idle_start
02 profile_setup
03 care_profile
04 mode_scene_select
05 preference_filter
06 voice_input
07 clarify_question
08 cat_council
09 council_bubbles
10 candidate_list
11 choose_yes_no
12 blind_box
13 qr_order
14 receipt_done
15 food_journal
16 lucky_food
17 group_decision
18 craving_check
19 home_cooking
20 food_knowledge_note

Important:
- Keep real text minimal and leave clean areas for code-rendered text.
- Do not draw dense forms.
- Use large readable UI regions.
- Show cats, food, buttons, speech bubbles, QR area, and receipt paper clearly.
- Lucky food is entertainment only, not medical advice or fortune-telling.
- Cycle, heart-rate, breathing, and food-pairing copy must be gentle and non-diagnostic.
- The system never pays automatically; QR is only a phone handoff.
- Output a full preview and a no-text background version for each page.
```

## Text Handling

AI-generated text is often inaccurate. For final implementation:

- Use preview text only as visual guidance.
- Render all real labels, prices, ETA, reasons, QR text, and agent lines in frontend/device code.
- Keep background art text-free unless the text is decorative and not functionally important.

## Safe Areas

For `448 x 368` art:

- Top safe area starts at `y=24`.
- Bottom controls should not go below `y=344`.
- Left/right content should stay inside `x=24` and `x=424`.
- Keep QR code at least `120 x 120 px` if shown on page 10.
- Avoid placing text in rounded screen corners.

## Handoff Checklist

- [ ] Every page folder exists.
- [ ] Every page has `preview_full.png`.
- [ ] Every page has `bg_no_text.png`.
- [ ] Every page has `layout_reference.png`.
- [ ] Every page has `notes.md`.
- [ ] Dynamic text areas are marked.
- [ ] Button/hit areas are marked.
- [ ] QR area is marked on page 10.
- [ ] All important text is planned for code rendering.
- [ ] No file name uses spaces or generated timestamps.
- [ ] P0 pages are complete before P1/P2 polish.
