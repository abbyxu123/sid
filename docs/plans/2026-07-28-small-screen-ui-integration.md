# Small Screen UI Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the chaotic current small-screen flow with a reliable refined-pixel CatTV/SID food decision experience while preserving the working Wi-Fi, voice, WebSocket, and QR paths.

**Architecture:** Keep the current ESP32-S3 firmware and backend protocol stable. Add a curated small-screen asset pipeline, convert only selected P0 assets into firmware-ready LVGL images, and update the firmware UI state machine around the existing backend states. Use fallback pixel-cat rendering if rich assets fail or exceed flash limits.

**Tech Stack:** ESP32-S3 Arduino, LVGL 8.3, Arduino_GFX, WebSocketsClient, FastAPI device gateway, Python/Pillow or local image tooling for asset processing.

---

### Task 1: Create Fine-Pixel Home Screen Visual Test

**Files:**
- Create: `assets/ui_small_screen/tests/`
- Create: `assets/ui_small_screen/tests/home_fine_pixel_test.png`
- Modify: `docs/ui_screen_asset_map.md`

**Step 1: Generate or process one visual test**

Create a 448x368 home screen mockup with:

- Fine-pixel robot cat.
- Large code-rendered text zones for `今天吃什么？`.
- Two button zones: `开始决定`, `我饿不饿`.
- Small local AI host-ready status area.

**Step 2: Inspect image**

Validate:

- Text zones are clear.
- Buttons are large enough for touch.
- Pixel detail is fine, not coarse.
- No important content is outside safe margins.

**Step 3: Document decision**

Update `docs/ui_screen_asset_map.md` with whether the test style is approved or needs revision.

### Task 2: Build Curated Asset Workspace

**Files:**
- Create: `assets/ui_small_screen/source_2026_07_28/`
- Create: `assets/ui_small_screen/processed/`
- Create: `assets/ui_small_screen/firmware_ready/`
- Create: `assets/ui_small_screen/README.md`

**Step 1: Copy selected source assets only**

Copy the selected P0 source assets from:

```text
/Users/beibeixv/Desktop/1.8尺寸UX UI- codex前端/
```

Do not copy the entire 132MB pack unless repository storage is intentionally accepted.

**Step 2: Add README**

Document:

- Source path.
- Selected assets.
- Conversion target sizes.
- Firmware inclusion rules.

### Task 3: Process P0 Visual Assets

**Files:**
- Create: `scripts/process_ui_assets.py`
- Create: `assets/ui_small_screen/processed/*.png`

**Step 1: Write processing script**

The script should:

- Crop backgrounds to 448x368.
- Resize cat sprites to 80-120 px height.
- Resize food sprites to candidate-card sizes.
- Preserve alpha where present.
- Produce deterministic output names.

**Step 2: Run script**

Run:

```bash
python3 scripts/process_ui_assets.py
```

Expected:

- Processed images are created.
- Dimensions match the map.
- Alpha is preserved for sprites.

### Task 4: Convert Minimal Firmware Images

**Files:**
- Create: `firmware/esp32_amoled18/noon_cat_amoled18/ui_assets_generated.c`
- Create: `firmware/esp32_amoled18/noon_cat_amoled18/ui_assets_generated.h`
- Modify: `firmware/esp32_amoled18/noon_cat_amoled18/noon_cat_amoled18.ino`

**Step 1: Convert only P0 assets**

Convert:

- 1 home/standby background.
- 1 council background.
- 1 receipt/QR card background if needed.
- 4-6 cat sprites.
- 4-8 food or box sprites if flash permits.

**Step 2: Compile**

Run Arduino compile for the known ESP32-S3 board profile.

Expected:

- Sketch remains within flash limits.
- PSRAM allocation still succeeds.

### Task 5: Refactor Firmware UI States

**Files:**
- Modify: `firmware/esp32_amoled18/noon_cat_amoled18/noon_cat_amoled18.ino`

**Step 1: Add screen enum**

Represent device UI screens separately from backend states:

- `SCREEN_STANDBY`
- `SCREEN_HOME`
- `SCREEN_LISTENING`
- `SCREEN_STRUCTURING`
- `SCREEN_COUNCIL`
- `SCREEN_CANDIDATE`
- `SCREEN_BLIND_BOX`
- `SCREEN_QR`
- `SCREEN_DONE`
- `SCREEN_ERROR`

**Step 2: Add screen render functions**

Create small render functions:

- `renderStandby()`
- `renderHome()`
- `renderListening()`
- `renderCouncil()`
- `renderCandidate()`
- `renderQr()`
- `renderError()`

**Step 3: Preserve fallback**

Keep `setPixCat()` and `animateCat()` as fallback/status layer.

### Task 6: Fix Interaction Flow

**Files:**
- Modify: `firmware/esp32_amoled18/noon_cat_amoled18/noon_cat_amoled18.ino`
- Reference: `docs/api_contract.md`

**Step 1: Update touch behavior**

Implement:

- Standby tap -> home only.
- Home left/right zones choose main mode.
- Voice page expects long press to record.
- Candidate left -> `left_ear`.
- Candidate right -> `right_ear`.
- QR/done right -> continue/finish.

**Step 2: Gate shake**

Shake should work only on candidate or blind-box screens.

**Step 3: Keep network escape hatch**

Bottom long press on offline/error continues to switch Wi-Fi profile.

### Task 7: Verify Backend And Device Loop

**Files:**
- Test existing gateway and firmware.

**Step 1: Start gateway**

Run the existing device gateway command with local model disabled or configured as available.

**Step 2: Health check**

Run:

```bash
curl http://127.0.0.1:8090/health
```

Expected:

- `gateway` is `ok`.
- Device count appears when board connects.

**Step 3: Serial monitor**

Confirm:

- Wi-Fi connects.
- WebSocket connects.
- Voice frames show nonzero peaks.
- Candidate and done states arrive.

### Task 8: Compile, Upload, And Field-Test

**Files:**
- Firmware sketch and generated assets.

**Step 1: Compile**

Use the known Arduino CLI board profile.

Expected:

- Compile passes.
- Binary remains inside partition size.

**Step 2: Upload**

Upload to the ESP32-S3 over the connected USB port.

**Step 3: Run product walkthrough**

Test:

- Home screen appears.
- Long press records.
- Voice result reaches council/candidate.
- Left/change works.
- Right/confirm works.
- QR appears.
- Error path allows retry.
- Offline/error bottom long press switches network.

### Task 9: Update Demo Docs

**Files:**
- Modify: `docs/mvp_spec.md`
- Modify: `docs/hardware_integration.md`
- Modify: `docs/product_draft.md`

**Step 1: Add field runbook**

Document:

- Power-on order.
- Wi-Fi profile behavior.
- Button map.
- Product walkthrough notes.
- Fallback steps if voice/network fails.

**Step 2: Add technical narrative**

Make the product story explicit:

- local AI workstation/local AI as decision center.
- local AI hardware positioning.
- Stepfun/local AI host model usage where configured.
- ESP32-S3 as tactile multimodal front end.

Do not include private strategy notes.
