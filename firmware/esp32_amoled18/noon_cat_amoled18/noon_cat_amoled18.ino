/*
 * 猫咪决策机 · 方形终端 v0.2 — Waveshare ESP32-S3-Touch-AMOLED-2.16
 * 底座：官方 05_LVGL_Widgets 例程（CO5300 QSPI + CST92xx + LVGL8 + QMI8658）
 * 移植：noon-decision-os 设备协议（WS 状态流 + 事件上报 + 幂等 + 重连）
 * 交互：左半屏=换一个  右半屏=确认(confirming 态再点=下单)  顶栏=开会  底栏长按=取消
 *       摇一摇 = 安全探索(摇苹果树)
 */
#include <lvgl.h>
#include "Arduino_GFX_Library.h"
#include <Adafruit_XCA9554.h>
#include "TouchDrvCSTXXX.hpp"
#include "pin_config.h"
#include <SensorQMI8658.hpp>
#include "ESP_I2S.h"
#include "es8311.h"
#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include "HWCDC.h"
#include "noon_config.h"   // WIFI_SSID / WIFI_PASS / GW_HOST / GW_PORT / DEVICE_ID
LV_FONT_DECLARE(noon_font_cn_46);
LV_FONT_DECLARE(noon_font_cn_32);  // 定制中文字库(覆盖演示数据全字符)
extern const lv_img_dsc_t splash_sofa;  // 开机封面+待机屏保(沙发猫插画, splash_sofa.c)
extern const lv_img_dsc_t council_img;  // 议事会开庭定场图(圆桌插画, council_img.c)
extern const lv_img_dsc_t taste_img;    // 口味选择引导页(开机问一次, 按键即确认)
lv_obj_t *splash = nullptr;
lv_obj_t *cImg = nullptr;
lv_obj_t *tasteImg = nullptr;
bool tasteAsked = false; uint32_t tasteAt = 0;
uint32_t lastUiAt = 0;                  // 最后一次画面变化, 60s 无动静回到沙发猫

HWCDC USBSerial;
#define TICK_MS 2

// ==== 显示/触摸/IMU（与官方例程一致） ====
Arduino_DataBus *bus = new Arduino_ESP32QSPI(
    LCD_CS, LCD_SCLK, LCD_SDIO0, LCD_SDIO1, LCD_SDIO2, LCD_SDIO3);
// 1.8 寸板 V2: CO5300 368x448 原生竖屏(列偏移16), LVGL 软旋转 90° 横用(448x368 猫脸)
Arduino_CO5300 *gfx = new Arduino_CO5300(
    bus, GFX_NOT_DEFINED, 0, LCD_WIDTH, LCD_HEIGHT, 16, 0, 0, 0);   // 原生竖屏, 旋转在 flush 里自己做
Adafruit_XCA9554 expander;   // 复位/使能挂 IO 扩展器
#define SCR_W 448
#define SCR_H 368
TouchDrvCST816 touch;   // V2 板贴纸 CST820, 与 CST816 同协议
volatile bool tpFlag = false;
void IRAM_ATTR onTpInt() { tpFlag = true; }
SensorQMI8658 qmi;
IMUdata acc;
// FT3168 触摸经 Arduino_DriveBus, 中断旗标在类内
static lv_disp_draw_buf_t draw_buf;

void rounder_cb(struct _lv_disp_drv_t *d, lv_area_t *a) {
  if (a->x1 % 2 != 0) a->x1--; if (a->y1 % 2 != 0) a->y1--;
  if (a->x2 % 2 == 0) a->x2++; if (a->y2 % 2 == 0) a->y2++;
}
static uint16_t *nativeFrame = nullptr;   // 368x448 原生帧(PSRAM)
void disp_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *p) {
  // full_refresh 模式: 每次都是完整 448x368 逻辑帧; 自己旋 90° 后整窗写入——
  // 该面板不支持行列交换, 局部窗口又有列对齐怪癖, 整窗写入是唯一稳的路
  const int LW = 448, LH = 368;
  uint16_t *src = (uint16_t *)&p->full;
  for (int y = 0; y < LH; y++) {
    for (int x = 0; x < LW; x++) {
      // 逻辑(x,y) → 原生(col=367-y, row=x): 横屏且按键朝上
      nativeFrame[x * 368 + (367 - y)] = src[y * LW + x];
    }
  }
  gfx->draw16bitRGBBitmap(0, 0, nativeFrame, 368, 448);
  lv_disp_flush_ready(disp);
}
void touchpad_read(lv_indev_drv_t *drv, lv_indev_data_t *data) {
  int16_t rx[1], ry[1];
  if (touch.getPoint(rx, ry, 1)) {
    data->state = LV_INDEV_STATE_PR;
    // 面板原生竖屏(368x448), 屏幕旋转90°横用 → (x,y) = (raw_y, 368-1-raw_x)
    data->point.x = ry[0];            // 与 flush 的 180° 翻转同步
    data->point.y = 367 - rx[0];
  } else data->state = LV_INDEV_STATE_REL;
}
void tick_cb(void *arg) { lv_tick_inc(TICK_MS); }

