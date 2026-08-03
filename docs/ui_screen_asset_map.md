# UI Screen Asset Map

Date: 2026-07-28

Source folder:

```text
/Users/beibeixv/Desktop/1.8尺寸UX UI- codex前端/
```

Target screen:

- 448 x 368 px landscape.
- 24 px safe margin.
- Important text is rendered by firmware/frontend code.

## Style Direction

Use refined pixel art as the device's main visual style. The provided illustration assets are valuable references and can be used as source material for fine-pixel conversions, but the firmware should not rely on full-size raw PNGs.

The current coarse pixel cat in firmware remains a fallback, not the final visual quality bar.

## Folder Mapping

| Source folder | Role | Firmware use |
|---|---|---|
| `室内场景/` | Backgrounds and mood references | Convert selected scenes into 448x368 fine-pixel backgrounds |
| `UI角色汇总/` | Cat agent cast | Convert selected cats into 80-120 px fine-pixel sprites |
| `预设菜色与菜号/` | Food recommendations and blind-box reveals | Convert 4-8 P0 foods into small sprites/cards |
| `UI按键组合与气泡/` | Button, bubble, icon visual language | Use as style reference; implement real buttons in LVGL |
| `屏幕上的测试不一定-只是看看/` | Rough page concepts | Use as UX reference only |

## P0 Screen Mapping

| Screen | Purpose | Source assets | Firmware treatment |
|---|---|---|---|
| `01_idle_start` | Standby cover / product first impression | `室内场景/首图.png`, `室内场景/沙发喝茶.png` | Use one refined-pixel 448x368 cover; tap wakes home only |
| `02_home` | Choose main mode | `UI按键组合与气泡/带文字的按钮.png`, `室内场景/沙发一角.png` | LVGL buttons, code-rendered text, small local AI host-ready chip |
| `03_voice_input` | User speaks what they want | `屏幕上的测试不一定-只是看看/说给你听.png`, robot-cat references in `UI按键组合与气泡/` | Listening cat sprite + waveform/paw animation |
| `04_structuring` | AI extracts constraints | `UI角色汇总/长期记忆猫.png`, `UI角色汇总/猫时间管理者.png` | Fine-pixel thinking cat, short status copy |
| `05_cat_council` | Multi-agent theater | `室内场景/开会.png`, cats in `UI角色汇总/` | One 448x368 council background plus rotating cat/bubble overlays |
| `06_candidate` | Show recommendation | `UI角色汇总/决策结果猫.png`, `预设菜色与菜号/菜8.png`, `菜10.png`, `菜12.png`, `菜15.png`, `菜16.png`, `菜21.png`, `菜24.png`, `菜25.png` | One dish card at a time, code-rendered name/price/ETA/reason |
| `07_choose` | Change or confirm | `UI按键组合与气泡/UI组合4.png` | LVGL left/right zones; no baked button text |
| `08_blind_box` | Optional safe mystery choice | `屏幕上的测试不一定-只是看看/开盲盒.png`, `盲盒.png`, `UI按键组合与气泡/组合UI1.png` | 4 boxes max for first firmware version |
| `09_qr_order` | Phone handoff | `UI按键组合与气泡/UI组合3.png` | Firmware-generated QR; background can be simple paper/card |
| `10_receipt_done` | Closure and memory | `UI角色汇总/长期记忆猫.png`, `UI角色汇总/决策结果猫.png` | Receipt layout, feedback hint, memory note |

## P1/P2 Screen Mapping

| Screen | Source assets | Treatment |
|---|---|---|
| Profile / care setup | `屏幕上的测试不一定-只是看看/口味记录长期记忆.png`, `UI角色汇总/长期记忆猫.png` | Later small form/chip UI |
| Hungry check / mmWave | `屏幕上的测试不一定-只是看看/可能真饿.png`, `UI角色汇总/猫时间管理者.png` | Concept/stub until sensor data exists |
| Lucky food | `屏幕上的测试不一定-只是看看/魔法.png`, food sprites | Entertainment-only result |
| Food journal | `屏幕上的测试不一定-只是看看/口味记录长期记忆.png` | Book/receipt style |
| Home cooking | `室内场景/厨房.png`, `室内场景/桌子.png` | Future home mode |

## First Firmware Asset Set

To protect flash size and demo reliability, convert only this first set:

### Backgrounds

- `idle_home_bg`: from `室内场景/首图.png` or a fine-pixel generated equivalent.
- `council_bg`: from `室内场景/开会.png` or a fine-pixel generated equivalent.
- `qr_receipt_bg`: simple generated/card background or LVGL-drawn paper.

### Cat Sprites

- `cat_taste`: from `美味推荐猫.png`.
- `cat_map`: from `定位距离猫.png`.
- `cat_memory`: from `长期记忆猫.png`.
- `cat_time`: from `猫时间管理者.png`.
- `cat_budget`: from `猫会计.png`.
- `cat_chair`: from `决策结果猫.png`.

### Food Sprites

Initial food choices should cover visually different cases:

- `菜8.png`: steak / western plate.
- `菜10.png`: spicy pot.
- `菜12.png`: salad/light.
- `菜15.png`: soup/noodles.
- `菜16.png`: rice bowl.
- `菜21.png`: roujiamo / handheld.
- `菜24.png`: rice noodle bowl.
- `菜25.png`: hotpot/spicy.

## Notes For Conversion

- Full-screen images should be cropped and reduced to 448x368.
- Sprites should be alpha PNGs first, then converted into LVGL image arrays only when selected.
- Use RGB565 or indexed color where quality remains acceptable.
- Keep code-rendered Chinese labels on top of art.
- Avoid adding all 67 source images to firmware.

## Open Visual Test

Before bulk conversion, produce one fine-pixel visual test:

- A 448x368 home screen.
- Title: `今天吃什么？`
- Buttons: `开始决定`, `我饿不饿`.
- A small `local AI host ready` status chip.
- Fine pixel cat, not coarse block cat.

If approved, use the same style for council, candidate, and blind-box screens.
