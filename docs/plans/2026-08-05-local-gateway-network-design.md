# Local Gateway Network Design

## Goal

Connect the Waveshare ESP32-S3 head to the home's 2.4 GHz Wi-Fi while the Mac runs the SID gateway at `192.168.0.100:8090`.

## Network Topology

- The ESP32 connects to the home's 2.4 GHz SSID.
- The Mac may remain on the paired 5 GHz SSID because both bands are served by the same LAN.
- The firmware sends HTTP and WebSocket traffic to `192.168.0.100:8090`.
- The 5 GHz-only fallback network is excluded because the ESP32-S3 cannot use it.

## Credential Handling

- Real Wi-Fi credentials live only in the ignored `noon_config.h` file.
- Git tracks a complete `noon_config.h.example` with placeholder values.
- Serial logs may show the SSID and gateway but must never print the password.

## Verification

1. Compile the 1.8-inch AMOLED firmware with the installed ESP32 Arduino core.
2. Flash the connected ESP32-S3 USB serial device.
3. Confirm serial output reports the expected SSID, a DHCP address, and the local router gateway.
4. Start SID gateway on port 8090 and confirm the device receives a WebSocket state frame.

## Verified Result

- The board joined the 2.4 GHz network and received `192.168.0.102`.
- The router gateway was `192.168.0.1`.
- The SID gateway reported one session and one online device.
- The device received the `idle` WebSocket state frame.

## Product Follow-up

This fixed local profile is only for development. Product firmware will replace compile-time Wi-Fi credentials with BLE or SoftAP provisioning and per-device authentication.