// ==== 协议层 ====
WebSocketsClient ws;
String sessionId = "";
String curState = "boot";
void playMeow(float f0, float f1, int ms, float vol = 0.55f);
void meowByCat(const String &t);
lv_obj_t *scr, *lblState, *lblTitle, *lblSub, *lblHint, *qr = nullptr;


// ==== 像素猫（14x10 网格，纯代码无资源）====
#define PGW 14
#define PGH 10
#define PCEL 22   // 448x368 横屏下猫缩到 308x220
static lv_obj_t *pixgrid[PGH][PGW];
// . 空  O 橙毛  W 白  K 深灰描边  P 粉  A 状态强调色
static const char *CAT_IDLE[PGH] = {
  ".KK........KK.", ".KOK......KOK.", ".KOOKKKKKKOOK.", ".KOOOOOOOOOOK.",
  ".KOWWOOOOWWOK.", ".KOKWOOOOKWOK.", ".KOOOOKKOOOOK.", ".KOOOPKKPOOOK.",
  ".KOOOOOOOOOOK.", "..KKKKKKKKKK..",
};
static const char *CAT_LISTEN[PGH] = {
  "KK..........KK", "KAK........KAK", "KAOKKKKKKKKOAK", ".KOOOOOOOOOOK.",
  ".KOWWOOOOWWOK.", ".KOKWOOOOKWOK.", ".KOOOOKKOOOOK.", ".KOOOKAAKOOOK.",
  ".KOOOKAAKOOOK.", "..KKKKKKKKKK..",
};
static const char *CAT_THINK[PGH] = {
  ".KK........KK.", ".KOK......KOK.", ".KOOKKKKKKOOK.", ".KOOOOOOOOOOK.",
  ".KOOOOOOOOOOK.", ".KOKKOOOOKKOK.", ".KOOOOKKOOOOK.", ".KOOOPKKPOOOK.",
  ".KOOOOOOOOOOK.", "..KKKKKKKKKK..",
};
static const char *CAT_HAPPY[PGH] = {
  ".KK........KK.", ".KOK......KOK.", ".KOOKKKKKKOOK.", ".KOOOOOOOOOOK.",
  ".KOKWOOOOWKOK.", ".KOWKOOOOKWOK.", ".KOOOOKKOOOOK.", ".KOOAKOOKAOOK.",
  ".KOOOAAAAOOOK.", "..KKKKKKKKKK..",
};
static const char *CAT_ERROR[PGH] = {
  ".KK........KK.", ".KOK......KOK.", ".KOOKKKKKKOOK.", ".KOOOOOOOOOOK.",
  ".KOKWOOOOWKOK.", ".KOWKOOOOKWOK.", ".KOOOOKKOOOOK.", ".KOOOKKKKOOOK.",
  ".KOOKOOOOKOOK.", "..KKKKKKKKKK..",
};

void setPixCat(const char **art, uint32_t accent) {
  for (int r = 0; r < PGH; r++)
    for (int c = 0; c < PGW; c++) {
      char ch = art[r][c];
      lv_obj_t *o = pixgrid[r][c];
      if (ch == '.') { lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN); continue; }
      lv_obj_clear_flag(o, LV_OBJ_FLAG_HIDDEN);
      uint32_t col = 0xFFB74D;
      if (ch == 'W') col = 0xF5F0E8; else if (ch == 'K') col = 0x2A2A33;
      else if (ch == 'P') col = 0xEF9A9A; else if (ch == 'A') col = accent;
      lv_obj_set_style_bg_color(o, lv_color_hex(col), 0);
    }
}

uint32_t stateBg() {
  if (curState == "candidate")  return 0xE65100;   // 橙
  if (curState == "council")    return 0x4527A0;   // 紫
  if (curState == "confirming") return 0x2E7D32;   // 绿
  if (curState == "error")      return 0xB71C1C;
  if (curState == "done")       return 0x00695C;
  return 0x111111;                                  // AMOLED 黑底省电
}

const char* stateCn(const String &st) {
  if (st == "idle") return "待命"; if (st == "listening") return "在听";
  if (st == "structuring") return "思考中"; if (st == "council") return "议事会";
  if (st == "candidate") return "今日推荐"; if (st == "confirming") return "确认？";
  if (st == "acting") return "下单中"; if (st == "done") return "完成";
  if (st == "error") return "出错"; if (st == "online") return "在线";
  if (st == "offline") return "重连中"; if (st == "explore") return "安全探索";
  return st.c_str();
}

