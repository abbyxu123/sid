# mmWave Bridge Design

Goal: connect the Seeed MR60BHA2/XIAO mmWave kit to Cat.TV without changing the working ESP32-S3 prototype firmware.

Architecture: the mmWave kit streams sensor readings over USB serial during development. A small bridge process reads the serial logs, extracts presence, distance, heart rate, respiration, and illuminance, then posts the latest sample to the existing FastAPI device gateway. The H5 and `/v1/hungry` endpoint consume the cached sample and fall back to the existing memory-only result when no fresh sensor data is available.

Scope:
- Add `/v1/sensor/mmwave` for real sensor samples.
- Upgrade `/v1/hungry` so the result can cite real body-state signals plus meal memory.
- Add a local bridge script for serial-to-HTTP forwarding.
- Do not flash or rewire the main Cat.TV board in this phase.

Product note: this is an entertainment wellness signal, not medical diagnosis. The user-facing copy should say "饿 / 不饿 / 可能只是馋" rather than making health claims.
