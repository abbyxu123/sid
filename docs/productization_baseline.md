# Productization Baseline

Date: 2026-08-03

This repository is the clean SID product baseline. It was distilled from the working prototype and the complete asset zip after the competition phase.

## Kept

- Core decision engine, constraint engine, scoring, memory, audit, and model-client code.
- FastAPI device gateway, board simulator, H5 console, and hardware event contracts.
- ESP32-S3 firmware variants for square and AMOLED boards.
- mmWave serial bridge and sensor-aware hungry-check backend path.
- Food extraction prompts, demo restaurant data, training data, and local training scripts.
- Tests, regression scripts, asset-processing scripts, and benchmark records useful for product engineering.
- Small-screen processed assets, UI export assets, web demo images, and hardware board/dimension references.
- Product, API, hardware, frontend, deployment, training, and implementation-plan documentation.

## Removed

- Event-only pitch drafts.
- Video and pitch scripts.
- Event checklist.
- Prototype sprint development log.
- Local backups, firmware build caches, virtual environments, pytest caches, and Python bytecode.
- Local ledger data, database files, `.env`, device secrets, `noon_config.h`, and model weights.

## Public Repository Rules

- Commit source code, firmware source, product docs, tests, and design assets that are needed to continue product development.
- Do not commit real user data, local ledgers, raw private photos, model weights, Wi-Fi credentials, generated firmware binaries, or one-off local backups.
- Keep event-specific material outside this repository unless it is deliberately rewritten as product evidence.

## Source Baselines

- Main code baseline: the 2026-08-02 working prototype.
- Asset supplement: `cattv-main.zip` / `Desktop/cat-eatmagic`, especially `assets/ui_export` and board reference images.
- New product destination: `Desktop/SID`, remote `https://github.com/abbyxu123/sid.git`.
