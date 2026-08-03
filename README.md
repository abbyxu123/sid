# SID｜Cat Decision Hardware

SID is a small-screen AI hardware product for food memory, meal decisions, and gentle body-state awareness. It combines a voice-first device, a local decision backend, food preference memory, optional camera/phone image input, and optional mmWave sensing.

The product direction is simple: help a person decide what to eat, remember what happened, and keep the interaction safe, explainable, and controllable.

## Product Scope

SID is not a event prototype anymore. This repository is the clean product-development baseline for turning the prototype into a real device.

Core product loops:

- Voice-first meal decision: budget, time, distance, taste, allergies, dislikes, care notes, and group context.
- Food memory: meal journal, feedback, repeat avoidance, and preference learning.
- Small-screen hardware UI: idle state, voice capture, council state, recommendation card, confirm/change, QR handoff, and receipt.
- Hardware controls: screen, microphone, speaker, haptic feedback, buttons or ears, IMU, and Wi-Fi gateway connection.
- Optional sensors: mmWave presence, heart-rate-like and respiration-like wellness signals, camera or phone image input, and location context.
- Safety boundaries: no diagnosis, no automatic payment, no overriding allergies or hard constraints, and no hidden action without user confirmation.

## Architecture

```text
SID hardware terminal
  screen / mic / speaker / haptic / buttons / IMU / optional sensors
        |
        | WebSocket + HTTP
        v
Device Gateway (:8090)
  small-screen state frames
  voice/text input endpoints
  sensor cache
  QR/order handoff
        |
        v
Decision OS
  hard constraints
  scoring agents
  memory ledger
  recommendation audit
  local or remote model adapters
```

The current implementation runs without a model service by falling back to deterministic rules. Model-backed extraction, vision, and council behavior can be enabled through the adapters in `core/` and `services/`.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -q
uvicorn services.device_gateway.main:app --host 0.0.0.0 --port 8090
```

Then open:

- `http://localhost:8090/sim` for the board simulator
- `http://localhost:8090/console` for the phone/H5 control surface

## Repository Map

- `core/` - decision schemas, hard constraints, scoring, memory, orchestration, model client
- `services/device_gateway/` - FastAPI gateway, simulator, console, assets
- `services/tool_gateway/` - external tool adapters
- `firmware/` - ESP32-S3 screen/audio/button firmware variants
- `scripts/` - data generation, evaluation, mmWave bridge, regression checks, asset processing
- `skills/food/` - food extraction prompts, demo data, and training data
- `training/` - local small-model fine-tuning and export scripts
- `tests/` - core regression and asset-processing tests
- `assets/` - product UI assets, small-screen processed images, and exported design references
- `docs/` - product specs, API contracts, hardware notes, deployment notes, and implementation plans

## Hardware Direction

Prototype hardware can remain modular:

- ESP32-S3 AMOLED terminal for screen, buttons, Wi-Fi, haptic, and basic audio.
- Microphone path with noise suppression and voice activity detection.
- Speaker or haptic feedback for short confirmations.
- Optional mmWave kit bridged over USB/serial during development.
- Optional camera/phone image path for food logging and menu/meal recognition.
- Optional phone-assisted location first; dedicated GNSS/LTE-M hardware later if standalone outdoor use becomes a product requirement.

Custom hardware should come after the modular prototype proves the core user loops. The custom phase should focus on enclosure, cat-ear mechanism, acoustic layout, antenna layout, power management, charging, thermal behavior, mmWave placement, and manufacturability.

## Safety Boundaries

- SID can give food and wellness suggestions, not medical diagnosis.
- mmWave, heart-rate-like, respiration-like, cycle, and diet-care signals are advisory context only.
- Allergies, taboos, hated ingredients, budget, time, and explicit user constraints are hard rules.
- The device can generate a QR/order/navigation handoff, but the user must confirm and pay manually.
- Local ledgers, `.env`, real device config, model weights, and private data are intentionally ignored by git.

## Development Baseline

This baseline was distilled from the complete prototype code and asset bundle after the event phase ended. Event-only materials, local caches, backups, private runtime data, and pitch files were removed. Product-critical software, firmware, hardware references, UI assets, training scripts, and test coverage were kept.
