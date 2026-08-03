# mmWave Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Feed real MR60BHA2/XIAO mmWave readings into the Cat.TV H5 hunger-check feature without modifying the working main-board firmware.

**Architecture:** Add a small sensor cache to `services/device_gateway/main.py`, expose it through `/v1/sensor/mmwave`, and let `/v1/hungry` use fresh readings when available. Add a local serial bridge script that parses the kit's USB serial logs and posts samples to the gateway.

**Tech Stack:** FastAPI, Python standard library, pytest/TestClient, macOS USB serial.

---

### Task 1: Backend Sensor Contract

**Files:**
- Modify: `tests/test_core.py`
- Modify: `services/device_gateway/main.py`

**Step 1:** Write a failing TestClient test that posts a real-looking mmWave sample and asserts `/v1/hungry` includes `sensor.fresh == True`, heart rate, respiration, distance, and an entertainment decision.

**Step 2:** Run the targeted test and verify it fails because the endpoint does not exist or hungry ignores the sample.

**Step 3:** Add the sensor cache, `/v1/sensor/mmwave`, and mmWave-aware hungry response.

**Step 4:** Run the targeted test and existing core tests.

### Task 2: Serial Bridge

**Files:**
- Create: `scripts/mmwave_bridge.py`

**Step 1:** Add parser tests or a parse helper exercised by the backend test path if practical.

**Step 2:** Implement a standard-library serial reader using `termios`, regex parsing, and `urllib.request` POSTs.

**Step 3:** Document the local command in the final response.
