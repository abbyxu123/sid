# Product Baseline Design

Date: 2026-08-03

## Goal

Turn the competition-era CatTV/SID prototype into a clean public product-development repository for ongoing software, firmware, hardware, and manufacturing work.

## Source Strategy

Use the final working prototype as the code baseline because it contains the latest firmware, gateway, mmWave bridge, tests, and backend changes. Use the complete zip-equivalent `cat-eatmagic` folder as the asset supplement because it contains UI export assets and board reference images not present in the final code baseline.

## Keep

Keep product-critical runtime code, firmware source, tests, training scripts, food data, API docs, hardware docs, UI assets, and implementation plans.

## Remove

Remove event-only product copy, video scripts, sprint logs, local backups, runtime data, caches, virtual environments, local config, and secrets.

## Public Repo Shape

The public repository should open with a product README, a product MVP spec, a hardware productization roadmap, and a baseline note explaining what was distilled. Git should ignore private runtime data and local build artifacts.

## Validation

Run the Python test suite from the product baseline. Run secret/artifact scans for common private files, local ledgers, model weights, caches, and competition-only terms. Inspect git status before staging. Push only the clean baseline to `abbyxu123/sid`.
