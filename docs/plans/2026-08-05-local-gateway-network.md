# Local Gateway Network Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reconfigure and flash the connected SID ESP32-S3 head so it reaches the gateway running on the local Mac.

**Architecture:** Keep secrets in an ignored device header, track a matching placeholder example, and compile the existing 1.8-inch firmware without changing its interaction behavior. Verify the result from both serial network events and the gateway health/WebSocket path.

**Tech Stack:** Arduino CLI, ESP32 Arduino core 3.3.11, Waveshare ESP32-S3 AMOLED firmware, Wi-Fi, HTTP, WebSocket.

---

### Task 1: Make the firmware configuration reproducible

1. Expand the example to define all network-profile macros required by the firmware.
2. Confirm the real header is ignored with `git check-ignore`.
3. Compile once to expose configuration or board-option failures.

### Task 2: Compile and flash

1. Compile with the installed ESP32 core and board settings for the connected Waveshare ESP32-S3.
2. Upload to the connected USB serial device.
3. Capture the upload exit status and flash verification result.

### Task 3: Verify the network path

1. Read the 115200-baud serial log.
2. Confirm connection to the 2.4 GHz SSID and a valid DHCP address.
3. Start or verify the SID gateway on `0.0.0.0:8090`.
4. Confirm `/health` responds and the device establishes its WebSocket stream.
5. Confirm `git status` contains no secret or unintended tracked change.