// ==== 打字机字幕（议事会台词逐字浮现，用户感知讨论过程）====
String twTarget = ""; int twPos = 0; uint32_t twAt = 0;
void twStart(const char *full) { twTarget = full; twPos = 0; lv_label_set_text(lblSub, ""); }
void twTick() {
  if (twPos >= (int)twTarget.length()) return;
  if (millis() - twAt < 60) return;                       // 60ms/字
  twAt = millis();
  uint8_t c = twTarget[twPos];
  int adv = (c < 0x80) ? 1 : (c < 0xE0) ? 2 : (c < 0xF0) ? 3 : 4;   // UTF-8 逐码点
  twPos += adv;
  lv_label_set_text(lblSub, twTarget.substring(0, twPos).c_str());
}

void uiSet(const String &st, const char *title, const char *sub) {
  if (splash) { lv_obj_del(splash); splash = nullptr; }   // 真实画面到来时撤下封面/屏保
  if (cImg) { lv_obj_del(cImg); cImg = nullptr; }         // 撤下开庭定场图
  if (tasteImg) { lv_obj_del(tasteImg); tasteImg = nullptr; }
  lastUiAt = millis();
  twTarget = "";                                          // 普通刷屏取消打字机
  curState = st;
  if (lblHint) lv_obj_add_flag(lblHint, LV_OBJ_FLAG_HIDDEN);  // 交互走按键/语音,屏幕不摆按钮
  uint32_t ac = stateBg();
  if (st == "listening" && String(title).indexOf("在听") >= 0) setPixCat(CAT_LISTEN, 0x66BB6A);
  else if (st == "council" || st == "structuring") setPixCat(CAT_THINK, 0x9575CD);
  else if (st == "candidate" || st == "done" || st == "confirming") setPixCat(CAT_HAPPY, 0xFFB74D);
  else if (st == "error") setPixCat(CAT_ERROR, 0xEF5350);
  else setPixCat(CAT_IDLE, 0xFFB74D);
  if (qr) {
    if (st == "done" && sessionId.length()) {   // 喵单屏：扫码下单/拍照记卡路里
      String url = urlBase() + "/console?sid=" + sessionId;
      lv_qrcode_update(qr, url.c_str(), url.length());
      lv_obj_clear_flag(qr, LV_OBJ_FLAG_HIDDEN);
      for (int r = 0; r < PGH; r++) for (int c = 0; c < PGW; c++)
        lv_obj_add_flag(pixgrid[r][c], LV_OBJ_FLAG_HIDDEN);   // 猫让位给二维码
    } else lv_obj_add_flag(qr, LV_OBJ_FLAG_HIDDEN);
  }
  lv_obj_set_style_text_color(lblState, lv_color_hex(curState == "idle" ? 0xFFB74D : stateBg()), 0);
  lv_label_set_text(lblState, stateCn(st));
  lv_label_set_text(lblTitle, title);
  lv_label_set_text(lblSub, sub);
}

String urlBase() { return String("http://") + GW_HOST + ":" + GW_PORT; }

bool httpPostJson(const String &path, const String &body, String *resp = nullptr) {
  HTTPClient http;
  http.begin(urlBase() + path);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  if (resp && code == 200) *resp = http.getString();
  http.end();
  return code == 200;
}

void ensureSession() {
  if (sessionId.length()) return;
  String resp;
  if (httpPostJson("/v1/session", String("{\"device_id\":\"") + DEVICE_ID + "\"}", &resp)) {
    StaticJsonDocument<128> d;
    if (!deserializeJson(d, resp)) sessionId = (const char *)d["session_id"];
  }
}

void postEvent(const char *ev) {
  ensureSession();
  StaticJsonDocument<256> d;
  d["device_id"] = DEVICE_ID; d["session_id"] = sessionId; d["event"] = ev;
  d["timestamp"] = (uint32_t)(millis());   // 单次开机内唯一 → 幂等键
  d["firmware_version"] = "amoled-0.2";
  String body; serializeJson(d, body);
  httpPostJson("/v1/device/event", body);
  if (String(ev) == "right_ear" && curState == "confirming")
    httpPostJson("/v1/confirm", String("{\"session_id\":\"") + sessionId + "\"}");
}

void postExplore() {  // 摇一摇 = 摇苹果树
  ensureSession();
  httpPostJson("/v1/input", String("{\"session_id\":\"") + sessionId +
               "\",\"soft_preferences\":{\"novelty\":\"bold\"}}");
}

