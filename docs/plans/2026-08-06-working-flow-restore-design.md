# SID Stable Flow Restore Design

## Goal

Restore the last known-good CatTV device interaction flow while retaining the
product-safe microphone, offline parsing, credential isolation, and WebSocket
cleanup fixes already validated in SID.

## Baseline

The reference implementation is `/Users/beibeixv/Desktop/cattv-main.zip`
(archive commit `e9f815cdb1fbd579c144a074f6e8b98eef4f0e76`). The GitHub connector cannot
currently access `abbyxu123/cattv`, so the local archive is the authoritative
read-only baseline for this repair.

## Behavioral Contract

- Idle UI remains visible for 60 seconds before standby.
- Follow-up listening does not disappear on a short server timer.
- The completed QR screen remains until the user explicitly leaves it.
- A new session does not assume delivery unless the user asks for delivery.
- Shake exploration uses the working 2.2g threshold and 3-second cooldown.
- WebSocket loss does not tear down a healthy Wi-Fi association.
- Candidate navigation, confirmation, and QR transition are verified as one
  state-machine flow.
- The local gateway is launched as a persistent development process and its
  health is checked before hardware testing.

## Preserved Improvements

- ES8311 microphone gain remains at the board-reference 18dB setting.
- Invalid flat audio is rejected before ASR.
- Offline text uses deterministic rule parsing when the model is disabled.
- Wi-Fi credentials remain in ignored `noon_config.h`.
- Runtime WebSocket disconnect cleanup remains in the gateway.

## Verification

Add regression tests for every restored timing, channel, shake, and reconnect
contract. Run the full Python suite, compile the firmware, flash with verify,
then manually exercise voice, next candidate, confirm, QR retention, and shake.
