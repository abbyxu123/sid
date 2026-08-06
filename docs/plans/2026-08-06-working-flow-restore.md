# SID Stable Flow Restore Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore the last known-good device flow without discarding validated product fixes.

**Architecture:** Treat the July 29 CatTV ZIP as the behavioral reference and SID as the maintained codebase. Lock each interaction contract with a regression test, apply the smallest state-machine changes, then validate through the real ESP32-S3 and local gateway.

**Tech Stack:** ESP32 Arduino/C++, LVGL, FastAPI, pytest, Arduino CLI, faster-whisper.

---

### Task 1: Lock old timing and interaction contracts

**Files:**
- Modify: `tests/test_device_connectivity.py`
- Reference: `firmware/esp32_amoled18/noon_cat_amoled18/noon_cat_amoled18.ino`
- Reference: `services/device_gateway/main.py`

1. Add failing tests for 60-second standby, no done/listening auto-idle, 2.2g shake threshold, and no forced Wi-Fi reset on WebSocket timeout.
2. Run the focused tests and confirm each fails for the current regression.
3. Add a gateway test proving a new unconstrained session keeps channel `any` and returns multiple candidates.
4. Run it and confirm it fails with the current forced-delivery default.

### Task 2: Restore firmware behavior

**Files:**
- Modify: `firmware/esp32_amoled18/noon_cat_amoled18/noon_cat_amoled18.ino`
- Test: `tests/test_device_connectivity.py`

1. Restore 60-second standby.
2. Restore 2.2g shake sensitivity and 3-second cooldown.
3. Keep Wi-Fi connected while WebSocket reconnects.
4. Run focused tests and confirm they pass.

### Task 3: Restore gateway state lifetime and candidate breadth

**Files:**
- Modify: `services/device_gateway/main.py`
- Test: `tests/test_device_connectivity.py`

1. Remove automatic done and follow-up idle transitions.
2. Stop assigning delivery to every new or revived session.
3. Preserve explicit delivery inferred from speech or supplied context.
4. Run focused tests and confirm they pass.

### Task 4: Verify and flash

**Files:**
- Verify: all changed files

1. Run `python -m pytest -q` and require zero failures.
2. Run `git diff --check`.
3. Compile the ESP32-S3 AMOLED firmware with the existing Arduino CLI profile.
4. Start the gateway persistently and verify port 8090 is listening.
5. Flash the board with upload verification.
6. Exercise voice, next candidate, confirm, QR retention, and shake while recording serial and gateway logs.
