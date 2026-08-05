# ESP32-S3 Touch AMOLED 1.8 Firmware

## Hardware

- Board: Waveshare ESP32-S3-Touch-AMOLED-1.8 V2
- MCU: ESP32-S3R8
- Flash: 16 MB
- PSRAM: 8 MB OPI
- USB: Hardware CDC/JTAG

## Arduino Dependencies

- ESP32 Arduino core 3.3.11
- LVGL 8.3.11 with the matching `lv_conf.h`
- GFX Library for Arduino 1.6.7
- Adafruit XCA9554 1.0.0
- Adafruit BusIO 1.17.4
- SensorLib 0.4.1
- WebSockets 2.7.2
- ArduinoJson 7.4.3

The firmware uses LVGL 8 APIs and does not compile against LVGL 9.

## Local Configuration

Copy `noon_cat_amoled18/noon_config.h.example` to `noon_config.h` and fill in the 2.4 GHz Wi-Fi and local gateway values. The real file is ignored by Git and must never be committed.

## Board Options

- Board: ESP32S3 Dev Module
- USB Mode: Hardware CDC and JTAG
- USB CDC On Boot: Enabled
- Flash Size: 16 MB
- Partition Scheme: 16 MB Flash, 3 MB app and 9.9 MB FATFS
- PSRAM: OPI PSRAM

Compile before every upload. Upload only after compilation exits successfully, then verify Wi-Fi, DHCP, HTTP, and WebSocket events at 115200 baud.
