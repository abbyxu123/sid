# Small Screen Style And UX Design

Date: 2026-07-28

## Decision

The device UI should use refined pixel art as the main on-screen style, not the current coarse 14x10 block cat and not a pure illustration UI.

The brand should have two connected visual layers:

- Device screen: fine pixel art, dense pixels, high readability, AMOLED-friendly dark backgrounds, warm amber food/home accents, and small local AI-green status signals.
- Pitch/PPT/marketing: more cinematic tech-toy visuals, using the SID hardware shape, cat ears, dark desk scenes, and local AI workstation local AI framing.

This keeps the product from looking like a generic cute food app while still avoiding the low-end feeling of large square blocks.

## Why Not Pure Illustration

Pure illustration is warm and consumer-friendly, but on a 448x368 physical screen it can become heavy, blurry, and harder to animate. It also weakens the "tiny AI gadget" signal that matters for the local AI demo.

Illustration assets remain useful for:

- Standby cover images.
- Web console and simulator visuals.
- product story.
- Source references for generating refined pixel versions.

## Why Not Coarse Pixel Art

The current firmware pixel cat is a good fallback and status indicator, but it is too coarse for the final consumer impression. It uses large visible blocks and cannot carry food, blind-box, scene, or agent-detail richness.

Coarse pixel art should remain only as:

- Emergency fallback if image assets fail.
- Very small state icons.
- Serial/debug-safe boot screen backup.

## Target Pixel Style

Use "fine pixel art" rather than "8-bit pixel art".

Rules:

- Pixel cells should feel around 2-4 logical pixels, not 18-22 px blocks.
- Use rich dithering, small highlights, and readable silhouettes.
- Keep text rendered by firmware fonts, not baked into generated art.
- Use dark backgrounds for AMOLED power and tech feeling.
- Use warm amber/orange for food, home, and primary decisions.
- Use local AI green only as a status or AI-compute accent, not as the whole palette.
- Keep UI touch areas large even if the art is detailed.

## P0 Device Flow

The first reliable field-test flow is:

1. Standby / cover.
2. Home with two entries: "今天吃什么" and "我饿不饿".
3. Voice input.
4. Structuring / "猫猫在想".
5. Cat council.
6. Candidate recommendation.
7. Change or confirm.
8. Optional blind-box when the user is unsure.
9. QR handoff.
10. Meow receipt.

P1/P2 screens should exist as visual-ready states, but they must not block the P0 path.

## Interaction Rules

- Physical long press records voice only when the flow expects voice.
- Physical short press means continue or confirm.
- Left screen side means change/back/reject when that action is valid.
- Right screen side means continue/confirm when that action is valid.
- Shake is disabled globally. It is only active on candidate or blind-box screens.
- Bottom long press in offline/error switches network profile.
- Tapping standby wakes the home screen only; it must not immediately trigger a decision.

## Asset Strategy

Do not upload every raw image directly into firmware.

Use three asset tiers:

- `assets/ui_small_screen/source_2026_07_28/`: selected source references from the provided UI pack.
- `assets/ui_small_screen/processed/`: cropped/resized 448x368 backgrounds and small sprites.
- `firmware/...`: only the small P0 assets converted to LVGL C arrays.

The firmware should initially contain:

- 2-3 full-screen backgrounds maximum.
- 4-6 cat sprites maximum.
- 4-8 food/box sprites maximum.
- Code-rendered labels and buttons.

## Technical Framing

The device UI should make the local AI story visible:

- "local AI host ready" can appear as a small status chip.
- Cat council represents local multi-agent reasoning.
- Voice input and local gateway reinforce hardware-to-local-AI flow.
- The final recommendation should show evidence: taste, time, budget, memory, and safety/care.

Do not imply automatic payment, medical diagnosis, or fortune-telling certainty.

## Acceptance Criteria

- The device can complete the P0 decision flow without a computer terminal visible to judges.
- Home screen has a clear next action.
- Voice failure has a retry path and does not trap the user.
- Candidate screen makes left/change and right/confirm obvious.
- QR screen works from a backend-returned URL.
- Pixel art is detailed enough to support food and blind-box visuals.
- Fallback pixel cat remains available if a rich asset is missing.