void onWsEvent(WStype_t type, uint8_t *payload, size_t len) {
  if (type == WStype_TEXT) USBSerial.printf("[WS] %.*s\n", (int)min(len,(size_t)150), payload);
  if (type == WStype_CONNECTED) { uiSet("idle", "想吃什么？", "按住说话 · 点左边换 · 摇一摇");
    static bool greeted = false;                                     // 只在开机首连打招呼, 重连不叫
    if (!greeted) { greeted = true; playMeow(700, 1000, 180); playMeow(1000, 1320, 200);
      if (!tasteAsked) {                     // 开机问一次口味(引导页, 任意键确认)
        tasteAsked = true; tasteAt = millis();
        tasteImg = lv_img_create(scr);
        lv_img_set_src(tasteImg, &taste_img);
        lv_obj_align(tasteImg, LV_ALIGN_CENTER, 0, 0);
      } }
    return; }
  if (type == WStype_DISCONNECTED) { uiSet("offline", "重连中...", ""); return; }
  if (type != WStype_TEXT) return;
  StaticJsonDocument<1024> d;
  if (deserializeJson(d, payload, len)) return;
  String st = (const char *)(d["state"] | "idle");
  if (st == "done") {
    uiSet("done", "喵单已出", "扫码下单 · 拍照记卡路里");
    playMeow(880, 1180, 200); playMeow(1180, 920, 240);       // 出单开心两连叫
  } else if (st == "candidate") {
    uiSet("candidate", (const char *)(d["display"]["subtitle"] | ""), "");  // 菜名大字,不重复"今日推荐"
    playMeow(820, 1160, 300);                                  // 推荐上扬喵
  } else if (st == "council") {
    String title = (const char *)(d["display"]["title"] | "");
    String sub = (const char *)(d["display"]["subtitle"] | "");
    uiSet(st, title.c_str(), "");
    if (title == "议事会") {                                   // 开场帧: 圆桌定场镜头
      cImg = lv_img_create(scr);
      lv_img_set_src(cImg, &council_img);
      lv_obj_align(cImg, LV_ALIGN_CENTER, 0, -20);
    }
    lv_label_set_text(lblSub, sub.c_str());                    // 台词一次性全显(打字机实测体验不佳)
    meowByCat(title);                                          // 谁发言谁叫
  } else {
    uiSet(st, (const char *)(d["display"]["title"] | ""),
          (const char *)(d["display"]["subtitle"] | ""));
    if (st == "error") playMeow(430, 300, 380);                // 低落喵
  }
}

// 触摸四分区（屏幕级事件）
static lv_point_t pressPt; static uint32_t pressAt = 0;
void scr_event_cb(lv_event_t *e) {
  lv_event_code_t code = lv_event_get_code(e);
  lv_indev_t *indev = lv_indev_get_act();
  if (!indev) return;
  if (splash || tasteImg) {                       // 屏保/口味页: 触摸只唤醒(=确认)
    if (code == LV_EVENT_RELEASED) {
      if (tasteImg) { uiSet("idle", "记住口味了喵！", "想吃什么？按住说话"); playMeow(800, 1050, 200); }
      else uiSet("idle", "想吃什么？", "按住说话 · 点左边换 · 摇一摇");
    }
    return;
  }
  if (code == LV_EVENT_PRESSED) { lv_indev_get_point(indev, &pressPt); pressAt = millis(); }
  if (code == LV_EVENT_RELEASED) {
    uint32_t held = millis() - pressAt;
    static uint32_t lastEventAt = 0;
    // 防误触：边缘 30px 死区(手持握边) + 事件间隔 ≥600ms + 普通触发必须是短按(<500ms)
    if (pressPt.x < 26 || pressPt.x > SCR_W - 26) return;  // 左右边缘死区(握持防误触)
    if (millis() - lastEventAt < 600) return;
    const char *evName = nullptr;
    if (pressPt.y > SCR_H - 48 && held > 800)    evName = "cancel";
    else if (pressPt.y > SCR_H - 60) {           // 底部轻点 = 我饿了吗(记忆猫彩蛋)
      httpPostJson("/v1/hungry", "{}"); lastEventAt = millis(); return; }
    else if (pressPt.y < 60 && held > 800) { cycleVolume(); lastEventAt = millis(); return; }  // 长按顶部=音量
    else if (held > 500)                         return;  // 长按(非取消区)=手掌误触,忽略
    else if (pressPt.y < 60)                     evName = "both_ears";
    else if (pressPt.x < SCR_W / 2)              evName = "left_ear";
    else                                         evName = "right_ear";
    lastEventAt = millis();
    postEvent(evName);
  }
}

