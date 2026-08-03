/*
 * 猫咪决策机 · 方形终端固件（ESP32-S3 + 480x480 一体屏）
 * 目标板：ESP32-S3-4848S040 / Guition JC4848W535（ST7701 RGB + GT911 触摸）
 * 依赖库：Arduino_GFX_Library, WebSockets(links2004), ArduinoJson, TAMC_GT911
 *
 * 协议 = docs/api_contract.md（V1.0）：
 *   下行 WS  ws://<GW>/v1/device/stream  → 状态帧驱动屏幕
 *   上行 POST /v1/device/event           → left_ear/right_ear/both_ears/cancel
 *   确认 POST /v1/confirm（收到 confirming 帧后右半屏再点一次）
 * 触摸分区（等价于耳朵，验收允许）：
 *   左半屏=left_ear  右半屏=right_ear  顶栏=both_ears  底栏长按=cancel
 */
#include <WiFi.h>
#include <HTTPClient.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Arduino_GFX_Library.h>
#include <TAMC_GT911.h>

// ==== 现场配置 ====
const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASS";
const char* GW_HOST   = "<GATEWAY_LAN_IP>"; // Gateway Wi-Fi IP
const int   GW_PORT   = 8090;
const char* DEVICE_ID = "cat-square-01";

// ==== 4848S040 显示（ST7701 RGB 16bit）——换板时只改这一段 ====
Arduino_ESP32RGBPanel *rgbpanel = new Arduino_ESP32RGBPanel(
    39/*DE*/, 48/*VSYNC*/, 47/*HSYNC*/, 45/*PCLK*/,
    4, 5, 6, 7, 15,          /* R */
    8, 20, 3, 46, 9, 10,     /* G */
    11, 12, 13, 14, 0,       /* B */
    0, 8, 4, 8, 0, 8, 4, 8, 1, 16000000);
Arduino_RGB_Display *gfx = new Arduino_RGB_Display(
    480, 480, rgbpanel, 0, true,
    new Arduino_SWSPI(GFX_NOT_DEFINED, 38, 48, 47, GFX_NOT_DEFINED),
    st7701_type1_init_operations, sizeof(st7701_type1_init_operations));
TAMC_GT911 touch(19/*SDA*/, 45/*SCL*/, 18/*INT*/, 38/*RST*/, 480, 480);

WebSocketsClient ws;
String sessionId = "";
String curState = "idle", curTitle = "", curSub = "";
unsigned long touchDownAt = 0; bool touchWasDown = false; int downX = 0, downY = 0;

uint16_t stateColor() {
  if (curState == "candidate")  return gfx->color565(255, 183, 77);   // 橙：出菜了
  if (curState == "council")    return gfx->color565(126, 87, 194);   // 紫：开会中
  if (curState == "confirming") return gfx->color565(102, 187, 106);  // 绿：待确认
  if (curState == "error")      return gfx->color565(239, 83, 80);    // 红
  if (curState == "done")       return gfx->color565(38, 166, 154);
  return gfx->color565(69, 90, 100);                                  // 灰蓝：idle 等
}

void render() {
  gfx->fillScreen(stateColor());
  gfx->setTextColor(WHITE);
  gfx->setTextSize(4); gfx->setCursor(24, 40);  gfx->print(curState);
  gfx->setTextSize(3); gfx->setCursor(24, 150); gfx->print(curTitle);
  gfx->setTextSize(2); gfx->setCursor(24, 220); gfx->print(curSub);
  gfx->setTextSize(2);
  gfx->setCursor(24, 430);  gfx->print("< huan yi ge");
  gfx->setCursor(300, 430); gfx->print("jiu chi zhe ge >");
}

void postEvent(const char* ev) {
  HTTPClient http;
  http.begin(String("http://") + GW_HOST + ":" + GW_PORT + "/v1/device/event");
  http.addHeader("Content-Type", "application/json");
  StaticJsonDocument<256> d;
  d["device_id"] = DEVICE_ID; d["session_id"] = sessionId;
  d["event"] = ev; d["timestamp"] = (uint32_t)millis() + 1700000000u; // 幂等键
  d["firmware_version"] = "esp32-0.1";
  String body; serializeJson(d, body);
  int code = http.POST(body);
  if (code == 200 && String(ev) == "right_ear") {
    // confirming 帧到达后第二次右击才 confirm；此处仅当 state 已是 confirming
    if (curState == "confirming") {
      HTTPClient c2;
      c2.begin(String("http://") + GW_HOST + ":" + GW_PORT + "/v1/confirm");
      c2.addHeader("Content-Type", "application/json");
      c2.POST(String("{\"session_id\":\"") + sessionId + "\"}");
      c2.end();
    }
  }
  http.end();
}

void onWsEvent(WStype_t type, uint8_t* payload, size_t len) {
  if (type != WStype_TEXT) return;
  StaticJsonDocument<1024> d;
  if (deserializeJson(d, payload, len)) return;
  curState = (const char*)(d["state"] | "idle");
  curTitle = (const char*)(d["display"]["title"] | "");
  curSub   = (const char*)(d["display"]["subtitle"] | "");
  render();
}

void ensureSession() {
  if (sessionId.length()) return;
  HTTPClient http;
  http.begin(String("http://") + GW_HOST + ":" + GW_PORT + "/v1/session");
  http.addHeader("Content-Type", "application/json");
  if (http.POST(String("{\"device_id\":\"") + DEVICE_ID + "\"}") == 200) {
    StaticJsonDocument<128> d;
    deserializeJson(d, http.getString());
    sessionId = (const char*)d["session_id"];
  }
  http.end();
}

void setup() {
  gfx->begin(); touch.begin(); touch.setRotation(ROTATION_NORMAL);
  curTitle = "lian wifi..."; render();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(300);
  ensureSession();
  ws.begin(GW_HOST, GW_PORT, "/v1/device/stream");
  ws.onEvent(onWsEvent);
  ws.setReconnectInterval(3000);   // 断线重连；重连后网关会重推当前帧
  curTitle = "online"; render();
}

void loop() {
  ws.loop();
  touch.read();
  bool down = touch.isTouched;
  if (down && !touchWasDown) { touchDownAt = millis(); downX = touch.points[0].x; downY = touch.points[0].y; }
  if (!down && touchWasDown) {
    unsigned long held = millis() - touchDownAt;
    if (downY > 420 && held > 800)      postEvent("cancel");      // 底栏长按取消
    else if (downY < 60)                postEvent("both_ears");   // 顶栏开会
    else if (downX < 240)               postEvent("left_ear");
    else                                postEvent("right_ear");
  }
  touchWasDown = down;
}
