# Hardware Productization Roadmap

Date: 2026-08-03

SID should move from modular prototype to custom hardware in stages. The goal is to avoid expensive custom work before the daily product loop is proven.

## Stage 1: Modular Product Prototype

Purpose: prove the food-memory and meal-decision loop on real hardware.

Hardware:

- ESP32-S3 AMOLED board.
- Built-in or external microphone path.
- Speaker or haptic actuator.
- Physical confirm/change controls through buttons or ear switches.
- Optional IMU for wake/shake interactions.
- Optional external mmWave kit through serial bridge.
- Phone-assisted camera and location.

Validation:

- Voice/text input reaches the gateway reliably.
- Device reconnects after Wi-Fi loss.
- Screen states match backend state.
- Confirm/change events are idempotent.
- Memory and feedback change future recommendations.
- No secret config is committed.

## Stage 2: Integrated Engineering Prototype

Purpose: reduce wiring and prove enclosure constraints.

Hardware work:

- Custom carrier or compact interconnect board.
- Better microphone placement and acoustic cavity.
- Speaker and haptic mounting.
- Battery, charging, and power-path planning.
- Magnetic back and desk/fridge/backpack mounting tests.
- mmWave placement experiment if the feature survives Stage 1.
- Thermal and antenna placement checks.

Software work:

- Stable provisioning flow.
- Device identity and config management.
- Audio AFE/VAD/noise suppression tuning.
- Sensor data schema and freshness policy.
- Local data privacy controls.

## Stage 3: Custom EVT Prototype

Purpose: prove industrial design and electrical architecture.

Custom work:

- Custom PCB or tightly integrated module stack.
- Enclosure with cat-ear mechanical control.
- Acoustic design for real environments.
- Battery safety and charging compliance planning.
- Manufacturing-friendly connector, screw, magnet, and service layout.
- Firmware update path.

Decision gates:

- The first product loop is used repeatedly without developer intervention.
- Noise handling is good enough in a kitchen, office, and restaurant-like environment.
- Battery life and thermal behavior are acceptable.
- The mmWave/camera/location features have clear product value before being embedded.

## Sensor Policy

- Camera: start with phone/upload capture. Embed only when privacy, field of view, lighting, and enclosure value are clear.
- mmWave: start external. Treat readings as advisory wellness context, not medical data.
- Location: start phone-assisted. Add standalone GNSS/LTE-M only for outdoor child/travel scenarios.
- Health/cycle/fitness: use user-entered context plus gentle suggestions. No diagnosis.

## Open Questions

- Whether SID is primarily a desk/fridge object, a travel device, or a child/family wearable-like companion.
- Whether the first custom shell should prioritize cat-ear controls or a simpler reliable button layout.
- Whether image recognition belongs on-device, on phone, or in the gateway for the first product release.