void buildUi() {
  scr = lv_scr_act();
  lv_obj_set_style_bg_color(scr, lv_color_hex(0x0A0A0E), 0);
  int gx = (SCR_W - PGW * PCEL) / 2, gy = 46;
  for (int r = 0; r < PGH; r++)
    for (int c = 0; c < PGW; c++) {
      lv_obj_t *o = lv_obj_create(scr);
      lv_obj_set_size(o, PCEL, PCEL);
      lv_obj_set_pos(o, gx + c * PCEL, gy + r * PCEL);
      lv_obj_set_style_radius(o, 2, 0);
      lv_obj_set_style_border_width(o, 0, 0);
      lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
      lv_obj_clear_flag(o, LV_OBJ_FLAG_CLICKABLE);
      pixgrid[r][c] = o;
    }
  lv_obj_add_flag(scr, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(scr, scr_event_cb, LV_EVENT_ALL, NULL);
  lblState = lv_label_create(scr);
  lv_obj_set_style_text_color(lblState, lv_color_white(), 0);
  lv_obj_set_style_text_font(lblState, &noon_font_cn_32, 0);
  lv_obj_align(lblState, LV_ALIGN_TOP_MID, 0, 8);
  lblTitle = lv_label_create(scr);
  lv_obj_set_style_text_color(lblTitle, lv_color_white(), 0);
  lv_obj_set_style_text_font(lblTitle, &noon_font_cn_46, 0);
  lv_obj_set_width(lblTitle, 432); lv_label_set_long_mode(lblTitle, LV_LABEL_LONG_WRAP);
  lv_obj_set_style_text_align(lblTitle, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_align(lblTitle, LV_ALIGN_TOP_MID, 0, 270);
  lblSub = lv_label_create(scr);
  lv_obj_set_style_text_font(lblSub, &noon_font_cn_32, 0);
  lv_obj_set_style_text_color(lblSub, lv_color_hex(0xBBBBBB), 0);
  lv_obj_set_width(lblSub, 432); lv_label_set_long_mode(lblSub, LV_LABEL_LONG_WRAP);
  lv_obj_set_style_text_align(lblSub, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_align(lblSub, LV_ALIGN_TOP_MID, 0, 322);
  lblHint = lv_label_create(scr);
  lv_obj_set_style_text_color(lblHint, lv_color_hex(0x777777), 0);
  lv_obj_set_style_text_font(lblHint, &noon_font_cn_32, 0);
  lv_label_set_text(lblHint, "< 换一个  |  就吃这个 >");
  lv_obj_align(lblHint, LV_ALIGN_BOTTOM_MID, 0, -18);
  qr = lv_qrcode_create(scr, 200, lv_color_hex(0x0A0A0E), lv_color_hex(0xFFFFFF));
  lv_obj_align(qr, LV_ALIGN_TOP_MID, 0, 78);
  lv_obj_add_flag(qr, LV_OBJ_FLAG_HIDDEN);
  lv_label_set_text(lblState, "启动");
  lv_label_set_text(lblTitle, "猫咪决策机");
  lv_label_set_text(lblSub, "连接中...");
  splash = lv_img_create(scr);                   // 开机封面: 沙发猫「今天吃什么?」
  lv_img_set_src(splash, &splash_sofa);          // WiFi/WS 连上后第一帧 uiSet 撤下
  lv_obj_align(splash, LV_ALIGN_CENTER, 0, 0);
}

// ==== 板载语音：按住 BOOT 说话(≥0.3s)，短按=召集议事会 ====
#define REC_RATE 16000
#define REC_MAX_S 6
uint8_t *recBuf = nullptr; size_t recLen = 0; bool recording = false;
uint32_t bootDownAt = 0; bool bootWasDown = false;

I2SClass i2s;   // ES8311 全双工: 录音+放音同一颗 codec

void micInit() {
  // 1.8 板只有一颗 ES8311: 麦克风 ADC + 喇叭 DAC 全双工
  i2s.setPins(I2S_BCK_IO, I2S_WS_IO, I2S_DO_IO, I2S_DI_IO, I2S_MCK_IO);
  if (!i2s.begin(I2S_MODE_STD, REC_RATE, I2S_DATA_BIT_WIDTH_16BIT,
                 I2S_SLOT_MODE_STEREO, I2S_STD_SLOT_BOTH)) {
    USBSerial.println("[MIC] I2S init fail");
    return;
  }
  recBuf = (uint8_t *)heap_caps_malloc(REC_RATE * 2 * 2 * REC_MAX_S, MALLOC_CAP_SPIRAM);  // 立体声
}

// ==== 喇叭：ES8311 + 合成猫叫（无音频素材，全部现场合成）====
bool spkOk = false; uint32_t paOffAt = 0;
es8311_handle_t spkH = NULL;
int volIdx = 1; const uint8_t VOLS[] = {45, 60, 76, 0};  // 小/中/大/静音, 长按屏幕顶部循环

void cycleVolume() {
  volIdx = (volIdx + 1) % 4;
  if (spkOk) es8311_voice_volume_set(spkH, VOLS[volIdx], NULL);
  USBSerial.printf("[SPK] vol=%d\n", VOLS[volIdx]);
  if (VOLS[volIdx]) playMeow(800, 1050, 180);            // 新音量喵一声反馈
}

void spkInit() {
  pinMode(PA, OUTPUT); digitalWrite(PA, LOW);
  es8311_handle_t h = es8311_create(0, ES8311_ADDRRES_0);
  if (!h) { USBSerial.println("[SPK] es8311 create fail"); return; }
  spkH = h;
  const es8311_clock_config_t clk = {
    .mclk_inverted = false, .sclk_inverted = false, .mclk_from_mclk_pin = true,
    .mclk_frequency = REC_RATE * 256, .sample_frequency = REC_RATE,
  };
  if (es8311_init(h, &clk, ES8311_RESOLUTION_16, ES8311_RESOLUTION_16) != ESP_OK) {
    USBSerial.println("[SPK] es8311 init fail"); return;
  }
  es8311_sample_frequency_config(h, REC_RATE * 256, REC_RATE);
  if (es8311_microphone_config(h, false) != ESP_OK) USBSerial.println("[MIC] es8311 mic config fail");
  if (es8311_microphone_gain_set(h, ES8311_MIC_GAIN_18DB) != ESP_OK) USBSerial.println("[MIC] es8311 mic gain fail");
  es8311_voice_volume_set(h, 60, NULL);   // 音量: 88 太炸, 60 温和
  spkOk = true;
  USBSerial.println("[SPK] es8311 ok");
}

// 猫叫：基频 f0→f1 滑音 + 颤音 + 谐波 + 包络。阻塞 ms 毫秒（叫声都很短）。
void playMeow(float f0, float f1, int ms, float vol) {
  if (!spkOk || recording) return;
  digitalWrite(PA, HIGH);
  const int N = REC_RATE * ms / 1000;
  static int16_t buf[512];
  int bi = 0; float ph = 0;
  for (int i = 0; i < N; i++) {
    float t = (float)i / N;
    float f = f0 + (f1 - f0) * t + 22.0f * sinf(t * 40.0f);
    ph += 2.0f * PI * f / REC_RATE;
    float env = (t < 0.10f) ? t / 0.10f : powf(1.0f - (t - 0.10f) / 0.90f, 1.5f);
    float s = sinf(ph) * 0.62f + sinf(2 * ph) * 0.26f + sinf(3 * ph) * 0.12f;
    int16_t v = (int16_t)(s * env * vol * 28000);
    buf[bi++] = v; buf[bi++] = v;                  // L + R
    if (bi == 512) { i2s.write((uint8_t *)buf, sizeof(buf)); bi = 0; }
  }
  if (bi) { i2s.write((uint8_t *)buf, bi * 2); }
  paOffAt = millis() + 1500;                       // 留 1.5s 再关功放，连续叫不咔哒
}

// 每只猫固定音色：口味高亢 / 预算低沉 / 时间急促两声 / 记忆拖长 / 探索上扬
void meowByCat(const String &t) {
  if      (t.indexOf("口味") >= 0) playMeow(900, 1250, 300);
  else if (t.indexOf("预算") >= 0) playMeow(470, 610, 340);
  else if (t.indexOf("时间") >= 0) { playMeow(760, 960, 150); playMeow(960, 800, 150); }
  else if (t.indexOf("记忆") >= 0) playMeow(600, 510, 430);
  else if (t.indexOf("探索") >= 0) playMeow(640, 1120, 360);
  else playMeow(700, 900, 250);
}

void sendVoice() {
  uiSet("structuring", "猫猫在想", "让我想想吃什么好");
  setPixCat(CAT_THINK, 0x9575CD);
  lv_refr_now(NULL);   // 立即重绘：下面 HTTP 阻塞期间 lv_timer_handler 不会跑，不刷会卡在"在听你说"
  ensureSession();
  HTTPClient http;
  http.begin(urlBase() + "/v1/voice?session_id=" + sessionId + "&rate=16000");
  http.addHeader("Content-Type", "application/octet-stream");
  http.setTimeout(120000);
  // ES8311 出来是立体声帧, 取单声道后再发(网关 /v1/voice 期望 16k 单声道)
  int16_t *pcm = (int16_t *)recBuf;
  size_t frames = recLen / 4;
  for (size_t i = 0; i < frames; i++) pcm[i] = pcm[i * 2];
  recLen = frames * 2;
  int code = http.POST(recBuf, recLen);
  USBSerial.printf("[VOICE] http=%d resp=%s\n", code, http.getString().substring(0, 120).c_str());
  if (code != 200) uiSet("error", "没听清", "再按住说一次");
  http.end();
}

void checkKeys() {
  static int idle0 = -1;
  if (idle0 < 0) { idle0 = digitalRead(0); USBSerial.printf("[KEY] idle g0=%d\n", idle0); }
  // 1.8 板只有 BOOT 一颗用户键: 快点=就吃这个, 按住=说话; 换一个用触摸左半屏/语音
  static bool aDown = false; static uint32_t aAt = 0; static bool wokeWithKey = false;
  bool a = digitalRead(0) != idle0;
  if ((splash || tasteImg) && a && !aDown) {
    if (tasteImg) {
      uiSet("idle", "记住口味了喵！", "想吃什么？按住说话");
      playMeow(800, 1050, 200);
    } else {
      uiSet("idle", "想吃什么？", "按住说话 · 点左边换 · 摇一摇");
    }
    aAt = millis();
    aDown = true;
    wokeWithKey = true;
    USBSerial.println("[KEY] A down (wake)");
  }
  if (splash || tasteImg) return;
  if (a && !aDown) { aAt = millis(); USBSerial.println("[KEY] A down"); }
  if (a && recording && recLen < REC_RATE * 2 * 2 * REC_MAX_S) {
    size_t got = i2s.readBytes((char *)recBuf + recLen, 2048); recLen += got;
  }
  if (a && !recording && recBuf && millis() - aAt > 300) {
    recording = true; recLen = 0;
    USBSerial.println("[REC] start");
    uiSet("listening", "在听你说...", "松开发送");
  }
  if (!a && aDown) {
    if (recording) {
      recording = false;
      wokeWithKey = false;
      USBSerial.printf("[REC] stop bytes=%u\n", recLen);
      if (recLen > REC_RATE * 2) sendVoice();   // 立体声字节流: 0.5 秒以上才发
      else uiSet("idle", "太短了", "按住再说一次");
    } else if (wokeWithKey) {
      wokeWithKey = false;
      USBSerial.println("[KEY] A short -> wake only");
    } else {
      USBSerial.println("[KEY] A short -> right_ear");
      postEvent("right_ear");
    }
  }
  aDown = a;
}

// 摇一摇检测
uint32_t lastShakeAt = 0;
void checkShake() {
  if (curState != "candidate") return;                  // 只在推荐页允许摇树, 防止录音/开会/确认乱跳
  if (!qmi.getDataReady()) return;
  if (!qmi.getAccelerometer(acc.x, acc.y, acc.z)) return;
  float mag = sqrtf(acc.x * acc.x + acc.y * acc.y + acc.z * acc.z);
  if (mag > 2.8f && millis() - lastShakeAt > 5000) {   // >2.8g 且 5s 冷却
    lastShakeAt = millis();
    uiSet("explore", "摇一摇!", "安全探索中...");
    postExplore();
  }
}

void setup() {
  USBSerial.begin(115200);
  USBSerial.setTxTimeoutMs(0);
  delay(200);
  USBSerial.println("[BOOT] start");
  pinMode(0, INPUT_PULLUP);   // BOOT 键(唯一用户键)
  Wire.begin(IIC_SDA, IIC_SCL);
  if (expander.begin(0x20)) {          // 复位序列: 屏/触摸/codec 使能挂扩展器
    for (int i : {0, 1, 2, 6}) expander.pinMode(i, OUTPUT);
    for (int i : {0, 1, 2, 6}) expander.digitalWrite(i, LOW);
    delay(20);
    for (int i : {0, 1, 2, 6}) expander.digitalWrite(i, HIGH);
    USBSerial.println("[BOOT] expander ok");
  } else USBSerial.println("[XCA9554] not found");
  qmi.begin(Wire, QMI8658_L_SLAVE_ADDRESS, IIC_SDA, IIC_SCL);
  qmi.configAccelerometer(SensorQMI8658::ACC_RANGE_4G, SensorQMI8658::ACC_ODR_1000Hz,
                          SensorQMI8658::LPF_MODE_0);
  qmi.enableAccelerometer();
  USBSerial.println("[BOOT] qmi ok");
  pinMode(TP_INT, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(TP_INT), onTpInt, FALLING);
  if (!touch.begin(Wire, CST816_SLAVE_ADDRESS, IIC_SDA, IIC_SCL))
    USBSerial.println("[TP] CST820 init fail(不阻塞)");
  else { touch.setMaxCoordinates(368, 448); USBSerial.println("[BOOT] touch ok"); }

  gfx->begin();                        // 显示尽早起(官方 V2 顺序), 音频挪到最后
  gfx->setBrightness(200);
  USBSerial.println("[BOOT] gfx ok");

  lv_init();
  uint32_t W = 448, H = 368;               // 逻辑横屏(自旋转 flush)
  nativeFrame = (uint16_t *)heap_caps_malloc(368 * 448 * 2, MALLOC_CAP_SPIRAM);
  // 全屏双缓冲(PSRAM): 整屏刷新, 从根上绕开 CO5300 局部窗口对齐的花屏
  lv_color_t *b1 = (lv_color_t *)heap_caps_malloc(W * H * sizeof(lv_color_t), MALLOC_CAP_SPIRAM);
  lv_color_t *b2 = (lv_color_t *)heap_caps_malloc(W * H * sizeof(lv_color_t), MALLOC_CAP_SPIRAM);
  USBSerial.printf("[BOOT] lv fullbuf %p %p (%lux%lu)\n", b1, b2, W, H);
  lv_disp_draw_buf_init(&draw_buf, b1, b2, W * H);
  static lv_disp_drv_t disp_drv;
  lv_disp_drv_init(&disp_drv);
  disp_drv.hor_res = W; disp_drv.ver_res = H;   // 面板原生 368x448
  disp_drv.flush_cb = disp_flush; disp_drv.rounder_cb = rounder_cb;
  disp_drv.draw_buf = &draw_buf; disp_drv.full_refresh = 1;
  lv_disp_drv_register(&disp_drv);   // W/H 已是硬件旋转后的 448x368
  static lv_indev_drv_t indev_drv;
  lv_indev_drv_init(&indev_drv);
  indev_drv.type = LV_INDEV_TYPE_POINTER;
  indev_drv.read_cb = touchpad_read;
  lv_indev_drv_register(&indev_drv);
  const esp_timer_create_args_t targs = { .callback = &tick_cb, .name = "lvgl_tick" };
  esp_timer_handle_t t; esp_timer_create(&targs, &t);
  esp_timer_start_periodic(t, TICK_MS * 1000);

  buildUi();
  lv_refr_now(NULL);                   // 先把封面画出来再init其余
  USBSerial.println("[BOOT] ui ok");

  micInit();
  spkInit();
  USBSerial.println("[BOOT] audio ok");

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  USBSerial.println("[BOOT] wifi begin");
}

bool wsStarted = false;
uint32_t lastWifiTry = 0;
void wifiWatch() {
  int status = WiFi.status();
  if (status == WL_CONNECTED) {
    if (!wsStarted) {
      uiSet("idle", "想吃什么？", "按住说话 · 点左边换 · 摇一摇");
      ensureSession();
      ws.begin(GW_HOST, GW_PORT, "/v1/device/stream");
      ws.onEvent(onWsEvent);
      ws.setReconnectInterval(3000);
      ws.enableHeartbeat(15000, 3000, 2);   // 15s ping; 链路悄死 ~21s 内检出并自动重连
      wsStarted = true;
    }
    return;
  }
  if (millis() - lastWifiTry < 30000) return;
  lastWifiTry = millis();
  if (status == WL_IDLE_STATUS) {
    USBSerial.println("[WIFI] still connecting");
    return;
  }
  USBSerial.printf("[WIFI] reconnect status=%d\n", status);
  uiSet("offline", "网络重连中...", "请稍等");
  WiFi.disconnect(false, false);
  delay(300);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

// 像素猫动画：400ms 一帧
uint32_t animAt = 0; int animFrame = 0;
void animateCat() {
  if (millis() - animAt < 400) return;
  animAt = millis(); animFrame++;
  if (curState == "done") return;                       // 喵单屏无猫
  if (curState == "listening" && recording)
    setPixCat(animFrame % 2 ? CAT_LISTEN : CAT_IDLE, 0x66BB6A);          // 张嘴/闭嘴
  else if (curState == "council")
    setPixCat(animFrame % 2 ? CAT_LISTEN : CAT_THINK, 0x9575CD);         // 开会: 张嘴说话
  else if (curState == "structuring")
    setPixCat(animFrame % 4 == 3 ? CAT_IDLE : CAT_THINK, 0x9575CD);      // 思考偶尔睁眼
  else if (curState == "candidate" || curState == "confirming")
    setPixCat(CAT_HAPPY, animFrame % 2 ? 0xFFB74D : 0xFFE082);           // 笑脸呼吸闪
  else if (curState == "error")
    setPixCat(CAT_ERROR, 0xEF5350);
  else
    setPixCat(animFrame % 7 == 6 ? CAT_THINK : CAT_IDLE, 0xFFB74D);      // 待命偶尔眨眼
}

uint32_t dbgAt = 0;
void loop() {
  animateCat();
  twTick();                                                  // 议事会台词打字机
  // 口味引导页 30s 没人按 → 自动进待命(演示时不卡流程)
  if (tasteImg && millis() - tasteAt > 30000)
    uiSet("idle", "想吃什么？", "按住说话 · 点左边换 · 摇一摇");
  // 待机屏保: 60s 无画面变化回到沙发猫(也防 AMOLED 烧屏); 录音中不启动
  if (!splash && !tasteImg && !recording && lastUiAt && millis() - lastUiAt > 60000) {
    splash = lv_img_create(scr);
    lv_img_set_src(splash, &splash_sofa);
    lv_obj_align(splash, LV_ALIGN_CENTER, 0, 0);
    lastUiAt = millis();
  }
  if (paOffAt && millis() > paOffAt) { digitalWrite(PA, LOW); paOffAt = 0; }  // 功放待机降噪
  if (millis() - dbgAt > 300) {   // 按键探测: 底行实时显示 GPIO0 电平
    dbgAt = millis();
    lv_label_set_text(lblHint, "< 换一个    |    就吃这个 >");
  }
  lv_timer_handler();
  wifiWatch();
  if (wsStarted) ws.loop();
  checkShake();
  checkKeys();
  delay(5);
}
