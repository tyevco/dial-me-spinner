# dial-me-spinner: firmware architecture plan (rev A)

**Status:** plan only; no firmware code exists yet. **Target:** nRF Connect SDK
(NCS) v3.x on Zephyr 4.x, built with sysbuild, with MCUboot and the SoftDevice
Controller. **Hardware:** [`hardware/design/SPEC.md`](../hardware/design/SPEC.md)
rev A, its net names in [`nets.py`](../hardware/design/nets.py) and the
generated sheets in [`sheets/`](../hardware/design/sheets/). Where this
document and SPEC disagree, SPEC wins; where SPEC and the sheets disagree, the
sheets and the netlist win. The disagreements found are listed in
[§18](#18-open-items-and-to-verify-list). Firmware rules that come from the
SPICE suite ([`hardware/sim`](../hardware/sim), described in
[simulation.md](simulation.md)) cite its finding id, e.g.
"(hardware/sim, LSW-3)".

This document is written for the person who will implement and bring up the
firmware. Each section gives the decision, the numbers behind it, and what
still has to be measured.

**Conventions**

* **TVP** means *to verify on prototype*. Treat every TVP number as an
  assumption until it has been measured on real hardware.
* **Angles.** θ follows SPEC §8: 0° is the USB-C direction, and angles increase
  counter-clockwise (CCW) seen from the top. The ring angle θr is positive CCW.
  Microsoft defines a positive Radial Controller dial value as **clockwise**, so
  the HID layer flips the sign.
* **Electrical angle φ.** The 48 alternating magnets make 24 electrical periods
  per revolution. One electrical period (360° el) is 15° mechanical, which is
  exactly one detent.
* **Kconfig and devicetree names** below are correct for current Zephyr/NCS as
  far as the research could check. Names drift between releases, so check each
  one against your SDK's `dts/bindings` and `Kconfig` before you rely on it.
  Names that could not be checked are marked *(check name)*.

## Contents

1. [Platform, build and resource allocation](#1-platform-build-and-resource-allocation)
2. [Module and thread architecture](#2-module-and-thread-architecture)
3. [Devicetree and Kconfig](#3-devicetree-and-kconfig)
4. [Rotation-sensing pipeline](#4-rotation-sensing-pipeline)
5. [Detent control](#5-detent-control)
6. [LED renderer](#6-led-renderer)
7. [Display](#7-display)
8. [Audio and press input](#8-audio-and-press-input)
9. [BLE](#9-ble)
10. [USB composite device](#10-usb-composite-device)
11. [Boot, partitions and DFU](#11-boot-partitions-and-dfu)
12. [Power management](#12-power-management)
13. [BQ25180 charger driver](#13-bq25180-charger-driver)
14. [LIS2DW12 accelerometer](#14-lis2dw12-accelerometer)
15. [Fault handling](#15-fault-handling)
16. [Bring-up and manufacturing tests](#16-bring-up-and-manufacturing-tests)
17. [Implementation plan and host-side tests](#17-implementation-plan-and-host-side-tests)
18. [Open items and to-verify list](#18-open-items-and-to-verify-list)
19. [References](#19-references)

---

## 1. Platform, build and resource allocation

### 1.1 SDK, board and repository layout

* **SDK.** NCS v3.x (Zephyr 4.x) with the SoftDevice Controller (SDC) and MPSL.
  Build with sysbuild: one application image plus MCUboot.
* **Board.** A custom HWMv2 board `dial_me_spinner/nrf52840` (SoC nRF52840
  QIAA inside the Raytac MDBT50Q-U1MV2).
  * The nRF runs in **normal-voltage mode**: VDD and VDDH both on +3V3, and
    DCCH unconnected (SPEC §3). Enable the REG1 DC/DC, whose inductor is inside
    the module.
  * UICR.REGOUT0 is irrelevant in this mode, so firmware does not write it.
* **Build variants.**

  | Variant | Purpose | Differences |
  |---|---|---|
  | `dev` | Daily development | RTT and UART logging, shell on USB CDC, APPROTECT left open, asserts on |
  | `factory` | Production test and calibration | `dev` plus the `hw …` test shell ([§16](#16-bring-up-and-manufacturing-tests)), factory-data writer |
  | `release` | Shipping | Logging minimal, shell off, signed and versioned, APPROTECT policy per [§11.5](#115-debug-access-and-approtect) |
  | `bringup.overlay` | First power-on only | Zephyr's stock `ti,tmag5273` sensor driver on TWIM0 instead of the PPI streaming driver ([§3.3](#33-bring-up-overlay)) |

* **Repository layout** (planned, under `firmware/`):

```
firmware/
  CMakeLists.txt  Kconfig  prj.conf  sysbuild.conf  pm_static.yml
  boards/dial/dial_me_spinner/         HWMv2 board: board.yml, *.dts, *-pinctrl.dtsi, defconfig
  dts/bindings/                        dial,tmag5273-ppi.yaml, dial,detent-stepper.yaml, dial,piezo.yaml, dial,board-signals.yaml
  sysbuild/mcuboot.conf, mcuboot.overlay
  src/main.c
  src/core/        zbus channels, motion seqlock, app mode state machine, settings schema
  src/sensors/     encoder_tmag.c (PPI/DMA driver), encoder_track.c (unwrap, tracker, calibration),
                   predictor.c, imu_lis2dw12.c
  src/actuator/    detent.c (state machine), stepper_pwm.c (nrfx_pwm sequences)
  src/leds/        renderer.c, power_limit.c, effects/*.c
  src/display/     oled_power.c (SSD1351 VCC sequencing, sleep), ui/*.c (LVGL screens)
  src/audio/       piezo.c
  src/input/       press.c (gpio-keys handling, gestures, flick-artifact rejection)
  src/ble/         hid_desc.c, hid_ble.c, adv.c, bond_slots.c, game_svc.c
  src/usb/         usb_composite.c
  src/power/       power_mgr.c, bq25180.c, battery.c
  src/test/        hw shell commands, production test sequencer
  tests/           ztest suites for native_sim (algorithms only; see §17)
```

### 1.2 Peripheral allocation

The nRF52840 shares peripheral IDs between some instances. TWIM0 and TWIM1 are
both used, so **SPIM0 and SPIM1 are unavailable**.

| Peripheral (ID) | Owner | Notes |
|---|---|---|
| RADIO, TIMER0, RTC0, some PPI channels and SWI/EGU | MPSL/SDC | Reserved. Never touch them. |
| RTC1 | Zephyr kernel timer | LFXO 32.768 kHz, 20 ppm |
| TWIM0 (ID 3, shares with SPIM0) | Encoder driver, through nrfx directly | Dedicated to the TMAG5273, about 390 kHz (FREQUENCY = 0x06200000, errata 219, [§4.4](#44-zero-cpu-acquisition-chain)). The Zephyr I2C driver must **not** bind ([§3](#3-devicetree-and-kconfig)). |
| TWIM1 (ID 4, shares with SPIM1) | Zephyr I2C | LIS2DW12 (0x19) and BQ25180 (0x6A, over the link), 250 kHz (errata 219, [§3.1](#31-board-dts-draft)) |
| SPIM2 (ID 35) | Spare | Same-pin fallback for the OLED (8 MHz, [§7.1](#71-spi-link-and-the-spim3-errata)), or for the LEDs (`worldsemi,ws2812-spi`, MOSI only on P0.06) if I2S cannot run with SDOUT alone. It can serve only one of the two. |
| SPIM3 (ID 47) | OLED, through `zephyr,mipi-dbi-spi` | 16 MHz (SPEC §4). Anomalies 198 and 195 apply, with their workarounds ([§7.1](#71-spi-link-and-the-spim3-errata)). Fallback: SPIM2 at 8 MHz on the same pins. |
| I2S (ID 37) | LED ring, `worldsemi,ws2812-i2s` | The nRF52840 has only one I2S |
| QSPI (ID 41) | W25Q128JV | MCUboot secondary slot plus assets |
| PWM0 (ID 28) | Detent stepper, through nrfx_pwm directly | 4 channels at 25 kHz |
| PWM1 (ID 33) | Piezo, Zephyr PWM | Two channels, one inverted |
| PWM2, PWM3 | Spare | |
| UARTE0 (ID 2) | Log TX on P1.00 (SWO pad, TC2030 pin 6) | TX only; RX is disabled |
| USBD | USB composite (HID + 2× CDC ACM) | |
| SAADC | VSYS_SENSE on AIN0 | |
| TIMER1 | Encoder batch timestamps, 1 MHz | Runs only while tracking |
| TIMER2 | Encoder sample counter (low-power counter mode) | Runs only while tracking |
| TIMER3, TIMER4 | Spare | The nrfx NFCT driver may claim one for its field-detect workaround on the nRF52840; check which instance the NCS NFC platform selects |
| GPIOTE | 1 IN channel for TMAG_INT_N while tracking | Every other interrupt pin uses PORT/SENSE |
| PPI | 2 channels + 1 fork for the encoder, via `nrfx_gppi` | Allocate at run time; the SDC reserves its own |
| WDT | Task watchdog | |
| POWER (POF) | Power manager | POF warning at 2.9 V on VDD |
| NFCT | NFC tag emulation, NCS `nfc_t2t` / `nfc_t4t` ([§9.7](#97-nfc-tag-emulation)) | P0.09/P0.10 = NFC1/NFC2; UICR NFCPINS stays in NFC mode; field sense in sleep |
| CC310 | MCUboot signature check, BLE crypto | |

### 1.3 GPIO configuration

Pins and nets come from SPEC §4. The table adds the firmware configuration.
"SENSE" means GPIO DETECT (PORT event), which costs about 2.36 µA in System ON,
against 17.37 µA for a GPIOTE IN channel
([nRF52840 PS sleep currents](https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/_tmp/nrf52840/autodita/current/parameters.i_sleep.html)).

| Pin | Net | Firmware use | Active config | Sleep config |
|---|---|---|---|---|
| P0.13 / P0.14 | OLED_SCK / OLED_MOSI | SPIM3 SCK / MOSI | H0H1 drive | Still driven, low (never float the SSD1351 inputs) |
| P0.15 | OLED_CS_N | `cs-gpios`, active low | Output | High |
| P0.16 | OLED_DC | `dc-gpios` | Output | Low |
| P1.01 | OLED_RES_N | `reset-gpios`, active low | Output | High (keeps GDDRAM; 3.3 µA flows in the 1 MΩ pull-down) |
| P1.02 | OLED_VCC_EN | ON of U21 (TPS22917 boost-input load switch, R25 100 kΩ pull-down), regulator node | Output | Low |
| P0.06 | LED_DIN_MCU | I2S SDOUT (R40 220 Ω at the pin) | **H0H1 drive, required** ([§6.1](#61-hardware-facts-used)) | **GPIO output, driven low** (SPEC §5.4), set after the all-zero frame and before VLED goes off ([§6.4](#64-rail-sequencing)) |
| P1.04 | LED_PWR_EN | ON of U2 (TPS22917 VLED load switch, R3 100 kΩ pull-down), regulator node | Output | Low |
| P0.24 / P0.25 | TMAG_SCL / TMAG_SDA | TWIM0 | S0D1 (default drive), external 4.7 kΩ pull-ups | Disconnected |
| P0.27 | TMAG_INT_N | GPIOTE IN, high-to-low (tracking) | No pull (47 kΩ external) | SENSE low (latched INT) |
| P0.08 / P1.09 | I2C_SCL / I2C_SDA | TWIM1 | S0D1 (default drive), external 4.7 kΩ pull-ups | Disconnected |
| P1.12 | IMU_INT1 | LIS2DW12 wake/6D/tap (push-pull, latched) | Edge | SENSE high |
| P0.30 | IMU_INT2 | LIS2DW12 FIFO watermark (balancing only) | Edge | Interrupt disabled |
| P1.03 | CHG_INT_N | BQ25180 /INT (128 µs pulses), R55 10 kΩ pull-up | SENSE low (LATCH captures short pulses, TVP) | SENSE low |
| P0.09 / P0.10 | NFC1 / NFC2 | NFCT antenna: coil pads J11, C16/C17 180 pF tuning caps ([§9.7](#97-nfc-tag-emulation)) | NFC mode (UICR NFCPINS), tag emulation | NFCT field sense, about 100 nA |
| P1.10 | BTN_N | Dial press (`gpio-keys`) | SENSE low | SENSE low |
| P0.02 | VSYS_SENSE | SAADC AIN0 | Analog | Analog |
| P0.26, P0.05 | MOT_A_IN1, MOT_A_IN2 | PWM0 channels 0, 1 | Standard drive | Disconnected (the DRV8837 internal pull-downs give coast) |
| P0.07, P0.11 | MOT_B_IN1, MOT_B_IN2 | PWM0 channels 2, 3 | Standard drive | Disconnected |
| P1.15 | MOT_NSLEEP | Shared DRV8837 nSLEEP | Output | Low |
| P1.14 | HOME_N | DRV5032FA output (push-pull, low = magnet present, always powered) | Input, no pull | Input, interrupt disabled |
| P0.12 / P1.08 | BUZZ_A / BUZZ_B | PWM1 channel 0 / channel 1 inverted | H0H1 drive | Disconnected (`pwm1_sleep` uses low-power-enable). The piezo is a capacitor between two floating pins, so no current flows; R59 (1 MΩ across BZ1) bleeds any shock-generated charge. |
| P1.00 | SWO | UARTE0 TX (log) | Output | Disconnected |
| P0.03, P0.04, P1.11, P1.13 | TP_SPARE1–4 | Scope timing toggles in `dev` builds | Output | Disconnected. **P0.04 is the only fast spare pin.** |
| P0.28, P0.29, P0.31, P1.05–P1.07 | not connected | none | Reset default (input disconnected) | Same |

Rules the firmware has to respect:

* No fast signal goes on the low-frequency-only pins. The pin map already
  complies; do not move functions around in pinctrl.
* Firmware MUST never drive P0.06 (LED_DIN_MCU) high while VLED is off, nor
  within 10 ms of LED_PWR_EN going high. U2's QOD holds VLED near 0 V, so a
  high DIN sits more than 0.7 V above the LED's VDD (WS2812C abs max
  VDD + 0.7 V) and back-powers the ring through its ESD diode. This is a hard
  rule while R43 (0 Ω) is fitted ([§6.4](#64-rail-sequencing); hardware/sim,
  LSW-3, LED-DATA-V4).
* NFC pins: P0.09/P0.10 are the NFCT antenna (NFC1/NFC2). UICR NFCPINS MUST
  stay in NFC mode, its erased default: do not set `nfct-pins-as-gpios` in
  the board files. In GPIO mode the NFCT stays disabled and the tag cannot
  work (hardware/sim, SLP-V1).
* The TWIM pins keep the default S0D1 drive. Stronger pull-ups or H0D1 drive
  would need series resistors in I2C_SCL/I2C_SDA, so H0D1 is not used
  (hardware/sim, PB-2, NF-3).

### 1.4 Memory map

**Internal flash (1 MB).** NCS Partition Manager; see `pm_static.yml` in
[§11.1](#111-partitions). In short:

| Region | Address | Size |
|---|---|---|
| MCUboot | 0x00000 | 64 KB (size it from a real build with USB CDC serial recovery and QSPI; the research expects about 64 KB) |
| Primary slot (pad + app) | 0x10000 | 928 KB |
| Settings (NVS: bonds, calibration, user config) | 0xF8000 | 32 KB |

**QSPI W25Q128JV (16 MB):** secondary slot (928 KB) at 0x000000; a factory
backup and crash-log area (96 KB) at 0x0E8000; littlefs for assets and logs
(15 MB) at 0x100000.

**RAM (256 KB).**

| User | Size | Notes |
|---|---|---|
| SPIM3 TX / LVGL draw buffers | 16 KB | **Two dedicated 8 KB AHB slaves**, 0x20000000–0x20003FFF (anomaly 198, [§7.1](#71-spi-link-and-the-spim3-errata)) |
| SDC + BT host (2 connections, 2 advertising sets) | about 45 KB | Estimate; read it from the map file |
| LVGL heap | 48 KB | |
| USB stack | about 10 KB | |
| Thread stacks | about 30 KB | See [§2.2](#22-execution-contexts) |
| MCUmgr, littlefs, settings buffers | about 12 KB | |
| LED I2S buffers | 1.4 KB | 2 × 700 B slab blocks for 48 LEDs |
| Encoder DMA ring | 240 B | 40 frames × 6 B |
| Retained RAM: boot-mode request (16 B) plus boot-loop counter, crash summary and the rail-state record (LED_PWR_EN, OLED_VCC_EN, [§15](#15-fault-handling)) | 1 KB | 0x2003FC00–0x2003FFFF, **outside** sram0, seen by both MCUboot and the app ([§3.1](#31-board-dts-draft)) |
| **Total** | **about 165–180 KB** | That leaves 75 KB or more of margin |

---

## 2. Module and thread architecture

### 2.1 Block and thread diagram

```
 ──────────────────────────── hardware events, DMA, ISRs ────────────────────────────
 TMAG INT ─▶ GPIOTE IN ─PPI─▶ TWIM0 STARTRX ─EasyDMA─▶ frame ring (40 × 6 B)
                             TWIM0 STOPPED ─PPI─▶ TIMER2 COUNT ─(CC0 = 4)─▶ enc_isr
                                           └─fork─▶ TIMER1 CAPTURE[0] (batch timestamp)
 BTN_N, IMU_INT1, CHG_INT_N, TMAG_INT_N (sleep) ─▶ GPIO PORT/SENSE ─▶ gpio callbacks
 PWM0 SEQEND0/1 ─▶ stepper_isr (refills one full step of µsteps)
 I2S, SPIM3, QSPI, USBD, SAADC, TWIM1 ─▶ Zephyr driver ISRs;  NFCT ─▶ NCS NFC library
 ─────────────────────────────────────────────────────────────────────────────────────
 enc_isr (TIMER2 IRQ, prio 1): CRC + SET_COUNT check ─▶ calibration ─▶ atan2 ─▶ unwrap ─▶ tracker
        │ writes                                    │ k_event
        ▼                                           ▼
  motion_state (seqlock) ◀── read ── led_thread, hid_thread, ui, game      encoder_thread
                                                                             rest/spin detection,
                                                                             detent crossings,
                                                                             calibration, predictor,
                                                                             W&S arm/disarm
  zbus: motion_evt ─▶ app_thread, hid_thread, audio, power_thread, game_svc
  zbus: input_evt (press.c) ─▶ app_thread, hid_thread
  app_thread ── msgq (mode, strength) ─▶ detent_thread ─▶ stepper_pwm (nrfx_pwm)
  app_thread ── zbus cfg_evt ◀─▶ game_svc (GATT), usb, ui, settings
  power_thread: power states, bq25180, battery ADC, sleep entry/exit ◀─ zbus activity/usb/charge
  hid_thread ─▶ bt_hids (BLE HOGP) │ usbd_hid (USB)        game_svc ─▶ GATT notifications
  led_thread ─▶ ws2812-i2s (I2S DMA, blocking about 2 ms per frame)
  lvgl_thread ─▶ ssd1351 (mipi-dbi-spi, SPIM3 DMA)
  storage_wq ─▶ settings/NVS, littlefs (QSPI)              BT host, SDC, MCUmgr SMP (BLE + CDC)
```

### 2.2 Execution contexts

Zephyr priorities: a lower number is a higher priority, and negative numbers
are cooperative. Interrupt priority 0 belongs to MPSL; Zephyr's default nRF
peripheral priority is 1.

| Context | Priority | Stack | Trigger / rate | Job |
|---|---|---|---|---|
| `enc_isr` (TIMER2 COMPARE0) | IRQ 1 | ISR | Every 4 samples, about 1.3 ms | Validate frames, calibrate, atan2, unwrap, tracker, write `motion_state`. About 15–20 µs per IRQ, about 1.5 % CPU. |
| `stepper_isr` (PWM0) | IRQ 2 | ISR | Once per full step (≤ 1042/s) | Refill the idle PWM sequence with the next full step |
| `encoder_thread` | 1 | 2 KB | `k_event` from `enc_isr`; predictor at 100 Hz | Spin/rest/detent events, calibration accumulation, W&S arming |
| `detent_thread` | 2 | 1.5 KB | Message queue | Actuator state machine and homing |
| `hid_thread` | 3 | 1.5 KB | Motion and input events, paced by HID flow control | Build and route HID reports |
| BT host RX/TX | Cooperative (SDK default) | SDK | | |
| `app_thread` | 5 | 3 KB | zbus | Mode state machine (game, controller, fidget), menus, game logic |
| `power_thread` | 6 | 1.5 KB | 1 s tick plus events | Power states, BQ25180, battery, sleep entry |
| `led_thread` | 7 | 2 KB | 30–240 fps | Effects, power limiter, I2S write |
| `lvgl_thread` | 9 | 4 KB | 30 fps (`lv_timer_handler`) | OLED UI |
| System work queue | Default | 2 KB | | Piezo patterns, NFC tag events, short jobs |
| `storage_wq` | 12 | 2 KB | Deferred | Settings, calibration, littlefs writes (never from an ISR) |
| Shell / log | 14 | 2 KB | | |

### 2.3 Inter-module data

**Motion state.** There is one writer, `enc_isr`. Readers use a lock-free
sequence lock, because the LED renderer and HID read it at a high rate and must
never block the ISR.

```c
struct motion_snapshot {
    int64_t  pos;        /* unwrapped mechanical position, units of 1/(24*65536) turn
                            (= 2^-16 electrical turn); positive = CCW seen from the top */
    float    omega;      /* mechanical rev/s, from the tracking loop */
    uint32_t t_us;       /* timestamp of pos (RTC-corrected, µs) */
    uint8_t  detent;     /* detent index 0..23 (modulo 24, relative) */
    uint8_t  flags;      /* LOCKED, CALIBRATED, ACTUATOR_MOVING, ABS_VALID, COASTING */
};
bool motion_get(struct motion_snapshot *out);   /* retries while the seqlock is odd */
```

**zbus channels**

| Channel | Payload | Producers | Consumers |
|---|---|---|---|
| `motion_evt` | `SPIN_START`, `SPIN_STOP`, `REST`, `DETENT_STEP(±1)`, `TOUCH`, `LOCK_LOST`, `PREDICTION(seg, conf)` | encoder_thread | app, hid, audio, power, game_svc |
| `input_evt` | `PRESS`, `RELEASE`, `CLICK`, `LONG` (≥ 0.6 s), `VLONG` (≥ 5 s), `PRESS_ROTATE(±n)` | press.c | app, hid |
| `cfg_evt` | Changed setting ID | GATT, USB shell, UI | All owners of the setting |
| `power_evt` | State change, battery %, charge state, USB attach | power_thread | app, ui, led, ble |
| `ble_evt` | Slot connected or disconnected, passkey display/confirm, pairing result | ble | app, ui |
| `result_evt` | Spin result | app (game) | game_svc, ui, led |

### 2.4 Application modes

| Mode | Default detent | LEDs | OLED | HID | Notes |
|---|---|---|---|---|---|
| **Game** (decision spinner) | FREE, or BRAKE (free while fast, click plus shoe when slow) | Virtual wheel locked to the ring angle; result flash | Pointer, live segment label, suspense, result | Off by default | Phone app over the custom GATT ([§9.6](#96-custom-game-service)) |
| **Controller** (Surface-Dial-like) | CLICK at full strength (16.5 mN·m, shoe engaged) until the shoe window is measured ([§5.1](#51-coordinates-and-strength-lut)) | Position arc, slot colour | Slot and mode icon, value | On (slot mode: Dial, Media or Scroll) | BLE or USB |
| **Fidget** | FREE or CLICK (user toggles with a long press) | Comet trail proportional to speed | RPM, spin counter, longest spin | Off | Balancing assistant as a sub-mode ([§14.3](#143-balancing-assistant-optional)) |

System screens overlay any mode: pairing (passkey), host-slot menu, charging,
low battery, fault, DFU.

---

## 3. Devicetree and Kconfig

### 3.1 Board DTS draft

The file is `boards/dial/dial_me_spinner/dial_me_spinner_nrf52840.dts`. Pins
follow SPEC §4. Properties marked *(check name)* could not be confirmed
against the current bindings.

```dts
/dts-v1/;
#include <nordic/nrf52840_qiaa.dtsi>
#include <zephyr/dt-bindings/input/input-event-codes.h>
#include <zephyr/dt-bindings/led/led.h>
#include <zephyr/dt-bindings/regulator/nrf5x.h>
#include <zephyr/dt-bindings/pwm/pwm.h>
#include "dial_me_spinner_nrf52840-pinctrl.dtsi"

/ {
	model = "dial-me-spinner rev A";
	compatible = "dial,dial-me-spinner";

	chosen {
		zephyr,sram = &sram0;
		zephyr,flash = &flash0;
		zephyr,console = &uart0;               /* TX-only log on P1.00 */
		zephyr,shell-uart = &cdc_acm_shell;
		zephyr,uart-mcumgr = &cdc_acm_smp;
		zephyr,display = &ssd1351;
		nordic,pm-ext-flash = &w25q128;        /* Partition Manager: external flash */
		zephyr,boot-mode = &boot_mode0;        /* app -> MCUboot serial-recovery request (§11.2) */
	};

	aliases {
		sw0 = &dial_press;
		mcuboot-button0 = &dial_press;         /* hold while plugging USB = serial recovery */
		led-strip = &led_strip;
		watchdog0 = &wdt0;
		accel0 = &imu;
	};

	/* Anomaly 198: dedicated RAM AHB slaves 0 and 1 (2 x 8 KB) for the SPIM3 TX buffers.
	 * sram0 is shrunk to start above them (see §7.1). Check zephyr.map afterwards. */
	spim3_txbuf: memory@20000000 {
		compatible = "zephyr,memory-region", "mmio-sram";
		reg = <0x20000000 DT_SIZE_K(16)>;
		zephyr,memory-region = "SPIM3_TXBUF";
	};

	/* Retained RAM at the top of RAM, outside sram0 (see &sram0 below). MCUboot builds for
	 * this same board, so it sees the same node and the same shrunken sram0 and never puts
	 * its stack or .bss here. If these nodes ever move to an app overlay, copy them into
	 * sysbuild/mcuboot.overlay as well. */
	retained_sram: memory@2003fc00 {
		compatible = "zephyr,memory-region", "mmio-sram";
		reg = <0x2003FC00 DT_SIZE_K(1)>;
		zephyr,memory-region = "RetainedMem";
		status = "okay";

		retainedmem {
			compatible = "zephyr,retained-ram";
			status = "okay";
			#address-cells = <1>;
			#size-cells = <1>;

			boot_mode0: retention@0 {
				compatible = "zephyr,retention";
				status = "okay";
				reg = <0x0 0x10>;
				prefix = [08 04];
				checksum = <1>;                /* CRC-8 */
			};

			crash_info0: retention@10 {        /* boot-loop counter, crash summary, rail-state record (§15) */
				compatible = "zephyr,retention";
				status = "okay";
				reg = <0x10 0x3F0>;
				prefix = [43 52];
				checksum = <2>;                /* CRC-16 */
			};
		};
	};

	buttons {
		compatible = "gpio-keys";
		debounce-interval-ms = <5>;
		dial_press: dial_press {
			gpios = <&gpio1 10 GPIO_ACTIVE_LOW>;   /* BTN_N, Q1B (BSS138DW) on the base board */
			label = "Dial press";
			zephyr,code = <INPUT_KEY_ENTER>;
		};
	};

	vled: regulator-vled {
		compatible = "regulator-fixed";
		regulator-name = "VLED";
		enable-gpios = <&gpio1 4 GPIO_ACTIVE_HIGH>;   /* LED_PWR_EN -> U2 TPS22917 ON (R3 100 kΩ pull-down) */
		startup-delay-us = <10000>;   /* >= 10 ms with P0.06 low before the first frame (hardware/sim, LED-DATA-V4);
		                               * U2 tON about 4 ms: C7 = 1 nF from CT to VIN (SPEC §5.1); scope it at test 12 */
		off-on-delay-us = <30000>;    /* QOD via R4 68 Ω: VLED to 10 % in <= 26.6 ms worst case (SPEC §5.1; hardware/sim, LSW-2) */
	};

	oled_vcc: regulator-oled-vcc {
		compatible = "regulator-fixed";
		regulator-name = "+13V_OLED";
		enable-gpios = <&gpio1 2 GPIO_ACTIVE_HIGH>;   /* OLED_VCC_EN -> U21 TPS22917 ON (R25 100 kΩ pull-down) -> OLED_VIN -> TPS61040 */
		startup-delay-us = <10000>;   /* U21 tON about 4 ms (C37 = 1 nF CT to VIN) + TPS61040 soft start; never below 10 ms
		                               * (hardware/sim, OLED-V2); oled_power.c waits the rest of the 200 ms asynchronously */
		off-on-delay-us = <100000>;
	};

	vsys_sense: vsys-sense {
		compatible = "voltage-divider";
		io-channels = <&adc 0>;
		output-ohms = <1000000>;      /* 2.2 MΩ / 1 MΩ, SPEC §3 */
		full-ohms = <3200000>;
	};

	encoder: encoder {
		compatible = "dial,tmag5273-ppi";       /* custom binding, §3.2 */
		twim = <&i2c0>;
		i2c-addr = <0x35>;                     /* TMAG5273A2 */
		int-gpios = <&gpio0 27 GPIO_ACTIVE_LOW>;
		pole-pairs = <24>;
		frame-bytes = <6>;                     /* TVP: 8 if XZX returns X, Z, X */
	};

	detent: detent-stepper {
		compatible = "dial,detent-stepper";    /* custom binding, §3.2 */
		pwm = <&pwm0>;
		nsleep-gpios = <&gpio1 15 GPIO_ACTIVE_HIGH>;
		home-gpios = <&gpio1 14 GPIO_ACTIVE_LOW>;
		full-steps-per-mm = <50>;              /* M2x0.4 lead, 20 steps/rev -> 0.02 mm/step */
		microsteps = <8>;
		stroke-steps = <375>;                  /* 7.5 mm, click -> park */
		coil-milliohms = <20000>;
	};

	piezo: piezo {
		compatible = "dial,piezo";
		pwms = <&pwm1 0 PWM_USEC(250) PWM_POLARITY_NORMAL>,
		       <&pwm1 1 PWM_USEC(250) PWM_POLARITY_INVERTED>;   /* 4 kHz, complementary */
	};

	board_signals: board-signals {
		compatible = "dial,board-signals";
		imu-int1-gpios = <&gpio1 12 GPIO_ACTIVE_HIGH>;
		imu-int2-gpios = <&gpio0 30 GPIO_ACTIVE_HIGH>;
		chg-int-gpios = <&gpio1 3 GPIO_ACTIVE_LOW>;    /* CHG_INT_N, R55 10 kΩ pull-up */
		led-din-gpios = <&gpio0 6 GPIO_ACTIVE_HIGH>;   /* LED_DIN_MCU forced low while VLED is off (§6.4) */
		tp-spare-gpios = <&gpio0 3 0>, <&gpio0 4 0>, <&gpio1 11 0>, <&gpio1 13 0>;
	};
};

&sram0 {
	reg = <0x20004000 DT_SIZE_K(239)>;   /* 0x20004000-0x2003FBFF: above the anomaly-198 carve-out,
	                                      * below the 1 KB retained RAM at 0x2003FC00 */
};

&uicr {
	gpio-as-nreset;          /* P0.18 = NRESET (TC2030 pin 3) */
	/* NFCPINS stays in NFC mode (erased default): P0.09/P0.10 = NFC1/NFC2, the tag antenna (§9.7) */
};

&nfct {
	status = "okay";         /* NFC tag for the NCS nfc_t2t / nfc_t4t libraries (check whether your NCS needs it) */
};

&reg1 {
	regulator-initial-mode = <NRF5X_REG_MODE_DCDC>;   /* REG1 inductor is inside the module */
};

&gpiote { status = "okay"; };

/* PORT/SENSE for every interrupt pin, so no GPIOTE IN channel is used in sleep.
 * gpio0: P0.27 TMAG_INT_N, P0.30 IMU_INT2 */
&gpio0 { status = "okay"; sense-edge-mask = <0x48000000>; };
/* gpio1: P1.03 CHG_INT_N, P1.10 BTN_N, P1.12 IMU_INT1, P1.14 HOME_N */
&gpio1 { status = "okay"; sense-edge-mask = <0x0000540C>; };

&wdt0 { status = "okay"; };

&adc {
	#address-cells = <1>;
	#size-cells = <0>;
	status = "okay";
	channel@0 {
		reg = <0>;
		zephyr,gain = "ADC_GAIN_1_6";            /* 0.6 V ref -> 3.6 V full scale */
		zephyr,reference = "ADC_REF_INTERNAL";
		zephyr,acquisition-time = <ADC_ACQ_TIME(ADC_ACQ_TIME_MICROSECONDS, 40)>;
		zephyr,input-positive = <NRF_SAADC_AIN0>; /* P0.02 VSYS_SENSE */
		zephyr,resolution = <12>;
		zephyr,oversampling = <3>;               /* 8x */
	};
};

/* TWIM0 is owned by the encoder's PPI/EasyDMA driver. The node is kept for its pinctrl
 * and register address; "disabled" stops Zephyr's I2C driver from binding to it. */
&i2c0 {
	compatible = "nordic,nrf-twim";
	status = "disabled";
	clock-frequency = <I2C_BITRATE_FAST>;   /* unused: the encoder driver writes FREQUENCY = 0x06200000 (§4.4) */
	pinctrl-0 = <&i2c0_default>;
	pinctrl-1 = <&i2c0_sleep>;
	pinctrl-names = "default", "sleep";
};

&i2c1 {
	compatible = "nordic,nrf-twim";
	status = "okay";
	/* nRF52840 errata 219: at 400 kHz the TWIM holds SCL low for only 1.25 µs, below the 1.3 µs tLOW of
	 * the LIS2DW12 and BQ25180. Run at 250 kHz (K250, FREQUENCY = 0x04000000; write it after init if the
	 * driver rejects 250000), or at I2C_BITRATE_STANDARD if the bring-up SCL rise time at J3 exceeds
	 * 250 ns (hardware/sim, NF-1, PB-2). Never I2C_BITRATE_FAST. */
	clock-frequency = <250000>;
	pinctrl-0 = <&i2c1_default>;
	pinctrl-1 = <&i2c1_sleep>;
	pinctrl-names = "default", "sleep";

	imu: lis2dw12@19 {
		compatible = "st,lis2dw12";       /* hardware description; the app drives it (§14) */
		reg = <0x19>;
		irq-gpios = <&gpio1 12 GPIO_ACTIVE_HIGH>, <&gpio0 30 GPIO_ACTIVE_HIGH>;
		int-pin = <1>;
	};

	charger: bq25180@6a {
		compatible = "ti,bq25180";        /* app driver bq25180.c; upstream charger driver off */
		reg = <0x6a>;
		constant-charge-current-max-microamp = <400000>;   /* (check name) */
	};
};

&spi3 {
	compatible = "nordic,nrf-spim";
	status = "okay";
	pinctrl-0 = <&spi3_default>;
	pinctrl-1 = <&spi3_sleep>;
	pinctrl-names = "default", "sleep";
	cs-gpios = <&gpio0 15 GPIO_ACTIVE_LOW>;   /* OLED_CS_N */
};

/ {
	mipi_dbi: mipi-dbi {
		compatible = "zephyr,mipi-dbi-spi";
		spi-dev = <&spi3>;
		dc-gpios = <&gpio0 16 GPIO_ACTIVE_HIGH>;      /* OLED_DC */
		reset-gpios = <&gpio1 1 GPIO_ACTIVE_LOW>;     /* OLED_RES_N, 1 MΩ pull-down */
		write-only;                                   /* no MISO (check name) */
		#address-cells = <1>;
		#size-cells = <0>;

		ssd1351: ssd1351@0 {
			compatible = "solomon,ssd1351";
			reg = <0>;
			mipi-max-frequency = <16000000>;          /* SSD1351 max 20 MHz */
			mipi-mode = "MIPI_DBI_MODE_SPI_4WIRE";    /* string enum in Zephyr 4.x (the driver uses DT_STRING_UPPER_TOKEN) */
			width = <128>;
			height = <128>;
			/* The values below map to the init commands in §7.2. All ten are *required* by
			 * solomon,ssd135x-common.yaml (checked against Zephyr main, 2026-10). */
			current-att = <0x08>;                     /* C7h master current, 08h = 56 % (§7.2 step 13) */
			display-offset = <0x00>;                  /* A2h */
			start-line = <0x00>;                      /* A1h */
			multiplex-ratio = <127>;                  /* CAh 7F */
			oscillator-freq = <0xF1>;                 /* B3h */
			phase-length = <0x32>;                    /* B1h */
			remap-value = <0x74>;                     /* A0h: 65k RGB565, COM split; flip bits for mounting */
			precharge-time = <0x01>;                  /* B6h */
			precharge-voltage = <0x17>;               /* BBh */
			vcomh-voltage = <0x05>;                   /* BEh, 0.82 x VCC */
		};
	};
};

&i2s0 {
	compatible = "nordic,nrf-i2s";
	status = "okay";
	pinctrl-0 = <&i2s0_default>;
	pinctrl-1 = <&i2s0_sleep>;
	pinctrl-names = "default", "sleep";
	clock-source = "PCLK32M_HFXO";     /* bit period exactly 1.25 µs; HFINT (±8 %) breaks T1H/T0L (§6.1, LED-DATA-V2) */

	led_strip: ws2812 {
		compatible = "worldsemi,ws2812-i2s";
		chain-length = <48>;           /* SPEC §5.4/§8: D101 at θ=0°, CCW */
		color-mapping = <LED_COLOR_ID_GREEN LED_COLOR_ID_RED LED_COLOR_ID_BLUE>;
		lrck-period = <10>;            /* SCK 3.2 MHz -> 4 SCK = 1.25 µs per LED bit */
		nibble-zero = <0x8>;           /* T0H 312.5 ns / T0L 937.5 ns */
		nibble-one = <0xc>;            /* T1H 625 ns / T1L 625 ns (default 0xE gives T1L 312 ns: out of V6 spec) */
		reset-delay = <300>;           /* V6 reset > 280 µs; the driver default of 8 µs is too short */
		extra-wait-time = <300>;       /* keep the default; lower only after testing */
	};
};

&qspi {
	status = "okay";
	pinctrl-0 = <&qspi_default>;
	pinctrl-1 = <&qspi_sleep>;
	pinctrl-names = "default", "sleep";

	w25q128: w25q128jv@0 {
		compatible = "nordic,qspi-nor";
		reg = <0>;
		writeoc = "pp4o";
		readoc = "read4io";
		sck-frequency = <32000000>;    /* TVP: drop to 16 MHz if reads fail at 32 */
		jedec-id = [ef 40 18];
		size = <134217728>;            /* bits = 128 Mbit */
		quad-enable-requirements = "S2B1v5";   /* TVP: -IQ parts may ship with QE=1; read SR2 at bring-up */
		has-dpd;
		t-enter-dpd = <3000>;
		t-exit-dpd = <3000>;
	};
};

/* PWM0 is owned by the detent stepper driver through nrfx_pwm (complex playback).
 * Keep the node for its pinctrl; "disabled" stops Zephyr's PWM driver from binding. */
&pwm0 {
	status = "disabled";
	pinctrl-0 = <&pwm0_default>;
	pinctrl-1 = <&pwm0_sleep>;
	pinctrl-names = "default", "sleep";
};

&pwm1 {
	status = "okay";
	pinctrl-0 = <&pwm1_default>;
	pinctrl-1 = <&pwm1_sleep>;
	pinctrl-names = "default", "sleep";
};

&uart0 {
	compatible = "nordic,nrf-uarte";
	status = "okay";
	current-speed = <1000000>;
	disable-rx;
	pinctrl-0 = <&uart0_default>;
	pinctrl-1 = <&uart0_sleep>;
	pinctrl-names = "default", "sleep";
};

zephyr_udc0: &usbd {
	compatible = "nordic,nrf-usbd";
	status = "okay";

	cdc_acm_smp: cdc_acm_smp { compatible = "zephyr,cdc-acm-uart"; };     /* MCUmgr SMP / DFU */
	cdc_acm_shell: cdc_acm_shell { compatible = "zephyr,cdc-acm-uart"; }; /* shell + log */

	hid_dial: hid_dial {
		compatible = "zephyr,hid-device";
		interface-name = "Dial";
		protocol-code = "none";
		in-report-size = <6>;            /* largest input report (ID 3) + report-ID byte */
		in-polling-period-us = <4000>;
	};
};
```

**Pinctrl** (`dial_me_spinner_nrf52840-pinctrl.dtsi`, abridged):

```dts
&pinctrl {
	/* TWIM pins: default S0D1 drive, no nordic,drive-mode (§1.3; hardware/sim, PB-2, NF-3) */
	i2c0_default: i2c0_default { group1 { psels = <NRF_PSEL(TWIM_SCL, 0, 24)>, <NRF_PSEL(TWIM_SDA, 0, 25)>; }; };
	i2c0_sleep:   i2c0_sleep   { group1 { psels = <NRF_PSEL(TWIM_SCL, 0, 24)>, <NRF_PSEL(TWIM_SDA, 0, 25)>; low-power-enable; }; };
	i2c1_default: i2c1_default { group1 { psels = <NRF_PSEL(TWIM_SCL, 0, 8)>,  <NRF_PSEL(TWIM_SDA, 1, 9)>; }; };
	i2c1_sleep:   i2c1_sleep   { group1 { psels = <NRF_PSEL(TWIM_SCL, 0, 8)>,  <NRF_PSEL(TWIM_SDA, 1, 9)>; low-power-enable; }; };

	spi3_default: spi3_default {
		group1 { psels = <NRF_PSEL(SPIM_SCK, 0, 13)>, <NRF_PSEL(SPIM_MOSI, 0, 14)>;
			 nordic,drive-mode = <NRF_DRIVE_H0H1>; };
	};
	spi3_sleep: spi3_sleep {   /* no low-power-enable: keep SCK/MOSI driven low into the powered SSD1351 */
		group1 { psels = <NRF_PSEL(SPIM_SCK, 0, 13)>, <NRF_PSEL(SPIM_MOSI, 0, 14)>; };
	};

	i2s0_default: i2s0_default {   /* SCK/LRCK not routed (TVP) */
		/* H0H1 is REQUIRED: standard drive cannot guarantee the WS2812C windows (hardware/sim, LED-DATA-V1) */
		group1 { psels = <NRF_PSEL(I2S_SDOUT, 0, 6)>; nordic,drive-mode = <NRF_DRIVE_H0H1>; };
	};
	/* No low-power-enable: SPEC §5.4 wants P0.06 driven low (not floating) while VLED is off.
	 * led_thread also forces it low through led-din-gpios before VLED goes off (§6.4). */
	i2s0_sleep:   i2s0_sleep   { group1 { psels = <NRF_PSEL(I2S_SDOUT, 0, 6)>; }; };

	pwm0_default: pwm0_default {
		group1 { psels = <NRF_PSEL(PWM_OUT0, 0, 26)>, <NRF_PSEL(PWM_OUT1, 0, 5)>,
			         <NRF_PSEL(PWM_OUT2, 0, 7)>,  <NRF_PSEL(PWM_OUT3, 0, 11)>; };
	};
	pwm0_sleep: pwm0_sleep {
		group1 { psels = <NRF_PSEL(PWM_OUT0, 0, 26)>, <NRF_PSEL(PWM_OUT1, 0, 5)>,
			         <NRF_PSEL(PWM_OUT2, 0, 7)>,  <NRF_PSEL(PWM_OUT3, 0, 11)>; low-power-enable; };
	};

	pwm1_default: pwm1_default {
		group1 { psels = <NRF_PSEL(PWM_OUT0, 0, 12)>, <NRF_PSEL(PWM_OUT1, 1, 8)>;
			 nordic,drive-mode = <NRF_DRIVE_H0H1>; };
	};
	pwm1_sleep: pwm1_sleep {
		group1 { psels = <NRF_PSEL(PWM_OUT0, 0, 12)>, <NRF_PSEL(PWM_OUT1, 1, 8)>; low-power-enable; };
	};

	qspi_default: qspi_default {
		group1 { psels = <NRF_PSEL(QSPI_SCK, 0, 19)>, <NRF_PSEL(QSPI_CSN, 0, 17)>,
			         <NRF_PSEL(QSPI_IO0, 0, 20)>, <NRF_PSEL(QSPI_IO1, 0, 21)>,
			         <NRF_PSEL(QSPI_IO2, 0, 22)>, <NRF_PSEL(QSPI_IO3, 0, 23)>;
			 nordic,drive-mode = <NRF_DRIVE_H0H1>; };
	};
	qspi_sleep: qspi_sleep {   /* SCK/IO0-IO3 pulled down so they do not float in DPD (hardware/sim, SLP-4);
	                            * IO2 = /WP and IO3 = /HOLD may be held low only with QE = 1 (test 5) */
		group1 { psels = <NRF_PSEL(QSPI_SCK, 0, 19)>, <NRF_PSEL(QSPI_IO0, 0, 20)>,
			         <NRF_PSEL(QSPI_IO1, 0, 21)>, <NRF_PSEL(QSPI_IO2, 0, 22)>,
			         <NRF_PSEL(QSPI_IO3, 0, 23)>; low-power-enable; bias-pull-down; };
		group2 { psels = <NRF_PSEL(QSPI_CSN, 0, 17)>; low-power-enable; bias-pull-up; };
	};

	uart0_default: uart0_default { group1 { psels = <NRF_PSEL(UART_TX, 1, 0)>; }; };
	uart0_sleep:   uart0_sleep   { group1 { psels = <NRF_PSEL(UART_TX, 1, 0)>; low-power-enable; }; };
};
```

### 3.2 Custom bindings

Both custom drivers own their peripheral through nrfx. They apply pinctrl with
`PINCTRL_DT_DEFINE()` and `pinctrl_apply_state()` on the *disabled* peripheral
node, which works because the nRF pinctrl driver only needs that node's `reg`
address. **Check this on your Zephyr version.** If it fails, fall back to nrfx
pin numbers taken from `NRF_DT_GPIOS_TO_PSEL()`.

```yaml
# dts/bindings/dial,tmag5273-ppi.yaml
description: TMAG5273 on a dedicated TWIM, streamed by GPIOTE -> PPI -> TWIM EasyDMA
compatible: "dial,tmag5273-ppi"
properties:
  twim:        { type: phandle, required: true }
  i2c-addr:    { type: int, default: 0x35 }
  int-gpios:   { type: phandle-array, required: true }
  pole-pairs:  { type: int, default: 24 }
  frame-bytes: { type: int, default: 6, enum: [6, 8] }

# dts/bindings/dial,detent-stepper.yaml
description: Micro linear stepper on 2x DRV8837 driven by nrfx_pwm complex playback
compatible: "dial,detent-stepper"
properties:
  pwm:                { type: phandle, required: true }
  nsleep-gpios:       { type: phandle-array, required: true }
  home-gpios:         { type: phandle-array, required: true }
  full-steps-per-mm:  { type: int, required: true }
  microsteps:         { type: int, default: 8 }
  stroke-steps:       { type: int, required: true }
  coil-milliohms:     { type: int, required: true }
```

`dial,piezo` (a `pwms` array) and `dial,board-signals` (named `*-gpios`) are
trivial bindings.

### 3.3 Bring-up overlay

For first power-on, use Zephyr's stock driver to prove the TMAG5273, its bus and
the magnet field before the PPI chain exists:

```dts
/* boards/dial/dial_me_spinner/bringup.overlay */
/delete-node/ &encoder;
&i2c0 {
	status = "okay";
	tmag5273: tmag5273@35 {
		compatible = "ti,tmag5273";
		reg = <0x35>;
		int-gpios = <&gpio0 27 GPIO_ACTIVE_LOW>;
		/* axis/range/averaging properties per ti,tmag5273.yaml (check names) */
	};
};
```

Then `sensor get tmag5273` in the shell shows raw X/Y/Z while you turn the ring
by hand.

### 3.4 Kconfig highlights (`prj.conf`)

```conf
# Core
CONFIG_FPU=y
CONFIG_GPIO=y
CONFIG_PINCTRL=y
CONFIG_CLOCK_CONTROL_NRF_K32SRC_XTAL=y
CONFIG_CLOCK_CONTROL_NRF_K32SRC_20PPM=y
CONFIG_PM_DEVICE=y
CONFIG_PM_DEVICE_RUNTIME=y
CONFIG_ZBUS=y
CONFIG_WATCHDOG=y
CONFIG_TASK_WDT=y
CONFIG_REBOOT=y
CONFIG_RETAINED_MEM=y
CONFIG_RETENTION=y
CONFIG_RETENTION_BOOT_MODE=y          # app -> MCUboot serial recovery request; needs the
                                      # zephyr,boot-mode chosen node and retained RAM (§3.1)
# nrfx peripherals owned directly by the app
CONFIG_NRFX_TWIM0=y
CONFIG_NRFX_TIMER1=y
CONFIG_NRFX_TIMER2=y
CONFIG_NRFX_PWM0=y
CONFIG_NRFX_PPI=y
# Buses, drivers
CONFIG_I2C=y
CONFIG_SPI=y
CONFIG_NRF52_ANOMALY_198_WORKAROUND=y # default y when spi3 is SPIM; keep it
CONFIG_PWM=y
CONFIG_ADC=y
CONFIG_SENSOR=y                       # voltage-divider
CONFIG_VOLTAGE_DIVIDER=y              # (check name)
CONFIG_LIS2DW12=n                     # app-level driver, §14
CONFIG_CHARGER=n                      # app-level driver, §13
CONFIG_REGULATOR=y
CONFIG_INPUT=y
# Storage
CONFIG_FLASH=y
CONFIG_NORDIC_QSPI_NOR=y
CONFIG_SETTINGS=y
CONFIG_NVS=y
CONFIG_SETTINGS_NVS=y
CONFIG_FILE_SYSTEM=y
CONFIG_FILE_SYSTEM_LITTLEFS=y
# LEDs
CONFIG_I2S=y
CONFIG_LED_STRIP=y
CONFIG_WS2812_STRIP_I2S=y
# Display + LVGL
CONFIG_DISPLAY=y
CONFIG_MIPI_DBI=y
CONFIG_MIPI_DBI_SPI=y
CONFIG_LVGL=y
CONFIG_LV_COLOR_DEPTH_16=y
CONFIG_LV_Z_MEM_POOL_SIZE=49152
CONFIG_LV_Z_DOUBLE_VDB=y
CONFIG_LV_Z_VDB_SIZE=25               # 25 % of 128 rows = 32 rows = 8 KB per buffer
CONFIG_LV_Z_VDB_CUSTOM_SECTION=y      # place .lvgl_buf in SPIM3_TXBUF (linker snippet)
CONFIG_LV_Z_VDB_ALIGN=8192            # (check name/limit)
# Bluetooth
CONFIG_BT=y
CONFIG_BT_PERIPHERAL=y
CONFIG_BT_MAX_CONN=2                  # 1 HID host + 1 app phone
CONFIG_BT_MAX_PAIRED=6                # 3 host slots + 3 phones
CONFIG_BT_ID_MAX=4                    # ID0 = app, ID1..3 = host slots
CONFIG_BT_SMP=y
CONFIG_BT_SETTINGS=y
CONFIG_BT_PRIVACY=y
CONFIG_BT_EXT_ADV=y
CONFIG_BT_EXT_ADV_MAX_ADV_SET=2
CONFIG_BT_DEVICE_NAME="DialSpinner"   # 11 characters max for Swift Pair (§9.3)
CONFIG_BT_DEVICE_APPEARANCE=960       # 0x03C0 Generic HID
CONFIG_BT_GATT_AUTHORIZATION_CUSTOM=y # deny HIDS to the app identity (§9.4)
CONFIG_BT_HIDS=y
CONFIG_BT_HIDS_MAX_CLIENT_COUNT=1
CONFIG_BT_HIDS_INPUT_REP_MAX=3
CONFIG_BT_HIDS_DEFAULT_PERM_RW_ENCRYPT=y
CONFIG_BT_BAS=y
CONFIG_BT_DIS=y
CONFIG_BT_DIS_PNP=y
CONFIG_BT_L2CAP_TX_MTU=247
CONFIG_BT_BUF_ACL_RX_SIZE=251
CONFIG_BT_BUF_ACL_TX_SIZE=251
CONFIG_BT_CTLR_DATA_LENGTH_MAX=251
CONFIG_BT_CTLR_TX_PWR_DYNAMIC_CONTROL=y
# NFC tag (§9.7); UICR NFCPINS stays in NFC mode (check names against your NCS)
CONFIG_NFC_T2T_NRFXLIB=y              # or CONFIG_NFC_T4T_NRFXLIB=y; start with one tag type per build
CONFIG_NFC_NDEF=y
CONFIG_NFC_NDEF_MSG=y
CONFIG_NFC_NDEF_RECORD=y
CONFIG_NFC_NDEF_URI_REC=y             # plus TEXT_RECORD etc. for the record types the app offers
# USB (device_next)
CONFIG_USB_DEVICE_STACK_NEXT=y
CONFIG_USBD_HID_SUPPORT=y
CONFIG_USBD_CDC_ACM_CLASS=y
# MCUmgr / DFU
CONFIG_MCUMGR=y
CONFIG_MCUMGR_TRANSPORT_BT=y
CONFIG_MCUMGR_TRANSPORT_UART=y
CONFIG_MCUMGR_GRP_IMG=y
CONFIG_MCUMGR_GRP_OS=y
CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN=y   # (check name) SMP only over an authenticated link
```

```conf
# sysbuild.conf
SB_CONFIG_BOOTLOADER_MCUBOOT=y
SB_CONFIG_MCUBOOT_MODE_SWAP_USING_MOVE=y
SB_CONFIG_PM_EXTERNAL_FLASH_MCUBOOT_SECONDARY=y
SB_CONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256=y
SB_CONFIG_BOOT_SIGNATURE_KEY_FILE="\${APP_DIR}/keys/release-p256.pem"   # never commit the release key
```

```conf
# sysbuild/mcuboot.conf (excerpt; the QSPI and serial-recovery lines are in §11.2)
CONFIG_RETAINED_MEM=y
CONFIG_RETENTION=y
CONFIG_RETENTION_BOOT_MODE=y
CONFIG_BOOT_SERIAL_BOOT_MODE=y        # enter serial recovery when the app sets the boot mode (check name)
```

---

## 4. Rotation-sensing pipeline

### 4.1 Signal at the sensor

SPEC places the TMAG5273A2 on the main-board **underside** at r = 29 mm,
θ = 270°, with its long axis radial. Sensor X is therefore tangential, Y radial
and Z axial. The board underside is at z = 29.1 and the magnet faces at
z = 25.6, so the board-to-magnet distance is 3.5 mm. The Hall element sits
0.73 mm inside the package top
([TMAG5273 DS, Fig. 6-2](https://www.ti.com/lit/ds/symlink/tmag5273.pdf)), and
the DBV body is 0.9–1.45 mm tall. The **element-to-magnet gap is therefore
about 2.7–3.3 mm**, about 3.1 mm nominal.

I re-simulated SPEC's track (48 alternating N52 Ø2×2 discs at R = 29.0 mm,
J = 1.44 T, magpylib 5.2.3; the scripts are in the session scratchpad):

| Element–magnet gap | Bt peak (sensor X) | Bz peak (sensor Z) | Radial |
|---|---|---|---|
| 2.60 mm | 21.8 mT | 26.8 mT | < 0.8 mT |
| 2.85 mm | 17.1 mT | 20.6 mT | |
| **3.10 mm (nominal)** | **13.4 mT** | **15.9 mT** | |
| 3.40 mm | 10.1 mT | 11.8 mT | |
| 3.70 mm | 7.6 mT | 8.7 mT | |

* The mean field is about 0 because the track alternates. The detent carriage
  is 180° away, about 50–58 mm from the sensor, and contributes 0.03 mT or
  less.
* Noise in XZX mode with 4× averaging is σx ≈ 52 µT and σz ≈ 45 µT (sensing
  research, verified). That gives σφ ≈ 0.2° electrical ≈ **0.009° mechanical
  RMS** at the nominal gap. HID needs 0.1°.
* The gap varies by unit (package height, magnet flushness ±0.1 mm), so the
  amplitude varies by about 2×. Calibration absorbs this ([§4.6](#46-calibration)).
  The A2 range (±133 mT) is never close to saturation.

**Sampling margin.** XZX with 4× averaging gives 3.1 kSPS (322 µs). The
oscillator is untrimmed, so the real rate can differ by about ±10 %; firmware
measures it ([§4.4](#44-zero-cpu-acquisition-chain)).

| Ring speed | Electrical advance per sample |
|---|---|
| 1 rev/s | 2.8° |
| 5 rev/s | 13.9° |
| 10 rev/s | 27.9° |
| 20 rev/s | 55.7° |
| 30 rev/s | 83.6° |
| Naive-unwrap limit (180°/sample) | 64.6 rev/s |

A hand-flicked ring reaches about 5–20 rev/s, so the margin is at least 3×.
Because the unwrap uses the predicted advance ([§4.5](#45-per-sample-processing)),
the real limit is set by prediction error, not by the raw advance.

### 4.2 TMAG5273 tracking configuration

Address 0x35 (A2). These register values are from the sensing research (FW-1)
and were checked bit by bit by its verifier against
[TMAG5273 DS SLYS045C](https://www.ti.com/lit/ds/symlink/tmag5273.pdf),
Tables 8-3 to 8-11.

| Order | Register (address) | Value | Meaning |
|---|---|---|---|
| 1 | SENSOR_CONFIG_2 (0x03) | 0x00 | ±133 mT ranges, no on-chip angle |
| 2 | SENSOR_CONFIG_1 (0x02) | 0xB0 | MAG_CH_EN = 0xB (XZX pseudo-simultaneous). Use 0xA (YZY) if the part is rotated 90°. |
| 3 | INT_CONFIG_1 (0x08) | 0xA4 | RSLT_INT = 1 (interrupt on conversion complete), INT_STATE = 1 (10 µs pulse), INT_MODE = 001 (INT pin) |
| 4 | T_CONFIG (0x07) | 0x00 | Temperature channel off |
| 5 | DEVICE_CONFIG_1 (0x00) | 0xA9 | CRC_EN = 1, MAG_TEMPCO = 01 (NdFeB 0.12 %/°C), CONV_AVG = 010 (4×), I2C_RD = 01 (1-byte read of 16-bit data + CONV_STATUS) |
| 6 | DEVICE_CONFIG_2 (0x01) | 0x02 | THR_HYST = 000, LP_LN = 0 (low active current, 2.3 mA), OPERATING_MODE = 10 (continuous). **Write this last; it starts conversions.** |

Init procedure:

1. At POR: if the +3V3 ramp is slower than 3 V/ms (TVP; it is probably faster),
   run one Wake-up&Sleep cycle first, as the datasheet requires.
2. Check identity with standard reads: DEVICE_ID (0x0D) bits 1:0 = 2 (x2
   range); MANUFACTURER_ID (0x0E/0x0F) = 0x49, 0x54 ("TI").
3. Write steps 1–4, then write DEVICE_CONFIG_1 = 0x28 temporarily (the same,
   but CRC off and standard reads), and read everything back.
4. **Clear POR.** CONV_STATUS (0x18) resets to 0x10: POR (bit 4) is set after
   every power-up and is R/W1C, so it stays set until the host writes a 1 to
   it ([TMAG5273 DS SLYS045C, Table 8-27](https://www.ti.com/lit/ds/symlink/tmag5273.pdf)).
   Write CONV_STATUS = 0x10, read it back, and require POR = 0 and
   DIAG_STATUS = 0. If POR is still 1, retry once, then report E_ENC_POR.
   Without this step every streamed frame carries POR = 1 and the per-frame
   check in [§4.5](#45-per-sample-processing) would re-initialise forever.
5. Write DEVICE_CONFIG_1 = 0xA9 and finally DEVICE_CONFIG_2 = 0x02.

**CONV_STATUS fields** (Table 8-27): SET_COUNT = bits 7:5 (3-bit rolling count
of conversion sets), POR = bit 4 (R/W1C, reset value 1), bits 3:2 reserved,
DIAG_STATUS = bit 1 (VCC undervoltage, memory CRC, INT pin or clock fault),
RESULT_STATUS = bit 0 (conversion data ready). Once init has cleared POR, a
POR = 1 in any later frame or read means the TMAG has reset since init.

### 4.3 Read frame and CRC

In 1-byte read mode the master sends only the address byte with R = 1 (0x6B),
and the TMAG returns:

```
X_MSB  X_LSB  Z_MSB  Z_LSB  CONV_STATUS  CRC8          (6 bytes; TVP: XZX might return X, Z, X -> 8 bytes)
```

* Bus time at about 390 kHz (errata 219 setting, [§4.4](#44-zero-cpu-acquisition-chain)):
  7 × 9 bits × 2.56 µs plus start/stop ≈ **167 µs**, against a 322 µs
  conversion period. An 8-byte frame (about 213 µs) would still fit.
* **CRC-8:** polynomial x⁸+x²+x+1 (0x07), initial value 0xFF, computed **over
  the command byte 0x6B followed by the 5 data bytes**. The verifier found
  that the CRC includes the command byte; code that covers only the data flags
  every frame as bad.
* CONV_STATUS ([§4.2](#42-tmag5273-tracking-configuration)): SET_COUNT (bits
  7:5) is a 3-bit rolling counter, so compare it **modulo 8**:
  gap = (set_count − last_set_count) & 7. gap = 1 is normal, gap = 0 is a
  duplicate read, and gap = k > 1 means k − 1 conversions were missed. POR
  (bit 4) and DIAG_STATUS (bit 1) must both read 0.
* The result registers do not update while a read is in progress, so each read
  must finish before the next conversion ends. 167 µs within 322 µs satisfies
  that.

```c
static uint8_t tmag_crc8(const uint8_t *p, size_t n)  /* call with {0x6B, d0..d4} */
{
    uint8_t c = 0xFF;
    while (n--) {
        c ^= *p++;
        for (int i = 0; i < 8; i++) c = (c & 0x80) ? (uint8_t)((c << 1) ^ 0x07) : (uint8_t)(c << 1);
    }
    return c;
}
```

### 4.4 Zero-CPU acquisition chain

Each sample costs no CPU. The CPU runs once every 4 samples.

| Element | Configuration |
|---|---|
| GPIOTE IN channel (allocated with `nrfx_gpiote_channel_alloc`) | PSEL = P0.27, POLARITY = HiToLo, event only. Before using it, disable the Zephyr GPIO interrupt on this pin. |
| PPI channel A | GPIOTE IN event → TWIM0.TASKS_STARTRX |
| TWIM0 | ENABLE; ADDRESS = 0x35; **FREQUENCY = 0x06200000** (about 390 kHz), written after init and never K400: nRF52840 errata 219 makes K400 hold SCL low for only 1.25 µs, below the TMAG5273's 1.3 µs minimum (hardware/sim, NF-1; simulated tLOW 1.31 µs with this value); RXD.PTR = ring[0]; RXD.MAXCNT = 6 (or 8); **RXD.LIST = ArrayList** (the pointer advances by MAXCNT per transfer); SHORTS = LASTRX_STOP; INTEN = ERROR |
| PPI channel B | TWIM0.EVENTS_STOPPED → TIMER2.TASKS_COUNT, **fork** → TIMER1.TASKS_CAPTURE[0] |
| TIMER2 | Low-power counter mode, 16-bit, CC[0] = 4, SHORTS COMPARE0_CLEAR, INTEN COMPARE0 → `enc_isr` at IRQ priority 1 |
| TIMER1 | Timer mode, 1 MHz, 32-bit, free-running while tracking |
| Ring | 32 frames + 8 guard frames. The ISR writes RXD.PTR back to ring[0] when 28 or more frames are used. The register is double-buffered after RXSTARTED, so the write takes effect at the next STARTRX, and the guard absorbs up to 2.6 ms of ISR latency. |

Notes:

* nrfx implements this pattern: `nrfx_twim_xfer()` with
  `NRFX_TWIM_FLAG_HOLD_XFER | NRFX_TWIM_FLAG_REPEATED_XFER | NRFX_TWIM_FLAG_RX_POSTINC`
  and `nrfx_twim_start_task_address_get()`. Prefer it to raw registers.
  *TVP:* check that the RXD.PTR read-back reflects the ArrayList increment on
  this silicon.
* **Latency.** Interrupting every 4 samples gives about 1.3 ms of output
  latency. The verifier corrected the research's 32-sample batch, which gives
  about 10 ms. TIMER1 keeps only the **last** capture of each batch, so the
  per-sample times are `t_last − (3 − k)·T_s`.
* **Sample period T_s.** Measure it against RTC1 (LFXO, 20 ppm) over 100 ms
  windows: T_s = Δt_RTC / Δsamples. Use the measured T_s in the tracker and in
  every rad/s conversion. The TMAG oscillator is untrimmed.
* **Errors.** A TWIM ERROR (NACK or overrun) raises the TWIM0 IRQ. The handler
  stops the chain, runs `nrfx_twim_bus_recover()`, re-inits the TMAG and
  re-arms. The tracker coasts meanwhile.
* **IRQ wiring.** Zephyr does not own TWIM0, TIMER1 or TIMER2, so connect
  their handlers yourself: `IRQ_CONNECT(SPIM0_SPIS0_TWIM0_TWIS0_SPI0_TWI0_IRQn, 1,
  nrfx_isr, nrfx_twim_0_irq_handler, 0)`, and likewise for TIMER2 (the batch
  IRQ). TIMER1 needs no IRQ.
* **Anomaly 89** (TWIM + GPIOTE static current) applies only to Engineering A
  silicon. The verifier traced it in the nrfx errata code, so no workaround is
  needed. Keep the rule to disable GPIOTE IN in sleep for the 17 µA vs 2.4 µA
  reason.

### 4.5 Per-sample processing

This runs in `enc_isr` for each frame in the batch. All integer conversions
below are defined behaviour in ISO C; copy them as written.

```c
/* Helpers (all well defined in ISO C) */
static inline int32_t wrap16(uint16_t d)  { return (d >= 32768u) ? (int32_t)d - 65536 : (int32_t)d; }
static inline int64_t floor_div256(int64_t v) { return (v >= 0) ? (v >> 8) : ~((~v) >> 8); }

#define CS_SET_COUNT(s)  (((s) >> 5) & 0x7u)   /* CONV_STATUS, DS Table 8-27 */
#define CS_POR           0x10u                 /* bit 4, R/W1C, cleared at init (§4.2) */
#define CS_DIAG          0x02u                 /* bit 1 */

/* 1. Validate */
if (crc_bad) { stats.crc++; continue; }        /* the next good frame's SET_COUNT gap covers it */
if (status & (CS_POR | CS_DIAG)) { schedule_reinit(); continue; }   /* POR = 1: TMAG reset since init */
uint32_t sc  = CS_SET_COUNT(status);
uint32_t gap = (sc - trk.last_set_count) & 7u; /* 3-bit counter: 7 -> 0 is a normal step */
trk.last_set_count = sc;
if (gap == 0) { stats.dup++; continue; }       /* duplicate read (or exactly 8 lost; see below) */
uint32_t n = gap;                              /* conversions since the last processed frame */
stats.lost += n - 1;

/* 2. Calibrate (from §4.6): offsets, gain ratio, quadrature skew */
float x = (raw_x - cal.ox) * cal.gx;
float z = (raw_z - cal.oz) * cal.gz;
x = x - z * cal.skew_sin;                      /* small-angle skew correction */
float mag2 = x * x + z * z;

/* 3. Electrical angle in 2^-16 turn units (Q16), harmonic LUT correction.
 *    atan2f() is in (-pi, pi]: convert through a signed integer, never float -> unsigned. */
int32_t  q   = (int32_t)lrintf(atan2f(x, z) * (65536.0f / (2.0f * (float)M_PI)));
uint16_t phi = (uint16_t)q;                    /* modulo 2^16: -1 -> 65535, as intended */
phi = (uint16_t)(phi - cal.harm_lut[phi >> 10]);   /* int16_t LUT, 64 entries */

/* 4. Type-II tracking loop (PLL) and unwrap.
 *    trk.theta: PLL angle, int64, Q24 electrical turns (2^-24 el turn).
 *    trk.omega: PLL velocity, float, Q24 el turns per sample.
 *    pos:       unwrapped *measured* angle, int64, Q16 = motion units (§2.3); no loop lag. */
int64_t th_p = trk.theta + (int64_t)lrintf(trk.omega * (float)n);  /* predict n samples ahead */
int64_t p16  = floor_div256(th_p);                                  /* prediction in Q16 */
int32_t err  = wrap16((uint16_t)(phi - (uint16_t)p16));             /* phase error, Q16, |err| < 32768 */
pos          = p16 + err;                      /* unwrap around the prediction: valid while |err| < 180° el */
trk.theta    = th_p + (int64_t)lrintf(K1 * 256.0f * (float)err);
trk.omega   += K2 * 256.0f * (float)err / (float)n;
/* mechanical rev/s = trk.omega / 2^24 / 24 / Ts */

/* 5. Lock supervision (60° el = 10923 in Q16) */
if ((abs(err) > 10923 for 3 frames) || mag2 outside (0.5..1.5 × cal.amp)^2) lose_lock();
```

* **Loop.** This is a real type-II (two-integrator) PLL: the error is taken
  against the loop's own predicted angle θ̂ + ω̂·n, θ̂ is corrected by K1·err
  and ω̂ by K2·err. The measured position `pos` is the raw angle unwrapped
  around that prediction, so it carries no loop lag; θ̂ and ω̂ feed only the
  unwrap, AUTO mode, `SPIN_START` and the predictor.
* **Gains** for f_n = 50 Hz, ζ = 0.8 and T_s = 322.6 µs: ω_n·T_s = 0.101,
  so **K1 = 2ζω_nT_s = 0.162** and **K2 = (ω_nT_s)² = 0.0103** (per-sample
  units, as in the code).
  * At constant speed both the phase error and the velocity error settle to
    zero.
  * Under an aggressive flick (about 300 rev/s² mechanical, which is
    45,000 rad/s² electrical) the phase error settles at α/ω_n² ≈ 26° el, below
    the 60° lock threshold. ω̂ lags the true speed by about
    (K1/K2 − ½)·T_s·α ≈ 4.9 ms × α ≈ 1.5 rev/s mechanical while the
    acceleration lasts, and the lag vanishes when the acceleration stops.
  * While |err| > 20° el, temporarily raise f_n to 100 Hz (K1 = 0.324,
    K2 = 0.041): the phase error drops to about 6.6° el and the velocity lag to
    about 0.7 rev/s.
* **Lost frames and coasting.** `n` is the SET_COUNT gap, so the prediction
  runs n samples ahead before the single correction. Up to 2 lost frames can
  be coasted at 30 rev/s. A gap of 8 or more aliases (gap = 0 also covers
  "exactly 8 lost"), so cross-check once per batch: the number of conversions
  since the previous batch is round((t_last − t_last,prev)/T_s) from the
  TIMER1 captures ([§4.4](#44-zero-cpu-acquisition-chain)). If that disagrees
  with the sum of the four gaps, use the timestamp count, mark the position
  `COASTING`, and count an error.
* **Error rate.** CRC failures, duplicates and lost conversions (n − 1) all
  count toward the [§15](#15-fault-handling) "> 1 % over 1 s → re-init" rule.
  A normal 7 → 0 SET_COUNT wrap is not an error.
* **Detent index.** The calibrated phase φ_well is where the rotor rests in a
  well ([§4.6](#46-calibration)). A `DETENT_STEP(±1)` event fires when pos
  crosses the crest (φ_well + 180° + n·360° el), with ±20° el of hysteresis.
  The same grid gives virtual detents in FREE mode.
* **Absolute angle.** SPEC has no index magnet, so the ring angle is relative.
  After a wake it is valid only modulo one detent (15°) unless continuity
  holds ([§4.8](#48-wake-on-rotation-wake-upsleep)). The virtual wheel and the
  LEDs do not need more, because the ring carries no markings. Optionally, the
  per-pole amplitude fingerprint ([§4.6](#46-calibration)) recovers the absolute
  pole index after one revolution (TVP).

### 4.6 Calibration

Store calibration in NVS (about 2 KB) and back it up in the QSPI factory area.

| Step | When | Method | Output |
|---|---|---|---|
| (a) Ellipse | First boot, factory, user request | Free spin at 3 rev/s or more for at least 3 s (about 220 electrical cycles). Decimate to about 2000 (x, z) points and fit with direct least squares (Fitzgibbon). | ox, oz, gx/gz, skew, nominal amplitude |
| (b) Rotation sign | Same session | Prompt "spin clockwise" on the OLED and record the sign. The bottom-mounted sensor mirrors the axes. | `cal.sign` |
| (c) Harmonic LUT | Same session | Per revolution, fit θ_true(t) = θ0 + ω0·t + ½α·t². The flywheel decelerates by well under 1 % per revolution, so it acts as a reference encoder. Bin residuals by electrical angle and average over all poles and at least 10 revolutions. | 64-entry common LUT |
| (d) Per-pole map | Same session | Per pole pair k (k = 0..23): amplitude A_k and phase residual | 24 × 16 LUT plus the amplitude fingerprint |
| (e) Detent phase | First rest in CLICK mode | Mean φ over 300 ms at rest in a well | φ_well |
| (f) Detent strength | Factory, and after a strength move | Pluck the ring in a well and measure the ringing frequency f_n. T1 = I·(2π·f_n)²/24, with I = 1.30·10⁻⁴ kg·m² (mechanical research; adjust for the built rotor). | Per-unit scale of the strength LUT ([§5.1](#51-coordinates-and-strength-lut)) |
| (g) Background re-fit | Every long coast (at least 5 revolutions above 2 rev/s) | Repeat (a) and (c). Accept only if the residual is below threshold. This is **mandatory**: X–Z sensitivity mismatch can drift up to ±15 % over temperature (verifier). | Updated a/c |
| (h) Self-test | Every calibration | Expect 24 electrical cycles per revolution and every per-pole amplitude within ±15 % of the median. Otherwise report "magnet k missing or reversed". A reversed magnet shows as a local phase reversal. | Fault code |

* **Fingerprint lock (optional, TVP).** Correlate the observed sequence of
  per-pole amplitudes with the stored 24-element fingerprint, over all 24
  circular shifts. When the correlation peak beats the runner-up by a set
  margin, set `ABS_VALID` and apply the per-pole LUT. Natural magnet scatter is
  about ±3–6 %. Until locked, only (a) and (c) apply, which gives about ±0.25°
  mechanical. That is plenty for 15° detents.
* Store separate offset vectors for CLICK and FREE carriage positions. The
  carriage's stray field (0.03 mT or less) makes this nearly a no-op, but it is
  cheap.

### 4.7 Motion events, velocity and spin-down prediction

**Events** (in `encoder_thread`):

| Event | Condition |
|---|---|
| `SPIN_START` | From rest: \|ω\| > 0.5 rev/s and more than 30° travelled within 200 ms |
| `REST` | \|ω\| < 0.02 rev/s for 300 ms (FREE). In CLICK: captured in a well (see below). |
| `SPIN_STOP` | `REST` after a `SPIN_START` |
| `TOUCH` | Deceleration residual more than 5σ above the model, i.e. a hand on the ring |
| `LOCK_LOST` | Tracker supervision tripped |

**Predictor** (adapted from sensing research FW-7):

1. Decimate ω to 100 Hz. Estimate α by a 0.2 s sliding linear regression. In
   CLICK mode the window spans at least one detent period, so the 24× detent
   ripple averages out.
2. Model α = −a·sgn(ω) − b·ω (Coulomb plus viscous). Fit it with recursive
   least squares (λ = 0.995), starting from per-regime priors stored in flash.
   Exclude `TOUCH` samples and samples within 100 ms of a carriage move.
3. Remaining time and angle:
   * t_rem = ln(1 + b·ω/a)/b
   * Δθ_rem = ω/b − (a/b²)·ln(1 + b·ω/a)
   * As b → 0 these become ω/a and ω²/(2a).
4. **CLICK capture.** The ring is captured in the first well after ω drops
   below ω_cap = √(4·T1/(24·I)). That is 0.73 rev/s at 16.5 mN·m, 0.56 rev/s at
   9.5 mN·m and 0.25 rev/s at 2 mN·m. The predicted landing detent is the
   first detent past the angle where ω = ω_cap. Learn ω_cap online as the
   lowest observed crest-crossing speed.
5. **Confidence.** σ_Δθ ≈ (ω²/(2a²))·σ_a, converted to segments. Publish the
   prediction and its confidence at 50 Hz.
6. **Result.** FREE: at `REST`, take one 32×-averaged reading. CLICK: decide as
   soon as the velocity reverses inside a well with kinetic energy below the
   barrier E_b = 2·T1/24. Do not wait for the ringing to stop.
7. **Fairness rule.** Use predictions **only for effects** (suspense, near-miss
   sounds). They must never change the outcome. Any brake engagement in game
   mode happens at a fixed speed threshold that does not depend on the
   prediction ([§5.5](#55-modes)).

**Priors** (refined online and stored per regime):

| Regime | a (Coulomb) | Basis |
|---|---|---|
| FREE (608 bearing, light oil, 2.5–3 N preload) | 1.2–3.1 rad/s² | 0.15–0.4 mN·m (SKF model ±2.7×, mechanical research) / I. From 10 rev/s that gives about 20–50 s, partly **below** the ≥ 45 s mechanical acceptance (architecture.md R3 and D3, bringup.md B-13): SPEC's preload is expected to miss it on some units. Replace the prior with the unit's measured spin-down from test 20 ([§16](#16-bring-up-and-manufacturing-tests)). |
| CLICK, shoe lifted | Same as FREE plus a little | 316L ring, so eddy drag is small |
| CLICK with shoe engaged | about 10–15 rad/s² | Shoe about 1.5 mN·m (detent verifier). From 5 rev/s: about 2.5 s, about 6 revolutions. TVP. |

### 4.8 Wake-on-rotation (Wake-up&Sleep)

The TMAG's Wake-up&Sleep (W&S) mode is the rotation wake source. The register
values come from sensing research FW-4 as corrected by the verifier.

**Arming** happens on entering DESK_IDLE or SLEEP, and on `REST` that lasts at
least 2 s while the device is idle:

1. Take one 32×-averaged reading of X and Z, i.e. one conversion of about
   2.5 ms. Call the results Bx0 and Bz0.
2. Per axis, compute the threshold code T = ceil((|B0| + Δ)/1.04 mT). The LSB
   is 133/128 mT for the A2. **Use Δ = 2 LSB** (2.08 mT, about 14σ of the 1×
   noise).
3. Write 0 (axis disabled) for an axis whose T·LSB would exceed 0.9 of that
   axis's calibrated amplitude. With Δ = 0.15·A at least one axis is always
   armed. If neither passes (which happens only at very low amplitude), arm
   the axis with the larger headroom anyway.
4. Write the wake configuration, with DEVICE_CONFIG_2 last:

   | Register (address) | Value | Meaning |
   |---|---|---|
   | CONV_STATUS (0x18) | 0x10 | Clear POR (W1C) so that a TMAG reset while armed shows as POR = 1 at wake |
   | DEVICE_CONFIG_1 (0x00) | 0x20 | CRC off, NdFeB tempco, 1× averaging, standard reads |
   | SENSOR_CONFIG_1 (0x02) | 0x52 (ARMED) or 0x57 (DEEP) | ZX channels; SLEEPTIME 10 ms or 100 ms. Use 0x58 (500 ms) on low battery. |
   | SENSOR_CONFIG_2 (0x03) | 0x00 | MAG_THR_DIR = 0: interrupt when the field leaves the ±T band |
   | X_THR_CONFIG (0x04) / Y_THR_CONFIG (0x05) / Z_THR_CONFIG (0x06) | T_x / 0 / T_z | 0 means no comparison on that axis |
   | INT_CONFIG_1 (0x08) | 0x44 | THRSLD_INT = 1, latched, INT pin |
   | DEVICE_CONFIG_2 (0x01) | 0x23 | THR_HYST = 001, OPERATING_MODE = 11 (W&S) |

5. On the nRF: disable the GPIOTE IN channel, the PPI channels, TIMER1,
   TIMER2 and TWIM0 (ENABLE = 0, pinctrl sleep state). Then set TMAG_INT_N to
   SENSE low through the Zephyr GPIO interrupt (the pin is in
   `sense-edge-mask`).

**Wake sensitivity.** I simulated this rule for SPEC's amplitudes: it scans all
rest phases in 0.5° steps, both directions, with the threshold quantised.

| Amplitude (Bt/Bz) | Δ | Worst case | Median | Share needing > 40° el |
|---|---|---|---|---|
| 13.4/15.9 mT (nominal) | 2 LSB | 104° el = **4.3° mech** | 0.69° mech | 34 % |
| 10.1/11.8 mT (large gap) | 2 LSB | 122° el = 5.1° mech | 0.94° mech | 36 % |
| 17.1/20.6 mT (small gap) | 2 LSB | 97° el = 4.0° mech | 0.52° mech | 29 % |
| 10.1/11.8 mT | 3 LSB | **never triggers in one direction** | | |

So use Δ = 2 LSB. Wake needs at most about ⅓ detent of rotation.

**Wake sequence** (TMAG_INT_N SENSE, latched low; the TMAG has left W&S and
sits in standby at 0.45 mA):

1. Re-enable TWIM0 in blocking mode. Read X, Y and Z (0x12–0x17) and
   CONV_STATUS (0x18) with a standard read. The read clears the latched INT and
   gives φ_first.
   * If CONV_STATUS.POR (bit 4) = 1, the TMAG has reset while armed (for
     example a +3V3 dip). Log E_ENC_POR, discard φ_first, mark the position
     relative, and run the full init of [§4.2](#42-tmag5273-tracking-configuration),
     which clears POR. Arming (step 4 above) is always preceded by the same
     POR clear, so POR = 0 is the expected value here.
2. Write the tracking configuration ([§4.2](#42-tmag5273-tracking-configuration),
   including the POR clear and read-back), then arm GPIOTE, PPI and DMA. The first streamed sample arrives about
   0.4 ms later. Total wake-to-tracking time is about 1 ms.
3. **Continuity.** Take the direction from the first two streamed samples, then
   unwrap from the stored φ_rest *in that direction*: Δ = (φ_first − φ_rest)
   mod 360° el, or its negative. This is valid while the ring moved less than
   one electrical period (15° mech) before the first sample.
   * In ARMED (10 ms): at most about 4.3° to trigger plus 3.6° per 10 ms at
     1 rev/s, so continuity holds for normal turns, and HID loses no clicks.
   * In DEEP (100 ms): a fast flick can travel more than 15°, so mark the
     position "relative" (clear `ABS_VALID`). The LEDs were off, so nothing
     visible jumps.

**Re-arm rules and watchdog**

* **Every** exit from W&S, from any wake source, must end in either tracking or
  re-arm. After a threshold INT the TMAG stays in standby drawing **0.45 mA**
  until it is reconfigured, which would empty a 1000 mAh cell in about 3
  months. Run a software watchdog: if tracking is not configured within 50 ms
  of a wake, force a re-arm.
* **False wake:** less than ¼ detent of motion within 300 ms of the wake.
  Re-measure and re-arm, and count it. If there are more than 6 per hour,
  raise Δ to 3 LSB **only if** the amplitude is at least 13 mT, otherwise move
  to the next longer interval. Log it. External magnets such as MagSafe rings
  and magnetic stands are the usual cause.
* **I2C access during W&S sleep is NACKed** and wakes the part, which also
  pulses INT. Any routine that touches the TMAG while it is armed (IMU or button
  wake, health check) must mask the INT handler for 1 ms, retry after at least
  50 µs on NACK, and then **re-arm with freshly measured thresholds**.
* Re-arm every 4 h anyway (self-heal), and after a die-temperature change of
  more than 10 °C. The magnet tempco of −0.12 %/°C gives 0.2 mT per 10 °C,
  which is small against Δ = 2 mT.

**Interval policy**

| Tier | Interval | TMAG current | Used in |
|---|---|---|---|
| TRACKING | Continuous, 3.1 kSPS | 2.3 mA + 0.31 mA pull-ups + about 0.5 mA nRF | ACTIVE, and 2 s after motion stops |
| ARMED | 10 ms (0x52) | about 17–20 µA (modelled; TVP) | DIM, DESK_IDLE, and 5 min after use |
| DEEP | 100 ms (0x57) | about 3 µA | SLEEP |
| DEEP-LOWBAT | 500 ms (0x58) | about 1.5 µA | SLEEP below 3.60 V (the low-battery warning level, [§12.4](#124-battery-measurement-and-low-battery-policy)) |

### 4.9 Outputs

* `motion_state`: position in 1/(24·65536) turn, ω in rev/s, detent index,
  flags.
* HID units: 0.1° (3600 per revolution) via `pos × 3600 / (24·65536)` with
  remainder carry, and the sign flipped for clockwise-positive.
* Events: `motion_evt` ([§2.3](#23-inter-module-data)) and the prediction at
  50 Hz.
* Wake reason: rotation, IMU, button, USB, charger, BLE.
* Renderers extrapolate by their own latency: θ_draw = θ + ω·t_lat.

---

## 5. Detent control

### 5.1 Coordinates and strength LUT

* **Carriage coordinate.** x is the offset in mm, measured radially inward from
  the CLICK-MAX position: x = 0 is full click at r = 29.0, and x ≥ 7.5 is FREE
  (park, r ≤ 21.5).
* **Actuator.** A micro PM linear stepper (VIC-TECH VSM08102 class, or the
  10 mm sibling; SPEC "micro actuator"). It has 20 full steps per revolution
  on an M2×0.4 lead screw, so 1 full step = **0.02 mm**, and the stroke is 375
  full steps. The self-locking screw gives zero hold power.
* **Strength LUT.** Peak detent torque vs in-plane offset at a 1.0 mm gap,
  verified by independent re-simulation
  ([detent research](https://www.micro-steppermotors.com/sale-28526335-vsm08102-8mm-4-pins-fpc-small-linear-stepper-motor-with-slider-m2-lead-screw.html)
  for the actuator; the magnetics come from the project's magpylib model). The
  values are for R = 30 mm; SPEC's R = 29 mm differs by only a few percent
  (TVP). Calibration step (f) scales them per unit.

  | x (mm) | 0 | 0.5 | 1.0 | 1.5 | 2.0 | 2.5 | 3.0 | 3.5 | 4.0 | 5.0 | 6.0 | 7.0 | 7.5 |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|---|
  | T1 (mN·m) | 16.5 | 15.4 | 12.8 | 9.5 | 6.2 | 3.7 | 2.0 | 1.1 | 0.55 | 0.14 | 0.031 | 0.006 | 0.0027 |

* **User strength s (1–100 %)** maps logarithmically to torque:
  T = T_min·(T_max/T_min)^((s−1)/99), with T_min = 1.0 mN·m and
  T_max = 16.5·k_unit mN·m. Interpolate x from the LUT in ln(T), round to whole
  full steps, and **end every move on a full step**. s = 0 means FREE.
  * The **default is s = 100 %** (x = 0, T ≈ 16.5 mN·m, 0.47 N at the 35 mm
    rim). That is where the optional friction shoe engages (design intent
    x ≤ 0.5 mm, [§5.6](#56-friction-shoe-interplay)), so the default click is
    damped. It follows architecture.md §6.2 ("default to the strongest
    setting") and the detent verifier's correction.
  * An EC11-like s = 85 % (T ≈ 11 mN·m at x ≈ 1.25 mm, 62 steps) becomes the
    default only if the factory-measured `shoe_x_max` is at least 1.3 mm.
    Otherwise 85 % stays a user choice and is undamped: about 10 s of rocking
    after a spin with bearing friction alone (§5.6).
* **Physics** at strength T1, with I = 1.3·10⁻⁴ kg·m² and N = 24:
  * In-well natural frequency f_n = √(N·T1/I)/2π: 8.8 Hz at 16.5 mN·m,
    6.7 Hz at 9.5 mN·m, 3.1 Hz at 2 mN·m.
  * Capture speed: see [§4.7](#47-motion-events-velocity-and-spin-down-prediction).

### 5.2 State machine

```
            boot / power loss with no valid stored position
                              │
                              ▼
   ┌──────────┐  fail ×3  ┌─────────┐ ok ┌──────────────────────────────────────┐
   │  FAULT   │◀──────────│ HOMING  │───▶│ IDLE(x)  drivers asleep, 0 µA hold     │
   │ (asleep, │           └─────────┘    └──────────────────────────────────────┘
   │ features │                ▲  lost steps    │ new target (debounced, rate-limited)
   │  off)    │                │  at park       ▼
   └──────────┘                │          ┌──────────────┐ arrive   ┌─────────┐
                               └──────────│ MOVING(x→x') │─────────▶│ SETTLE  │─▶ IDLE(x')
                                          └──────────────┘          │ 20 ms   │
                                            abort: low batt,         └─────────┘
                                            new target (re-plan)
```

| State | Entry actions | Exit condition |
|---|---|---|
| HOMING | nSLEEP high; wait 1 ms (tWAKE ≤ 30 µs); energise the stored phase for 10 ms at run current; run the homing procedure of [§5.4](#54-homing-with-the-drv5032) (approach at **run current**, final stall at 50 % current and 80 PPS) | The **stall at the park stop** is the reference: after the stall, HOME must read asserted; back off 4 steps; set x = x_park. Otherwise retry (×3), then FAULT. |
| IDLE(x) | Brake, then sleep: IN1 = IN2 = 1 on U40 and U41 for ≥ 3 ms, then all IN low and nSLEEP low. **Immediately** write x, the motor phase and `valid = 1` to `state/carriage` in NVS (no debounce). | New target |
| MOVING | **First** clear `state/carriage.valid` in NVS and wait for the write to complete (a few ms; TVP with BLE active). Then wake the driver; energise the current phase for 10 ms; run the profile ([§5.3](#53-stepping-profile)); set the `ACTUATOR_MOVING` flag. A move to FREE ends with the re-reference stall ([§5.4](#54-homing-with-the-drv5032)). | Last full step reached |
| SETTLE | Hold current for 20 ms | → IDLE |
| FAULT | Brake ≥ 3 ms, then driver asleep. Report on status/UI. Detent features stay wherever the carriage is. | User "re-home", or reboot |

* **Brake before sleep on every stop path.** IDLE entry, FAULT, an abort
  (low battery, POF, per-move watchdog) and any other path that ends a move
  MUST set IN1 = IN2 = 1 on U40/U41 for ≥ 3 ms before IN = 00 and nSLEEP low.
  Coasting the coils from a hold dumps their energy through the DRV8837 body
  diodes into VSYS; on USB after charge termination nothing but the VSYS
  ceramics absorbs it, against the BQ25180's 5.5 V SYS absolute maximum
  (hardware/sim, MD-1). A reset mid-move cannot brake; the 25 V VSYS
  capacitors and C74 keep that coast under 5.5 V (SPEC §5.1, §5.6; MD-5).
* **Boot:** skip homing only if `state/carriage.valid = 1`. Because `valid` is
  cleared before the first step of every move and set again only after
  SETTLE, a watchdog reset, HardFault, brown-out or battery removal during a
  move (or before its post-SETTLE write lands) always leaves `valid = 0`, and
  the next boot homes. A reset while IDLE keeps a correct record, so homing is
  rare.
  * NVS wear is negligible: two records of about 16 B (with the ATE) per move
    at 200 moves/day is about 6.4 KB/day into the 32 KB settings partition,
    i.e. one erase per 4 KB sector every 5 days or so, against 10,000 cycles.
  * Ship-mode entry parks first ([§12](#12-power-management)); the park move's
    SETTLE writes the valid record.
  * Homing takes about 2 s from the click end, up to about 2.7 s from inside
    the park zone, and about 3 s before the factory has learned the HOME edges
    ([§5.4](#54-homing-with-the-drv5032)).
* **Command coalescing:** only the latest target is kept. A new target during
  MOVING re-plans from the current step, with deceleration if the direction
  reverses.

### 5.3 Stepping profile

* **Drive.** PWM0, 4 channels, 16 MHz clock, COUNTERTOP = 640 → **25 kHz**,
  individual decoder mode. Coil A = channels 0 and 1 (DRV8837 #1), coil B =
  channels 2 and 3.
* **Microstepping.** 8 µsteps per full step (32 per electrical cycle); coil A
  ∝ cos θ and coil B ∝ sin θ in 11.25° increments. Keep this sine drive:
  firmware MUST never use full-current two-phase full steps on USB, which
  store about 4× the coil energy of the sine hold (hardware/sim, MD-1).
* **Slow decay.** DRV8837 IN1/IN2: 1,0 = forward; 1,1 = brake (both low-side
  on, slow decay); 0,0 = coast. For positive current hold IN1 high and PWM IN2
  at a duty of (1 − |d|); for negative current, swap. Encode the polarity with
  the PWM sequence value's polarity bit.
* **Amplitude** (voltage mode, scaled by measured VSYS and compensated for
  coil temperature, hardware/sim, MD-3):
  d_peak = I_target × (20 Ω × (1 + 0.00393 × (T − 25 °C)) + 0.33 Ω) / VSYS,
  with T the nRF die temperature (20.33 Ω at 25 °C, including RDS(on)).
  Clamp d ≤ 1; at T = 60 °C the 160 mA run current needs VSYS ≥ 3.69 V
  (calculated from the formula).
  * Run: I_target = 160 mA, giving d = 0.77 at 4.2 V, 0.88 at 3.7 V and 0.92 at
    3.55 V (25 °C).
  * Homing: run current (160 mA) for every travel phase, because the load
    can oppose the carriage in either direction (magnetic up to 0.29 N, and
    0.8–1.15 N worst case with guide friction and the anti-lash spring,
    architecture.md §6.2, against the VSM08102's 0.78 N minimum thrust; this
    shortfall is still open, [§18](#18-open-items-and-to-verify-list)
    item 10). 80 mA (50 %) only for the final stall into the park stop, where
    the magnetic force is about 0 and the anti-lash spring pushes toward PARK.
  * Below a measured idle VSYS of 3.55 V the coil no longer gets its rated
    current under load, so only park moves are allowed ([§5.8](#58-limits)).
* **Sequences.** Use `nrfx_pwm_complex_playback()` with two ping-pong
  sequences, each holding 8 µsteps (one full step) × 4 channels (64 B).
  REFRESH sets periods per µstep, i.e. speed. The SEQEND IRQ refills the idle
  sequence with the next step and that step's REFRESH, via
  `nrfx_pwm_sequence_update()`. Achievable speeds are 25000/(8·(REFRESH+1))
  PPS:

  | REFRESH + 1 | 3 | 4 | 5 | 6 | 7 | 8 | 10 | 39 |
  |---|---|---|---|---|---|---|---|---|
  | Full steps/s (PPS) | 1042 | 781 | 625 | 521 | 446 | 390 | 313 | 80 |

* **Speed plan** (verifier-corrected thrust budget: the magnetic load opposes
  retraction by up to 0.29 N in x = 0.75–2.25 mm, and thrust is rated only at
  500 PPS):

  | Zone | Speed | Why |
  |---|---|---|
  | Breakaway (first 4 steps) | 313 PPS | Start-up torque |
  | 0 ≤ x ≤ 4 mm (loaded) | **446 PPS max** | Rated thrust (≥ 80 gf) is specified only at 500 PPS |
  | x > 4 mm | Ramp 521 → 781 PPS (1042 only after a thrust test, TVP) | Magnetic force is about 0 there |
  | Decel | Mirror of the ramp, last 4 steps at 313 PPS | |
  | Homing travel (back-off, approach, run-in) | 313 PPS back-off; approach and run-in 313 → 446 PPS; run current | Thrust margin in the loaded zone ([§5.4](#54-homing-with-the-drv5032)) |
  | Final stall (homing, and the tail of every move to FREE) | 80 PPS, 50 % current, about 60–140 steps | Gentle stall into the park stop; at x ≥ 6.7 mm the detent torque is ≤ 0.01 mN·m, so the slow tail is not felt |

  A full 7.5 mm stroke takes **about 0.7–0.9 s** (verifier: plan 0.6–0.9 s),
  plus the 0.75 s re-reference tail when the target is FREE ([§5.4](#54-homing-with-the-drv5032));
  a strength trim of 0.5 mm takes about 60 ms. Energy is 0.035–0.055 mAh per
  full stroke, and battery peak current is 0.36–0.42 A.

### 5.4 Homing with the DRV5032

The DRV5032FA is always powered (SPEC) on the **top** side directly above park.
I simulated the detent magnet's Bz at the sensor die; the die sits about
2.4–2.8 mm above the magnet's top face (board 1.6 mm + 0.5 mm carriage plate +
package).

| Die height above magnet | x = park (0 mm away) | 3 mm away | 4 mm | 5 mm | 6 mm | **7.5 mm (click)** |
|---|---|---|---|---|---|---|
| 2.4 mm | 70.9 mT | 12.9 | 3.4 | −0.2 | −1.3 | **−1.40** |
| 2.6 mm | 60.9 | 12.9 | 4.0 | 0.4 | −0.9 | **−1.22** |
| 2.8 mm | 52.6 | 12.7 | 4.5 | 0.8 | −0.6 | **−1.03** |
| 3.5 mm (research's recommendation) | 32.9 | 11.2 | 5.2 | 2.0 | 0.4 | −0.47 |

The DRV5032FA is omnipolar, with BOP 1.5/3/4.8 mT, BRP 0.5/1.5/3 mT and
BHYS 0.8/1.5/3 mT (min/typ/max). It samples at 20 Hz with a sampling period
tS of 27/50/75 ms, so a field change is seen 0–75 ms late
([DRV5032 DS SLVSDC7H §6.5, §6.6](https://www.ti.com/lit/ds/symlink/drv5032.pdf)).
The 48-magnet track adds about 0.01 mT. Below, s is the carriage distance from
the **park stop** in full steps (s = 0 at the stop, s = 375 at click;
x = (375 − s) × 0.02 mm). This leads to the following:

* At park the field is more than 50 mT, so HOME is solidly asserted.
* **Assert edge** (moving toward park): HOME asserts about 3.8–4.6 mm from the
  stop, i.e. s_ast ≈ 190–230 steps. It does **not** mark the stop.
* **Release edge** (moving toward click): the field falls below BRP about
  4.1–5.0 mm from the stop, s_rel ≈ 200–250 steps. The hysteresis puts the
  release 11–42 steps further out than the assert (BHYS 0.8–3 mT over a local
  gradient of about 3.6 mT/mm).
* **Detection lag**: 0–75 ms in the direction of travel, which is 0–6 steps at
  80 PPS, 0–24 at 313 PPS and 0–34 at 446 PPS. Both edges lie at
  x ≈ 2.5–3.7 mm, inside the ≤ 446 PPS loaded zone of
  [§5.3](#53-stepping-profile).
* At the click end |Bz| reaches 1.0–1.4 mT. That is below BOP min (1.5 mT), but
  only by 0.1–0.5 mT, so a unit with a low die or a strong magnet may assert
  HOME at full click (SPEC §5.6 notes it; [§18](#18-open-items-and-to-verify-list) item 2).
  Factory test 19 rejects or reworks any unit that asserts HOME at x = 0, so
  firmware may assume that **HOME asserted means the park zone (s ≤ s_rel)**.

**Factory learning (test 19).** After a homing stall, sweep toward click at
80 PPS and record the step where HOME releases; sweep back toward park at
80 PPS and record where it asserts. Do 5 sweeps each way and store the means
s_rel,L and s_ast,L and the spread in `cal/home_edges`. Until they are learned,
use the simulated ranges above.

**Homing procedure** (unknown position: first boot, `valid = 0`, user
re-home, lost-step recovery, FAULT retry):

| Phase | Drive | Ends when | Limit |
|---|---|---|---|
| H0 wake | nSLEEP high, 1 ms; energise the stored phase 10 ms at run current | | |
| H1 back-off (only if HOME reads asserted) | Toward click, **run current**, 313 PPS | HOME releases (now just outside the park zone) | s_rel,L + 24 + 20 steps (default 295). Still asserted → failed attempt |
| H2 approach | Toward park, **run current**, 4 steps at 313 PPS then 446 PPS | HOME released → asserted edge | 375 + 40 = 415 steps. No edge → failed attempt (likely a stall in the loaded zone) |
| H3 run-in | Continue toward park, run current, 446 PPS, for n3 = s_ast,L − 34 − 10 − 20 steps | n3 steps done; the carriage is now 20–80 steps from the stop (20–94 with the unlearned default, n3 = 136) | |
| H4 final stall | Decelerate to **80 PPS, 50 % current**; step the remaining maximum + 20 steps of overdrive (100 learned, 114 default) | The carriage reaches the stop after 20–94 steps and slips for at least 20 more | |
| H5 confirm | Read HOME | HOME asserted → back off 4 steps at run current, x = x_park = stop − 4 steps (7.42 mm nominal, T1 ≈ 3 µN·m), → SETTLE | HOME not asserted → failed attempt |

* **x_park and SPEC.** SPEC §1 defines FREE as x ≥ 7.5 mm. With the park stop
  exactly at 7.5 mm, the 4-step back-off leaves x = 7.42 mm and
  T1 ≈ 3 µN·m, which is the residual the 7.5 mm stroke was sized for. Ask
  the mechanical design for the park stop at x ≥ 7.58 mm (r ≤ 21.42 mm) so
  that x_park itself is ≥ 7.5 mm; `stroke-steps` in [§3.1](#31-board-dts-draft)
  then becomes the measured stop-to-stop count (TVP).
* A failed attempt retries from H0 with every travel phase at 313 PPS, where
  the PM stepper has more thrust; after 3 failures go to FAULT (E_DET_HOME).
* **Duration**: about 2 s from the click end (H2 ≤ 0.5 s, H3 about 0.3 s,
  H4 1.25 s), up to about 2.7 s from inside the park zone (H1 adds up to
  0.9 s), and about 3 s with unlearned edges.
* **Every move to FREE re-references.** Run the normal profile to s = 40
  (x = 6.7 mm), then 80 PPS at 50 % current for 40 + 20 steps (0.75 s), confirm
  HOME asserted, back off 4 steps and set x = x_park. Detent torque is already
  ≤ 0.01 mN·m at s = 40, so the slow tail is not felt. If HOME is not asserted
  there, run the full homing procedure. This park stall plus HOME confirmation
  is the **primary** lost-step check (and it matches architecture.md §6.2:
  "HOME must read asserted after every park stall, including the one that
  ends every return to free mode").

Firmware rules that follow:

1. The **mechanical stall at the park stop** is the only position reference.
   HOME only confirms it (asserted after the stall) and locates the carriage
   coarsely during homing. Never set x from a HOME edge.
2. **Secondary lost-step check (edge windows).** When a move crosses an edge,
   compare the step where the edge is seen with the learned value, allowing
   for the one-sided detection lag at the speed v in use (lag = 0.075 s × v,
   m = max(10 steps, learned spread), TVP for temperature drift of BOP/BRP):
   * moving toward park, assert seen at s ∈ [s_ast,L − lag − m, s_ast,L + 6 + m];
   * moving toward click, release seen at s ∈ [s_rel,L − 6 − m, s_rel,L + lag + m].

   At 446 PPS that is a 60-step window; at 80 PPS, 32 steps. Outside the
   window → E_DET_STEPS: the next move to FREE re-references anyway; re-home
   at once (when the ring is at rest) if the error exceeds 40 steps or two
   moves in a row fail. Strength trims near the click end (x < 2 mm) cross no
   edge, so a lost step there shows only as a few percent of strength until
   the next return to FREE or a user re-home.
3. Homing failures (H1, H2 or H5 above): retry up to 3 times, then FAULT.
4. Ignore HOME at x < 2 mm in normal moves: there it carries no information,
   given the BOP margin.

There is no current sensing, so stall detection is open-loop. A PM stepper
slips against the stop at 50 % current, and the final error is ±1–2 full
steps (±0.02–0.04 mm, about ±2–4 % torque). *TVP:* confirm on the prototype
that repeated 50 % stalls do not wear or jam the lead-screw nut, and that the
run-current approach clears the loaded zone at 446 PPS at VSYS 3.4 V.

### 5.5 Modes

| Mode | Behaviour |
|---|---|
| FREE | Go to the park stop with the re-reference tail, end at x_park ≈ 7.42 mm ([§5.4](#54-homing-with-the-drv5032)) |
| CLICK(s) | Go to x(s) from the LUT |
| AUTO | Like Logitech SmartShift. In CLICK, a flick (ω rising past 2 rev/s with α > 20 rev/s²) moves to FREE; returns to CLICK when \|ω\| < 0.5 rev/s or on `TOUCH`. Rate-limited to one switch per second. The actuator takes 0.7–0.9 s (the 0.75 s re-reference tail of a move to FREE is not felt), so switching happens after the flick, which is fine. |
| BRAKE (game) | FREE while \|ω\| > ω_brake (default 1.5 rev/s); below that, move to CLICK-MAX with the shoe engaged, giving a short prize-wheel ending. ω_brake is fixed per game setting and never depends on the prediction (fairness). |

### 5.6 Friction shoe interplay

The detent research (verifier-corrected) proposes a removable felt or UHMW shoe
on the carriage that engages only at small offsets: about 1.5 mN·m, so the
ringing settles in about 8–12 cycles. SPEC does not fix it, and bearing
friction is the dominant unknown. Firmware therefore treats the shoe as
optional and **learned**:

* **Engagement offset** `shoe_x_max` is a factory or setting value (design
  intent ≤ 0.5 mm, which covers the s = 100 % default; ≥ 1.3 mm would also
  cover the EC11-like 85 % setting, [§5.1](#51-coordinates-and-strength-lut)). Firmware
  confirms it by measuring the Coulomb term a during short spin-downs at a few
  offsets. A step of about 8–12 rad/s² marks the shoe.
* The **predictor** keeps separate priors for shoe-on and shoe-off
  ([§4.7](#47-motion-events-velocity-and-spin-down-prediction)).
* **Damped vs undamped strength.** Any strength with x > `shoe_x_max` is
  undamped, and so is every strength on a unit without a shoe. Without the
  shoe, ringing at 150 µN·m bearing friction loses about 0.09° per cycle, so it
  lasts about 85 cycles (about 10 s) at 8.8 Hz. That is why the default is
  s = 100 % (x = 0). For undamped settings:
  * the UI offers a "damped" preset (snaps to x ≤ `shoe_x_max`);
  * the result logic always decides at first capture ([§4.7](#47-motion-events-velocity-and-spin-down-prediction)
    step 6), never at full stillness.
* **Wear tracking.** Log a (shoe on) per session. If it falls more than 30 %
  below the factory value, show "shoe worn".
* **No engaging at speed** unless BRAKE asks for it: firmware does not move
  into the shoe window while |ω| > 3 rev/s (wear, sudden braking).

### 5.7 Encoder interplay during moves ("blanking")

The stepper sits 180° from the TMAG and its coil field there is about 1 µT.
Magnetic blanking is therefore **not** needed, and the tracker must never stop,
because the ring may be moving. "Blanking" here means suppressing the
*derived* events that a move causes:

* While `ACTUATOR_MOVING` is set, and for 150 ms after it clears:
  * Suppress `DETENT_STEP` HID clicks and piezo ticks caused by the engagement
    snap, i.e. motion under one detent with |ω| < 0.3 rev/s. Real turns above
    that still pass.
  * Suppress `SPIN_START` from rest.
  * Freeze calibration updates.
  * Exclude the samples from the predictor fit.
* If the move causes CRC or lock errors (ground bounce from the 25 kHz
  switching), the tracker coasts as usual. Log the count; it should be 0.

### 5.8 Limits

| Limit | Value | Reason |
|---|---|---|
| Minimum VSYS for non-park moves | 3.55 V (measured idle) | The coil must get its rated 165 mA at 3.3 V under the stroke load (cell, BATFET, link and rDS(on) sag); that point is 3.53 V at 25 °C (hardware/sim, MD-2) |
| Minimum VSYS for a park move | 3.30 V | Parking is needed before ship mode |
| Rate | At most 20 full strokes per minute sustained; bursts of 5 | Motor heating (about 1 J per stroke) and battery |
| LED cap while moving | 100 mA average; instantaneous budget less 0.23 A ([§6.3](#63-power-limiter)) | Keeps the coincident peak below about 0.6 A and the cell sag below 0.3 V |
| OLED_VCC_EN during a move | Never toggled while VBAT < 3.6 V; enable the OLED before a park move | The OLED turn-on surge (≈ 0.3 A for ~2 ms, 0.4 A peak) on top of a stroke eats the BQ25180 BAT-pin margin to BUVLO at a low cell (hardware/sim, NEW-2) |
| Stop | Brake ≥ 3 ms, then sleep ([§5.2](#52-state-machine)) | VSYS overshoot on USB (hardware/sim, MD-1) |
| Watchdog per move | Expected steps / PPS + 0.5 s | A hung profile goes to FAULT and the driver sleeps |

---

## 6. LED renderer

### 6.1 Hardware facts used

* 48× WS2812C-2020-V6 (D101–D148), 5 mA per channel. The WS2812B-2020-V6
  (12 mA per channel) is pin-compatible only: firmware supports it as a
  factory-set variant, and with it the instantaneous cap of
  [§6.3](#63-power-limiter) (≈ 1.0 A at full battery) is mandatory
  (hardware/sim, PI-3). Until the variant is set, **firmware assumes 12 mA**,
  which is the safe direction. Both variants must be V6 parts; the data-line
  margins below assume the V6 input threshold (SPEC §5.4).
* LED j (0-based; D(101+j) in SPEC and the `leds` sheet) sits at θ = 7.5°·j,
  CCW from the USB-C direction. That gives 2 LEDs per detent.
* Data path: P0.06 → R40 220 Ω (next to the module pin) → LED_DIN_R (R41
  100 kΩ pull-down) → R43 0 Ω → D101 DIN, at 3.3 V logic. A DNP SN74LV1T34
  level shifter (U43, powered from VLED, with C43) replaces R43 only if the
  bench test at VSYS 4.6 V shows bit errors. Firmware keeps the DIN rules of
  [§6.4](#64-rail-sequencing) either way; U43 (Ioff) only makes a violation
  harmless.
* **Data margin.** The DC high-level margin at D101 is +427 mV realistic but
  only about +41 mV on the nRF datasheet bound at VSYS 4.59 V (SYS_REG
  4.5 V + 2 %), and about +116 mV with SYS_REG 4.4 V; the tightest pulse
  width is T1H, with 15 ns of margin (SPEC §5.4; hardware/sim, LED-DATA-2,
  LDO-2). Three firmware rules hold that margin; they are requirements, not
  options:
  * P0.06 MUST use `nordic,drive-mode = NRF_DRIVE_H0H1` in its default
    pinctrl state ([§3.1](#31-board-dts-draft)): standard drive does not
    guarantee the WS2812C T1H/T0L/T1L windows (hardware/sim, LED-DATA-V1).
  * Every LED frame MUST be clocked from the HFXO: request it and wait until
    it runs before the frame, and release it afterwards. On HFINT (±8 %) the
    bit timing breaks T1H/T0L (hardware/sim, LED-DATA-V2). The nrfx I2S
    driver with `clock-source = "PCLK32M_HFXO"` requests the HFXO itself and
    starts the transfer once it runs (check on your Zephyr version);
    otherwise `led_thread` does it through the HF clock onoff manager.
  * BQ25180 SYS_REG_CTRL MUST be 001 (4.4 V); 010 (4.5 V) is the only other
    allowed value, never higher or pass-through while the LEDs may run
    ([§13.1](#131-register-init-table); hardware/sim, LED-DATA-V3). VLED =
    VSYS sets the LED's VIH, so a higher SYS eats the margin above.
* Timing: T0H 312.5 ns, T0L 937.5 ns, T1H/T1L 625 ns (all inside the V6
  windows with H0H1 drive and the HFXO), with reset at least 280 µs
  ([WS2812C-2020-V6 DS](https://datasheet.lcsc.com/datasheet/pdf/8c7f104c99e52e4adb687ae84e594e95.pdf),
  [Zephyr ws2812-i2s binding](https://docs.zephyrproject.org/latest/build/dts/api/bindings/led_strip/worldsemi,ws2812-i2s.html)).
* Frame: (48 × 3 + 1 + 30) words × 4 B = 700 B; line time 1.75 ms. The stock
  driver adds 300 µs of extra wait and blocks, so the **frame period is about
  2.05 ms, at most about 480 fps**. The `led_thread` blocks for that time,
  which is why it runs at low priority.
* *TVP:* the I2S runs with only SDOUT routed. If the driver insists on SCK and
  LRCK pins, no second fast spare pin exists (only P0.04). Fall back to
  `worldsemi,ws2812-spi` on SPIM2 (4 MHz, 0x70/0x40 frames, MOSI only on
  P0.06, still H0H1 and HFXO-clocked) with no hardware change, as long as the
  OLED stays on SPIM3.

### 6.2 Frame pipeline

```
effect(mode, motion snapshot θ + ω·t_lat) → linear RGB float [0..1] per LED
  → × user brightness × mode ceiling
  → gamma 2.2 LUT (12-bit internal) + temporal dithering to 8 bit (only at ≥ 200 fps)
  → power limiter (scales codes)
  → GRB pack → led_strip_update_rgb()
```

* **Frame rate:**
  * 30 fps for idle effects;
  * 120 fps by default;
  * 240 fps while |ω| > 3 rev/s. At 10 rev/s the wheel moves 480 px/s, so
    above about 5 rev/s draw motion-blurred, anti-aliased arcs rather than
    stepping pixels;
  * the rail goes off after 2 s of all-black.
* **Latency compensation:** t_lat ≈ render + DMA ≈ 3 ms.
* **Virtual prize wheel (game).** Segment i has weight w_i, so its arc is
  w_i/Σw · 360°. The wheel is fixed to the ring with offset ψ. LED j shows the
  colour at wheel angle β_j = α_j − θ_r − ψ, area-weighted over the LED's 7.5°
  footprint. The pointer is the LED `pointer_led` (setting, default 12, which
  is θ = 90°), and the OLED shows an arrow toward it.

### 6.3 Power limiter

* **Current model, per frame:**
  I = Σ_LED Σ_ch (code/255)·I_ch + 0.2 mA × (number of lit LEDs) + 0.05 mA.
  I_ch is 5 or 12 mA by variant. The 0.2 mA per-IC operating current comes
  from the WS2812B PCN and is TVP for the C variant.
* **Budget:** **150 mA sustained, 300 mA bursts of at most 2 s.**

```c
/* token bucket, dt = frame period */
#define I_SUST  150.0f    /* mA */
#define I_BURST 300.0f
#define BUCKET  ((I_BURST - I_SUST) * 2.0f)   /* 300 mA·s */
bucket = clampf(bucket + (I_SUST - I_req) * dt * (I_req < I_SUST ? 0.2f : 1.0f), 0, BUCKET);
float cap = (bucket > 0) ? I_BURST : I_SUST;
cap = fminf(cap, derate_cap());          /* battery, thermal, actuator, USB rules */
float s = (I_req > cap) ? cap / I_req : 1.0f;
scale_codes(frame, s);                   /* current is linear in code, so this is exact */
/* instantaneous budget (PI-2): a lit channel draws its full I_ch while its PWM is on */
float pk = peak_cap();                   /* VBAT row below, minus 0.23 A while moving, USB rule */
while (lit_channels(frame) * I_CH > pk)
    zero_dimmest_channel(frame);         /* scaling codes does not lower the peak */
```

* **Instantaneous (lit-channel) budget.** The average cap dims each channel
  by lowering its PWM duty, but a lit channel still sinks its full 5 mA
  while its PWM is on. With all 48 LEDs lit at any brightness and their
  2 kHz PWM in phase (the worst case), the ring draws 0.72 A for
  70–210 µs every 500 µs, and VLED sags almost as far as at DC. Firmware MUST
  therefore also cap Σ(lit channels) × I_ch (hardware/sim, PI-2):

  | Rested VBAT (V) | 3.48 | 3.53 | 3.60 | 3.65 | 3.70 | 3.80 | ≥ 3.90 |
  |---|---|---|---|---|---|---|---|
  | Allowed peak (A) | 0.19 | 0.28 | 0.33 | 0.42 | 0.51 | 0.69 | full ring |

  * Use the row at or below the rested VBAT, and subtract about 0.23 A while
    the actuator moves.
  * **On USB** VBAT cannot be measured ([§12.4](#124-battery-measurement-and-low-battery-policy)):
    use the 3.48 V row until CHG_STAT reports CV or done, or keep the total
    on-USB load (LEDs + OLED + actuator) ≤ 0.40 A (hardware/sim, NF-1).
  * With the B variant, I_ch = 12 mA and the cap at full battery is about
    1.0 A (hardware/sim, PI-3).
  * *TVP:* bring-up scopes the summed ring current after power-up to see
    whether the V6 PWM phases really align; the budget stays until that is
    measured.

* **Derating** (VBAT is the rested estimate, [§12.4](#124-battery-measurement-and-low-battery-policy)):

  | Condition | Cap |
  |---|---|
  | VBAT ≥ 3.65 V | 150/300 mA (re-enable threshold, with hysteresis) |
  | VBAT < 3.60 V | 100 mA, no bursts |
  | VBAT < 3.53 V | LEDs off except one dim red low-battery cue (≤ 2 mA); SHIP follows ([§12.4](#124-battery-measurement-and-low-battery-policy)). Red Vf stays in regulation. |
  | Loaded VSYS < about 3.3 V (WS2812C VDD minimum), any reading | All-zero frame, then LED_PWR_EN low ([§6.4](#64-rail-sequencing); hardware/sim, LED-DATA-3) |
  | Actuator moving | 100 mA |
  | nRF die temperature > 55 °C | 100 mA sustained |
  | On USB, charging (optional "charge first") | 150 mA, no bursts; instantaneous budget per the USB rule above |
  | **VBUS present but input limit still 100 mA** (TMR_ILIM = 0xC9, before USB "configured" or charger detection, [§13.3](#133-input-current-strategy-on-usb)) | **20 mA**, no bursts: the charging cue. No actuator moves (homing is deferred). OLED_VCC_EN stays low unless the battery can supplement SYS (no BUVLO_STAT and VBAT ≥ about 3.15 V); only then OLED C7 ≤ 04h (hardware/sim, NEW-1, OLED-V1). Lifted when ILIM goes to 500 mA (at most about 2 s after VBUS). With a battery below BUVLO or absent, the BQ25180 cannot supplement SYS ([SLUSE99C §8.3.3](https://www.ti.com/lit/ds/symlink/bq25180.pdf)) and the 100 mA input cannot carry the OLED boost's turn-on surge, so an uncapped boot (OLED VCC, LED animation, homing at run current) collapses SYS into a brown-out reboot loop exactly in the "battery empty, plug in" case. |
  | **No supplement** on USB: pack absent, STAT1 BUVLO_STAT = 1, or CHG_STAT = precharge | ILIM 100 mA phase: LEDs at most the ≤ 20 mA charging cue, OLED off, no flash erase, BLE TX 0 dBm, total ≤ 70 mA. ILIM 500 mA phase: no actuator moves, LEDs ≤ 100 mA and peak-limited, OLED C7 ≤ 08h, total ≤ 400 mA. Without this profile both USB budgets exceed the ILIM minimum (80 / 450 mA) and SYS has no operating point (hardware/sim, PI-4). |
  | VLED fault latched, or the last reset was a brown-out/BATOCP with LED_PWR_EN set | LEDs off ([§15](#15-fault-handling); hardware/sim, NEW-5, NF-3) |

  While the LEDs run above the 150 mA sustained cap (bursts), the OLED is
  held at C7 ≤ 08h and ≤ 30 % white ([§7.4](#74-burn-in-mitigation-and-power-caps)).

* **Hardware worst case** without the limiter is 730 mA for 48 C-variant LEDs
  at full white, or 1.74 A for the B variant; with the OLED at full white, both
  coils on and the +3V3 peak the system draws about 1.33 A, which pulls VLED
  below the WS2812C's 3.3 V minimum at VBAT 3.7 V and browns the system out at
  the end of discharge. The LED/OLED/motor limiter is therefore a
  hardware-protection function: it MUST be active from the first frame after
  reset, and MCUboot and the USB-recovery image MUST keep LED_PWR_EN,
  OLED_VCC_EN and MOT_NSLEEP low (their pull-downs R3, R25 and R70 hold them
  off until firmware drives them; [§11.2](#112-mcuboot-configuration))
  (hardware/sim, PI-1).

### 6.4 Rail sequencing

* **Off** (SPEC §5.4: "drive P0.06 low and send an all-zero frame before
  switching VLED off"):
  1. Send an all-zero frame and wait for it to finish (the I2S idles low).
  2. Configure P0.06 as a GPIO output driven low:
     `gpio_pin_configure_dt(&led_din, GPIO_OUTPUT_LOW)`, with `led_din` from
     `led-din-gpios` in [§3.1](#31-board-dts-draft). The GPIO setting applies
     whenever the I2S is not driving the pin, so DIN never floats on the
     100 kΩ pull-down alone; `i2s0_sleep` (no low-power-enable) also leaves it
     an output low.
  3. `regulator_disable(vled)`. Firmware MUST wait at least 30 ms before
     turning on again or treating VLED as off: the QOD discharges C8, C9 and
     C101–C148 through R4 = 68 Ω plus the switch's internal QOD resistance,
     taking VLED to 10 % in about 24 ms nominal and 26.6 ms worst case
     (3.48 V start, C8/C9 +20 %, DC bias) (SPEC §5.1; hardware/sim, LSW-2).
     Test 12 measures tFALL: the datasheet tFALL row implies an internal QOD
     of about 170 Ω rather than 150 Ω (hardware/sim, NEW-4).

  This order is a hard rule (hardware/sim, LSW-3): all-zero frame, P0.06
  low, then LED_PWR_EN low. Firmware MUST never drive P0.06 high while VLED
  is off: QOD holds VLED near 0 V, DIN would sit more than 0.7 V above it
  (WS2812C abs max VDD + 0.7 V) and back-power the ring through its ESD
  diode, and a larger R40 does not cure it at cold. Fitting the DNP U43
  (SN74LV1T34, Ioff) with C43 and removing R43 makes a violation harmless;
  the rule stays in firmware either way.
* **On:** first check the VLED fault latch and the last reset ([§15](#15-fault-handling));
  record LED_PWR_EN = 1 in the retained rail-state record. Then
  `regulator_enable(vled)` (LED_PWR_EN high) and wait at least 10 ms with
  P0.06 held low (the regulator's `startup-delay-us`): VLED must be at least
  2.5 V before DIN goes high, because of the DI abs max of VDD + 0.7 V; U2's
  tON is about 4 ms with C7 = 1 nF from CT to VIN (check the ramp at test 12)
  (hardware/sim, LED-DATA-V4). Only then hand P0.06 back to the I2S:
  PSEL.SDOUT stays assigned, so the I2S takes the pin when it next starts;
  re-apply the I2S default pinctrl state (H0H1) if the scope shows no data
  (TVP). Then request the HFXO ([§6.1](#61-hardware-facts-used)) and send the
  first frame.
* **Low VSYS:** when the loaded VSYS falls below about 3.3 V (the WS2812C
  VDD minimum), firmware MUST send an all-zero frame and drop LED_PWR_EN,
  using the off sequence above (hardware/sim, LED-DATA-3).
* The V6 standby current is 1 µA or less per LED, but the rail is still
  gated, because DESK_IDLE and SLEEP budget it at about 0.

---

## 7. Display

### 7.1 SPI link and the SPIM3 errata

* **Panel:** NHD-1.5-128128G (Orient AOC128128A0-1.50W is pin-identical),
  SSD1351, 128×128 RGB565, write-only 4-wire SPI.
* **Interface:** SPIM3 at **16 MHz**, mode 0. The SSD1351 maximum is 20 MHz
  (tcycle 50 ns, [SSD1351 DS](https://cdn-shop.adafruit.com/datasheets/SSD1351-Revision+1.3.pdf)),
  and SPIM3's next step up is 32 MHz. A full frame (32 KB) takes 16.4 ms, so
  at most about 60 fps.
  * The SSD1351 also requires tR/tF ≤ 15 ns. Check the edges at the FPC with
    the H0H1 drive (TVP).
* **Anomaly 198:** SPIM3 TX data is corrupted if the CPU accesses the same RAM
  AHB slave during a transfer
  ([errata 198](http://docs.nordicsemi.com/r/bundle/errata_nrf52840_rev3/page/err/nrf52840/rev3/latest/anomaly_840_198.html)).
  The Zephyr/nrfx workaround (on by default) gives SPIM3 priority over the
  buffer's RAM block, which **stalls the CPU** on any access to that block. A
  buffer in the 192 KB AHB slave 8, where the stacks live, would freeze the
  CPU, and the BLE ISRs with it, for 4–16 ms. So:
  * The two LVGL draw buffers (8 KB each, 128×32 px RGB565) live in **AHB
    slaves 0 and 1 (0x20000000–0x20003FFF)**. Carve them out of sram0
    ([§3.1](#31-board-dts-draft)) and place `.lvgl_buf` there with a linker
    snippet (`CONFIG_LV_Z_VDB_CUSTOM_SECTION`). Verify in `zephyr.map` that
    nothing else lands there.
  * Command bytes sent from the stack cause only brief stalls of a few µs,
    which is acceptable.
  * With NCS Partition Manager, check that the RAM layout does not override
    the sram0 change (TVP).
* **Anomaly 195:** SPIM3 draws about 900 µA after disable unless
  0x4002F004 = 1 is written. nrfx applies this on uninit. **Measure sleep
  current** to confirm.
* **Fallback:** the same pins work with SPIM2 at 8 MHz (32.8 ms per frame,
  30 fps max, no anomalies). That needs only a devicetree change, and it gives
  up SPIM2 as the LED fallback.

### 7.2 Init sequence and power sequencing

The mainline `solomon,ssd1351` driver (`display_ssd135x.c`) does **not**
clear RAM before AFh, set B4h/ABh/B5h/B2h, sequence VCC after init, or support
the ABh-off sleep (verifier). Use a small out-of-tree wrapper or patch,
`oled_power.c`, that owns the sequence below and calls the driver only for
pixel writes. The sequence follows the
[NHD datasheet](https://newhavendisplay.com/content/specs/NHD-1.5-128128G.pdf)
with the verifier's corrections.

| # | Command | Data | Meaning |
|---|---|---|---|
| 0 | (hardware) | | +3V3 (VCI/VDDIO) up at least 1 ms; RES# low at least 10 µs, then high |
| 1 | FDh | 12h | Unlock the command interface |
| 2 | FDh | B1h | Unlock A2/B1/B3/BB/BE/C1 |
| 3 | AEh | | Display off |
| 4 | B3h | F1h | Clock divider / oscillator frequency |
| 5 | CAh | 7Fh | Mux ratio 128 |
| 6 | A2h | 00h | Display offset 0 (also used for the vertical pixel orbit) |
| 7 | A1h | 00h | Start line 0 |
| 8 | A0h | 74h | Remap: 65k RGB565 (bits 7:6 = 01), COM split, scan direction. Flip bits 1 and 4 to match the mounting (FPC toward θ = 270°); TVP. |
| 9 | B5h | 00h | GPIO0/1 off |
| 10 | ABh | 01h | Internal VDD regulator on |
| 11 | B4h | A0h B5h 55h | External VSL (the only valid setting) |
| 12 | C1h | C8h 80h C8h | Contrast A/B/C |
| 13 | C7h | 08h | Master current (n+1)/16: 08h = 56 %, 0Ah = 69 % (normal); 03–04h = 25–31 % (dim) |
| 14 | B9h | | Default linear grey LUT |
| 15 | B1h | 32h | Phase lengths |
| 16 | BBh | 17h | Pre-charge voltage |
| 17 | B2h | A4h 00h 00h | Display enhancement |
| 18 | B6h | 01h | Second pre-charge period |
| 19 | BEh | 05h | VCOMH = 0.82 × VCC |
| 20 | A6h | | Normal display |
| 21 | 15h / 75h / 5Ch | 00h 7Fh / 00h 7Fh / 32 KB of 00h | **Clear GDDRAM before VCC on** |
| 22 | (hardware) | | Check the OLED_VCC_EN rules below, record OLED_VCC_EN = 1 in the retained rail-state record, then OLED_VCC_EN high: U21 (TPS22917) connects VSYS to OLED_VIN, reaching 90 % after a turn-on time tON of about 4 ms (C37 = 1 nF from CT to VIN; 3.8–4 µs/pF, SLVSDW8B §7.6). The TPS61040 (EN = OLED_VIN) starts at its ≈ 1.5 V UVLO while U21 is still ramping; its soft start sets the inrush, ≈ 0.3 A for ~2 ms and 0.4 A peak from VSYS, and it ramps to 13.0 V (SPEC §5.3; hardware/sim, LSW-4, OLED-BST-3) |
| 23 | (wait) | | **200 ms** (Orient sequence) before AFh. The first 10 ms (the regulator's `startup-delay-us`, [§3.1](#31-board-dts-draft)) cover U21's tON and the boost soft start; send nothing that needs VCC before it returns. TVP: measure VCC settling and shorten with margin, but the wait MUST never be below 10 ms (hardware/sim, OLED-V2). |
| 24 | AFh | | Display on; SEG/COM turn on about 200 ms later (tAF) |

| Transition | Sequence | Notes |
|---|---|---|
| **Sleep** (DESK_IDLE, SLEEP) | AEh → ABh 00h (VDD regulator off) → OLED_VCC_EN low | RES# stays high, so GDDRAM is retained. U21's QOD holds OLED_VIN at about 0 V, so the TPS61040 stays in shutdown; +13V_OLED floats behind D21. About 17.6 µA total at 25 °C (typical): ICI about 4 µA, about 5 µA through the panel's VCI→VCC ESD path into the 499 k/52.3 k divider, 3.3 µA in the RES# pull-down, and about 5.4 µA of D21 (B5819W) reverse leakage from the ESD-held +13V_OLED (about 2.7 V) that U21's QOD sinks; that leakage is about 30 µA at 60 °C. Datasheet maximum about 46 µA at 25 °C and 72 µA at 60 °C (hardware/sim, sleep budget; accepted for rev A). |
| **Wake** | ABh 01h → VCC_EN high → wait (step 23) → AFh → **full-frame rewrite** | The rewrite self-heals any SPI corruption. Wake-to-visible takes about 200–400 ms, so the LEDs give feedback within 5 ms. |
| **Short idle** (DIM) | AEh only, VCC kept on | About 5 mA. Gives instant re-show for idles under 30 s. |
| **Off for long storage / ship** | AEh → VCC_EN low → RES# low | VCI stays up (no switch on +3V3) |

Never apply VCC while VCI is off. U21 guarantees this in hardware: R25 holds
its ON pin low whenever the nRF (on +3V3, which also feeds VCI) is unpowered
or in reset, and its QOD pulls OLED_VIN below 0.4 V within 1.6 ms of a reset
(hardware/sim, LSW-1). Firmware keeps the order anyway.

**OLED_VCC_EN rules** (`oled_power.c` checks them before every enable):

* Firmware MUST never set OLED_VCC_EN while the BQ25180 input limit is
  100 mA (TMR_ILIM = 0xC9) unless the battery can supplement SYS: no
  BUVLO_STAT and VBAT ≥ about 3.15 V, taken from the last battery-only
  reading (unknown counts as "cannot"). It raises OLED_VCC_EN only after
  ILIM = 500 mA, and until then shows the charging cue on the LEDs (≤ 20 mA).
  A dead battery cannot supplement SYS and the 100 mA input cannot carry the
  boost's turn-on surge, so otherwise the unit reboot-loops exactly in the
  "battery empty, plug in" case (hardware/sim, NEW-1, OLED-V1; [§13.3](#133-input-current-strategy-on-usb)).
* Firmware MUST NOT toggle OLED_VCC_EN during an actuator move while
  VBAT < 3.6 V; it enables the OLED before a park move ([§5.8](#58-limits);
  hardware/sim, NEW-2).
* Firmware records OLED_VCC_EN in the retained rail-state record. If the
  next reset is a brown-out, or the BQ25180 reports BAT_OCP_FAULT (FLAG0
  bit 0), with OLED_VCC_EN recorded high, it MUST leave the OLED off for the
  session and show an error on the LEDs ([§15](#15-fault-handling);
  hardware/sim, OLED-V3). Assembly inspects J20 pins 1–2 (VCC next to GND at
  0.5 mm pitch).

### 7.3 LVGL configuration

* LVGL 9 (the Zephyr module), partial render mode, 2 × 8 KB buffers, RGB565.
  Check byte order: the SSD1351 expects MSB first, so enable the Zephyr
  display driver's swap if colours look wrong.
* 48 KB heap. The `lvgl_thread` runs at priority 9 and 30 fps, below BLE and
  the sensors.
* **Geometry.** SPEC's Ø30 mm window shows about 90 % of the 26.86 mm square
  active area. Keep all content inside a centred circle of r ≤ 61 px, which
  leaves 3 px for the pixel orbit. Centre (63.5, 63.5); pixel pitch 0.21 mm.
* **Frame budget.** Each 32-row chunk takes 4.1 ms to send. Full-screen
  animation is at most about 50 fps; the target is 30 fps.
  * There is no TE line, so expect tearing on full-screen motion. Prefer
    partial-window updates (number readouts, the label under the pointer).
  * For a spinning-wheel graphic on the OLED, blit pre-rendered 4 bpp frames
    (8 KB each) from QSPI littlefs or internal flash rather than doing
    real-time image transforms.
* **Assets.** Small fonts go in internal flash; large images and themes go on
  QSPI littlefs, through the LVGL FS driver.

### 7.4 Burn-in mitigation and power caps

| Rule | Value |
|---|---|
| Theme | Black background. Static elements at ≤ 40 % grey. Nothing static at full white for more than 1 min. |
| Auto-dim / off | C7 03–04h after 10 s; display sleep after 30 s (setting 10–300 s). No mode may show a static screen without a timer; an "always on" clock face must move. |
| Pixel orbit | ±2 px every 60 s. Vertical via A2h, horizontal via the LVGL root offset. |
| Status | Battery and link state show on the LED ring (brief), not as permanent OLED icons |
| Master current | C7 ≤ 0Ah in normal use. "Bright" mode (0Fh) only on user request, with a timer, and only above the low-battery limit below. |
| Low battery / boost headroom | Firmware MUST hold C7 ≤ 08h and no screens with more than 30 % white area below rested VBAT 3.75 V ([§12.4](#124-battery-measurement-and-low-battery-policy)) and whenever the LED current exceeds its 150 mA sustained cap. At 3.6 V the worst-case boost stack (TPS61040 current limit, L20 −20 %, DCR and U21 RON at maximum) cannot deliver the panel's 42 mA 100 %-on maximum at VCC ≥ 12.5 V; 3.75 V leaves about 70 mV over the 3.68 V crossover for the BATFET and harness drop (hardware/sim, OLED-BST-2). |

---

## 8. Audio and press input

### 8.1 Piezo

* PKMCS0909E4000-R1, driven complementary from PWM1 at 4.0 kHz (resonance):
  ±3.3 V, about 72 dB(A) minimum at 10 cm (research figure; TVP with the
  470 Ω series resistors).
* A detent or segment tick is 1–2 cycles (0.25–0.5 ms), rate-limited to 200
  ticks/s.
  * Above about 8 rev/s in click mode, tick on segment boundaries rather than
    on every detent (24 × 8 = 192/s).
  * Volume is set by cycle count and duty, in levels 0–3.
* Silent mode is a setting (GATT, menu). With the high-drive outputs and
  470 Ω per side (R57/R58), the edge current is at most about 7 mA (a 6.6 V
  step across 940 Ω; estimate), which is fine. R59 (1 MΩ across BZ1) bleeds
  the piezo while the pins are disconnected in sleep.

### 8.2 Press handling (`press.c`)

* `gpio-keys` with a 5 ms debounce. Gestures:

  | Gesture | Meaning |
  |---|---|
  | Click | Shorter than 0.6 s |
  | LONG | 0.6 s or more |
  | VLONG | 5 s or more (pair a new host in the current slot) |
  | PRESS_ROTATE(±n) | Detents turned while held |

* The BQ25180 sees the same press on TS/MR:
  * A 20 s hold is a hardware power-cycle (by design; [§13](#13-bq25180-charger-driver)).
    No UI gesture may need more than 10 s.
  * Its WAKE1/WAKE2 flags and the brief charge pause during a press are
    ignored.
  * A press pulls TS/MR low, which the TS comparators read as HOT, so
    firmware MUST ignore TS_STAT, TS_FAULT and TS interrupts while BTN_N is
    low and for 5 ms (one debounce) after it returns high; otherwise every
    press while charging can show "too hot to charge" (hardware/sim,
    charger_ts-v2).
* **Flick-artifact rejection** (mechanical research: a hard flick can lift the
  floating assembly and false-click). A press is suppressed when all of these
  hold:
  * it starts within ±40 ms of an angular-acceleration spike above
    50 rev/s², or an IMU |Δa| above 0.5 g;
  * it lasts less than 150 ms;
  * it is not part of a PRESS_ROTATE.

  The thresholds are settings (TVP).
* A press while the panel is asleep wakes the UI. That first press is consumed
  and not sent as HID, unless the host slot is in Dial mode **and** the display
  was in DIM.

---

## 9. BLE

### 9.1 GATT database

| Service | Notes |
|---|---|
| GAP / GATT | Device name "DialSpinner"; appearance 0x03C0; PPCP 11.25–15 ms, latency 0, 4 s timeout |
| HID (0x1812), NCS `bt_hids` | Report map [§9.2](#92-hid-report-map). HID Information: bcdHID 0x0111, country 0, flags 0x03 (RemoteWake + NormallyConnectable). Protocol Mode. 3 input-report characteristics (IDs 1–3), each with a Report Reference descriptor. Encryption required. |
| Battery (0x180F) | Level with notify. Windows shows it. |
| Device Information (0x180A) | Manufacturer, model, firmware revision, PnP ID (VID source 0x02 USB-IF; VID/PID the same as USB, placeholder) |
| SMP (MCUmgr) | DFU and OS group. Authenticated link only. |
| Game service (custom, 128-bit) | [§9.6](#96-custom-game-service) |

### 9.2 HID report map

One fixed composite map serves BLE and USB. **Freeze it before the first
pairing:** Windows caches the map per bond. The bytes are from the MCU/RF
research. ID 1 is byte-identical to the mandatory part of
[Microsoft's Radial Controller sample](https://learn.microsoft.com/en-us/windows-hardware/design/component-guidelines/radial-controller-sample-report-descriptors),
and the whole map parses with balanced collections, with report sizes of
2/2/5 bytes.

```c
static const uint8_t hid_report_map[] = {
    /* ---- Report ID 1: Windows Radial Controller (mandatory usages) ---- */
    0x05, 0x01,        /* Usage Page (Generic Desktop)            */
    0x09, 0x0E,        /* Usage (System Multi-Axis Controller)    */
    0xA1, 0x01,        /* Collection (Application)                */
    0x85, 0x01,        /*   Report ID (1)                         */
    0x05, 0x0D,        /*   Usage Page (Digitizers)               */
    0x09, 0x21,        /*   Usage (Puck)                          */
    0xA1, 0x00,        /*   Collection (Physical)                 */
    0x05, 0x09,        /*     Usage Page (Button)                 */
    0x09, 0x01,        /*     Usage (Button 1)                    */
    0x95, 0x01,        /*     Report Count (1)                    */
    0x75, 0x01,        /*     Report Size (1)                     */
    0x15, 0x00,        /*     Logical Minimum (0)                 */
    0x25, 0x01,        /*     Logical Maximum (1)                 */
    0x81, 0x02,        /*     Input (Data, Var, Abs)              */
    0x05, 0x01,        /*     Usage Page (Generic Desktop)        */
    0x09, 0x37,        /*     Usage (Dial)                        */
    0x95, 0x01,        /*     Report Count (1)                    */
    0x75, 0x0F,        /*     Report Size (15)                    */
    0x55, 0x0F,        /*     Unit Exponent (-1)                  */
    0x65, 0x14,        /*     Unit (Degrees, English Rotation)    */
    0x36, 0xF0, 0xF1,  /*     Physical Minimum (-3600)            */
    0x46, 0x10, 0x0E,  /*     Physical Maximum (3600)             */
    0x16, 0xF0, 0xF1,  /*     Logical Minimum (-3600)             */
    0x26, 0x10, 0x0E,  /*     Logical Maximum (3600)              */
    0x81, 0x06,        /*     Input (Data, Var, Rel)              */
    0xC0,              /*   End Collection                        */
    0xC0,              /* End Collection                          */
    /* ---- Report ID 2: Consumer Control (16-bit usage array) ---- */
    0x05, 0x0C,        /* Usage Page (Consumer)                   */
    0x09, 0x01,        /* Usage (Consumer Control)                */
    0xA1, 0x01,        /* Collection (Application)                */
    0x85, 0x02,        /*   Report ID (2)                         */
    0x55, 0x00,        /*   Unit Exponent (0)    reset the globals */
    0x65, 0x00,        /*   Unit (None)          inherited from    */
    0x35, 0x00,        /*   Physical Minimum (0) ID 1 (essential)  */
    0x45, 0x00,        /*   Physical Maximum (0)                  */
    0x15, 0x00,        /*   Logical Minimum (0)                   */
    0x26, 0xFF, 0x03,  /*   Logical Maximum (1023)                */
    0x19, 0x00,        /*   Usage Minimum (0)                     */
    0x2A, 0xFF, 0x03,  /*   Usage Maximum (1023)                  */
    0x75, 0x10,        /*   Report Size (16)                      */
    0x95, 0x01,        /*   Report Count (1)                      */
    0x81, 0x00,        /*   Input (Data, Array, Abs)              */
    0xC0,              /* End Collection                          */
    /* ---- Report ID 3: Mouse with wheel and AC Pan ---- */
    0x05, 0x01,        /* Usage Page (Generic Desktop)            */
    0x09, 0x02,        /* Usage (Mouse)                           */
    0xA1, 0x01,        /* Collection (Application)                */
    0x85, 0x03,        /*   Report ID (3)                         */
    0x09, 0x01,        /*   Usage (Pointer)                       */
    0xA1, 0x00,        /*   Collection (Physical)                 */
    0x05, 0x09,        /*     Usage Page (Button)                 */
    0x19, 0x01,        /*     Usage Minimum (1)                   */
    0x29, 0x03,        /*     Usage Maximum (3)                   */
    0x15, 0x00,        /*     Logical Minimum (0)                 */
    0x25, 0x01,        /*     Logical Maximum (1)                 */
    0x95, 0x03,        /*     Report Count (3)                    */
    0x75, 0x01,        /*     Report Size (1)                     */
    0x81, 0x02,        /*     Input (Data, Var, Abs)              */
    0x95, 0x01,        /*     Report Count (1)                    */
    0x75, 0x05,        /*     Report Size (5)                     */
    0x81, 0x03,        /*     Input (Const)  padding              */
    0x05, 0x01,        /*     Usage Page (Generic Desktop)        */
    0x09, 0x30,        /*     Usage (X)                           */
    0x09, 0x31,        /*     Usage (Y)                           */
    0x09, 0x38,        /*     Usage (Wheel)                       */
    0x15, 0x81,        /*     Logical Minimum (-127)              */
    0x25, 0x7F,        /*     Logical Maximum (127)               */
    0x75, 0x08,        /*     Report Size (8)                     */
    0x95, 0x03,        /*     Report Count (3)                    */
    0x81, 0x06,        /*     Input (Data, Var, Rel)              */
    0x05, 0x0C,        /*     Usage Page (Consumer)               */
    0x0A, 0x38, 0x02,  /*     Usage (AC Pan)                      */
    0x95, 0x01,        /*     Report Count (1)                    */
    0x81, 0x06,        /*     Input (Data, Var, Rel)              */
    0xC0,              /*   End Collection                        */
    0xC0,              /* End Collection                          */
};                     /* 152 bytes: ID1 56 + ID2 33 + ID3 63 */
```

**Report payloads.** BLE notifications carry no report-ID byte; USB interrupt
IN reports start with it.

| ID | Bytes | Layout |
|---|---|---|
| 1 | 2 | `v = ((dial & 0x7FFF) << 1) \| button`, little-endian. dial is int15 in 0.1° units, positive = clockwise, range ±3600 per report. |
| 2 | 2 | 16-bit consumer usage, 0x0000 = release. Used: 0x00E9 Vol+, 0x00EA Vol−, 0x00E2 Mute, 0x00CD Play/Pause, 0x00B5 Next, 0x00B6 Prev. |
| 3 | 5 | buttons (bits 0–2), X, Y (always 0), Wheel int8, AC Pan int8 |

**Scaling and host-slot modes**

| Slot mode | Rotation | Press | Notes |
|---|---|---|---|
| Dial (Windows) | CLICK: **100 units (10.0°) per detent** by default (setting 1–3600). FREE: 10 × Δdeg × gain, clamped ±3600 per report, remainder carried. | ID 1 button bit | 100 per detent assumes Windows' default RotationResolutionInDegrees is 10°, which is **unverified**. docs/architecture.md says 150 per detent. Test in Windows Wheel settings and pick the default from that (TVP). |
| Media | Vol± per detent (ID 2) | Play/Pause; long press = Mute | |
| Scroll (macOS, iOS, Linux, Android) | Wheel ±1 per detent (ID 3) | Button 3 (middle); PRESS_ROTATE = AC Pan | Smooth scroll in FREE: ±1 per 7.5°. High-resolution scrolling would need a Resolution Multiplier feature report, which is not in the frozen map; that is a v2 option. |

* Send reports only on change, with at most one notification per report ID in
  flight (nRF Desktop pattern). Accumulate deltas while waiting so latency
  never builds up.
* At 10 rev/s in FREE that is 540 units per 15 ms report, far inside ±3600.
* The keyboard collection is deliberately left out: iOS hides the soft
  keyboard while a BLE keyboard is connected.

### 9.3 Advertising

The SoftDevice Controller runs two extended-advertising sets with legacy PDUs
(`CONFIG_BT_EXT_ADV`, 2 sets).

**Set A: HID, under the identity of the active host slot.**

Pairing-mode payload. Swift Pair requires the name and appearance **in the
same packet**, because Windows does not active-scan, so the 31-byte budget
allows a name of 11 characters at most:

```
02 01 06                                  Flags (LE General Discoverable, no BR/EDR)
03 19 C0 03                               Appearance 0x03C0 (Generic HID)
03 03 12 18                               16-bit UUIDs: 0x1812 (HID)
06 FF 06 00 03 00 80                      Microsoft (0x0006), Swift Pair beacon 0x03,
                                          sub-scenario 0x00 (LE only), reserved RSSI 0x80
0C 09 44 69 61 6C 53 70 69 6E 6E 65 72    Complete Local Name "DialSpinner"
                                          = 31 bytes
```

| Phase | Payload | Interval / duration |
|---|---|---|
| Pairing (VLONG press or empty slot) | As above, including Swift Pair | 30 ms for 30 s, then 100 ms up to 3 min, then stop |
| Reconnect (bonded slot) | No Swift Pair section (**remove it outside pairing mode**) | If the peer uses an identity address: high-duty directed advertising for 1.28 s. Otherwise, or after that: undirected with the filter accept list (only the bonded peer can connect) at 30 ms for 10 s, 100 ms for 60 s, 1 s for 10 min, then stop → SLEEP. |

**Set B: app, under identity 0.** Connectable, legacy PDU. Advertising data is
`02 01 06 | 11 07 <128-bit service UUID>` (21 B); the scan response is the
name. Interval 152.5 ms while awake (ACTIVE or DIM), 1 s in DESK_IDLE, off in
SLEEP. Off entirely in Controller mode unless "app always" is set.

### 9.4 Identities, bonding and pairing

| Identity | Role | Bonds |
|---|---|---|
| ID 0 | Game app (phones, Web Bluetooth) | Up to 3 phones |
| ID 1–3 | Host slots 1–3 (nRF Desktop `ble_bond` pattern) | One host each |

* `CONFIG_BT_ID_MAX = 4`, `CONFIG_BT_MAX_PAIRED = 6`, `CONFIG_BT_MAX_CONN = 2`:
  one HID host plus one app phone at the same time. Only the active slot
  advertises.
* **Slot switching.** LONG press + rotate opens the slot menu on the OLED;
  rotate and release to select. Firmware then **always disconnects the old
  host** and advertises on the new identity. Keeping the old host connected
  is not possible with this configuration: old host + new host + app phone is
  3 links against `CONFIG_BT_MAX_CONN = 2`, and `bt_hids` serves one client.
  (A v2 could raise `CONFIG_BT_MAX_CONN` to 3 and
  `CONFIG_BT_HIDS_MAX_CLIENT_COUNT` to 2, about +5 KB of RAM, and route
  reports only to the active slot.) A VLONG press on a slot clears its bond (`bt_id_reset`) and starts
  pairing.
* **Pairing:** LE Secure Connections with numeric comparison (IO capability
  DisplayYesNo). The OLED shows the 6-digit code (waking it if needed); a press
  confirms and a long press rejects.
* **HIDS isolation.** The GATT database is shared across identities. Use the
  custom GATT authorization callback
  (`bt_gatt_authorization_cb_register()`, `CONFIG_BT_GATT_AUTHORIZATION_CUSTOM`)
  to **deny HID-service reads and CCCD writes on ID 0 connections**, so a
  bonded phone running the app does not grab the dial as an input device. Web
  Bluetooth cannot reach 0x1812 anyway, because it is blocklisted.
* **TVP:** directed advertising to hosts that use resolvable private
  addresses (Apple, Android) may not trigger reconnection; test per OS.

### 9.5 Connection parameters and radio

* **HID link:** request 11.25–15 ms (9–12 units), latency 0 while active. After
  5 s without input, request latency 30 (about 450 ms effective), timeout 4 s.
  This is inside the Apple accessory guidelines (interval ≥ 15 ms, 11.25 ms
  allowed for HID, latency ≤ 30, timeout 2–6 s; unverified against the current
  Apple revision).
  * Some hosts, Windows among them (TVP), may refuse latency. Then desk-idle
    costs about 133 µA instead of about 7 µA ([§12](#12-power-management)).
* **App link:** 30–50 ms, latency 0–4, ATT MTU 247, data length 251, 2M PHY
  allowed. HID stays on 1M.
* **TX power:** +4 dBm by default. Raise to +8 dBm when the measured
  connection RSSI is below −80 dBm (dynamic TX power control). In normal-voltage
  mode the VDD load limit of high-voltage mode does not apply.

### 9.6 Custom game service

* **UUIDs are placeholders.** Generate one random v4 base before the first
  release and keep the 16-bit field `xxxx`: `d1a1xxxx-7a3e-4c55-9f1b-2b5d0e6c8a01`.
  The service is `d1a10001-…`.
* All values are little-endian.
* **Security:**
  * Reads and notifications of `spin_event`, `spin_result` and `status` are
    open, which keeps Web Bluetooth simple.
  * All writes need an encrypted (bonded) link. Exception: during **party
    mode** (enabled on the device for 10 min), `wheel_config`,
    `segment_table` and `led_theme` accept unencrypted writes from guests.
  * Commands marked † also need a physical press to confirm.

| UUID (xxxx) | Name | Properties | Size | Layout |
|---|---|---|---|---|
| 0002 | `detent_mode` | R/W/N | 1 | 0 FREE, 1 CLICK, 2 AUTO, 3 BRAKE |
| 0003 | `detent_strength` | R/W/N | 2 | u8 strength 0–100 % (0 = free); u8 flags (bit0 prefer damped/shoe) |
| 0004 | `wheel_config` | R/W | 16 | u8 version = 1; u8 n_segments (2–48); u8 pointer_led (0–47); u8 fair_flags (bit0 shuffle the offset at spin start, bit1 require a minimum spin); u8 min_revs_x10 (default 20 = 2.0 revolutions); u8 tick_mode (0 off, 1 detent, 2 segment); u8 volume (0–3); u8 hid_slot_mode; u16 dim_s; u16 display_off_s; u16 sleep_min; u16 reserved |
| 0005 | `segment_table` | W, R | ≤ 22 | Write {u8 idx, u8 r, g, b, u8 weight, u8 label_len, UTF-8 label ≤ 16}. A write with label_len = 0xFF selects idx for the next read. |
| 0006 | `spin_event` | N (≤ 20 Hz spinning, 50 Hz during the final second) | 20 | u8 version; u8 state (0 idle, 1 spinning, 2 coasting, 3 capturing, 4 settled); u16 seq; u32 t_ms; u16 angle_cdeg (0–35999); s16 turns; s16 velocity_dps; u8 segment_now; u8 predicted_segment; u8 confidence (0–255); u8 detent (0–23); u16 reserved |
| 0007 | `spin_result` | R/N | 20 | u8 version; u8 flags (valid, shuffled, brake used, touched, too weak); u16 seq; u8 segment; u8 n_segments; u16 final_angle_cdeg; u16 revolutions_x10; u32 duration_ms; u16 peak_dps; u32 t_end_ms |
| 0008 | `led_theme` | R/W | 12 | u8 theme_id; u8 brightness % (still capped by [§6.3](#63-power-limiter)); u8 primary r,g,b; u8 secondary r,g,b; u8 effect_id; u8 speed; u8 idle_effect; u8 flags (bit0 status indications on the ring) |
| 0009 | `status` | R/N (on change, ≤ 1 Hz) | 16 | u8 version; u8 battery %; u16 vsys_mV; u8 charge_state; u8 power_state; u8 detent_state; u8 detent_mode; u16 detent_offset_um; u16 fault_flags; u8 active_slot; u8 fw major/minor/patch packed in 2 B (4/6/6 bits) |
| 000A | `command` | W without response | 1 + n | 0x01 identify (blink + beep); 0x02 start encoder calibration; 0x03 re-home actuator; 0x04 demo spin animation; 0x05 select host slot n; 0x06† clear slot n; 0x07† enable party mode; 0x08† reboot to serial recovery; 0x09 set time (u32 Unix); 0x0A play sound n |
| 000B | `raw_angle` | N, ≤ 50 Hz, off by default | 12 | u32 t_ms; s64 pos (motion units) |
| 000C | `nfc_tag` | R/W | ≤ 20 per write | Draft. Write {u8 op; payload}: 0 tag off, 1 set NFCID1 (4, 7 or 10 B), 2 append an NDEF chunk, 3 commit (store and restart emulation), 4 clear. Read: u8 enabled; u8 tag type (2 or 4); u16 NDEF length; NFCID1 ([§9.7](#97-nfc-tag-emulation)) |

**Valid spin (game).** A spin counts if it covers at least `min_revs_x10`/10
revolutions and peaks at 1.5 rev/s or more. Otherwise the result is flagged
"too weak", with a "spin again" prompt. The optional shuffle re-randomises ψ
from the hardware RNG at `SPIN_START`, shown with a quick LED wipe, which
defeats practised flicks.

### 9.7 NFC tag emulation

* **Hardware** (SPEC §5.2): the NFCT on P0.09/P0.10 (NFC1/NFC2), C16/C17 =
  180 pF C0G from each pin to GND, and a 13.56 MHz flex coil
  (about 1.4–1.5 µH) in the top cover, soldered to the pads J11 on the
  main-board top. UICR NFCPINS stays in NFC mode ([§1.3](#13-gpio-configuration)).
  C16/C17 are retuned on the prototype for the coil's real inductance.
* **Function.** The dial is an NFC-A tag that phones read: Type 2 (NCS
  `nfc_t2t`) or Type 4 (`nfc_t4t`, for larger NDEF messages). The NDEF
  content (for example a URI or a text record) and the NFCID1 can be changed
  at run time: stop emulation, set the payload and the NFCID1 parameter,
  start again (`nfc_t2t_emulation_stop()`, `nfc_t2t_payload_set()`,
  `nfc_t2t_parameter_set()` with `NFC_T2T_PARAM_NFCID1`,
  `nfc_t2t_emulation_start()`, and the `nfc_t4t_*` equivalents; check names).
  The content lives in `cfg/nfc` ([§11.4](#114-settings-schema)).
* **"Read a tag" is done by the phone.** The nRF52840 NFCT is a tag only and
  cannot read tags. The app reads a tag with the phone and sends its content
  to the spinner over BLE (`nfc_tag`, [§9.6](#96-custom-game-service); writes
  need an encrypted link). Only open NDEF content and a chosen NFCID1 are
  reproduced: encrypted badges and payment cards cannot be emulated.
* **Power.** Between reads the NFCT sits in field sense, about 100 nA in
  sleep (hardware/sim, SLP-V1). A reader field raises FIELDDETECTED, which
  wakes the CPU from System ON idle ([§12.3](#123-wake-sources)); the NFCT
  can also wake the chip from System OFF, which this design does not use. In
  SHIP and SHUTDOWN the nRF is unpowered, so the tag is silent.
* *TVP:* read range through the top cover; whether the T2T and T4T libraries
  can be linked into one image (until then, one tag type per build).

---

## 10. USB composite device

* **Stack:** Zephyr `device_next` (USBD). The legacy stack is deprecated in
  NCS 3.x.
* **Descriptors:**
  * Device class 0xEF/0x02/0x01 (IAD); VID/PID placeholder (pid.codes 0x1209
    or a purchased VID).
  * Strings: manufacturer, "dial-me-spinner", and a serial from the FICR
    DEVICEID.
  * One configuration with bmAttributes 0xA0 (bus-powered, remote wakeup) and
    **bMaxPower 0xFA (500 mA)**. This must cover the charger's input current
    ([§13.3](#133-input-current-strategy-on-usb)). The verifier corrected the
    research's 100 mA, which is non-compliant while charging.

| Interface | Class | Use |
|---|---|---|
| HID `hid_dial` | HID, no boot protocol | Same report map; IN reports with the report ID; 4 ms polling |
| CDC ACM `cdc_acm_smp` | CDC ACM | MCUmgr SMP (DFU, image list, reset) |
| CDC ACM `cdc_acm_shell` | CDC ACM | Shell + log (factory test, debugging) |

* **Routing.** When the USB HID interface is configured, HID reports go to USB
  and the BLE HID link stays connected but silent. A setting allows "both". On
  USB suspend the HID path is idle; a rotation sends a remote-wakeup request if
  the host enabled it.
* **USB suspend and the 2.5 mA limit:** the BQ25180 draws about 1 mA from
  VBUS even when idle (IQ_IN 0.75 mA typical, no input high-impedance mode),
  so the device meets the suspend limit only as a high-power device with
  remote wakeup (the descriptor above) and with charging stopped. On the
  suspend event firmware MUST therefore disable charging and set
  battery-only SYS (or drop ILIM to the 50 mA code), and restore on resume
  ([§13.3](#133-input-current-strategy-on-usb); hardware/sim, V-2).
* There is no CC-pin sensing to the MCU (SPEC: 5.1 kΩ Rd only), so firmware
  cannot see 1.5 A or 3 A Type-C sources. It always stays at the 500 mA input
  code.

---

## 11. Boot, partitions and DFU

### 11.1 Partitions

`pm_static.yml` (NCS Partition Manager; NCS is moving to devicetree partitions,
so port this if your release defaults to that):

```yaml
mcuboot:              { address: 0x0,      size: 0x10000,  region: flash_primary }
mcuboot_pad:          { address: 0x10000,  size: 0x200,    region: flash_primary }
app:                  { address: 0x10200,  size: 0xE7E00,  region: flash_primary }
mcuboot_primary:      { address: 0x10000,  size: 0xE8000,  span: [mcuboot_pad, app], region: flash_primary }
mcuboot_primary_app:  { address: 0x10200,  size: 0xE7E00,  span: [app], region: flash_primary }
settings_storage:     { address: 0xF8000,  size: 0x8000,   region: flash_primary }
mcuboot_secondary:    { address: 0x0,      size: 0xE8000,  device: DT_CHOSEN(nordic_pm_ext_flash), region: external_flash }
factory_backup:       { address: 0xE8000,  size: 0x10000,  device: DT_CHOSEN(nordic_pm_ext_flash), region: external_flash }
crash_log:            { address: 0xF8000,  size: 0x8000,   device: DT_CHOSEN(nordic_pm_ext_flash), region: external_flash }
littlefs_storage:     { address: 0x100000, size: 0xF00000, device: DT_CHOSEN(nordic_pm_ext_flash), region: external_flash }
```

* Primary slot = 1024 − 64 − 32 = **928 KB**. Swap-using-move needs one spare
  sector, so the largest image is about 920 KB. The estimated image is
  500–600 KB (SDC + host + HIDS + SMP about 250 KB, USB about 35 KB, LVGL +
  fonts 150–200 KB, app about 80 KB). **CI fails the build above 880 KB.**
* Both flashes have 4 KB sectors, which swap-move requires.

### 11.2 MCUboot configuration

* Signed images (ECDSA P-256, verified with CC310) in swap-using-move mode.
  The secondary slot is in QSPI, so MCUboot includes the QSPI NOR driver
  (`sysbuild/mcuboot.conf`: `CONFIG_NORDIC_QSPI_NOR=y`, and
  `sysbuild/mcuboot.overlay` carries the same `&qspi` node).
* **Serial recovery over USB CDC ACM** (`CONFIG_MCUBOOT_SERIAL=y`,
  `CONFIG_BOOT_SERIAL_CDC_ACM=y`). It is entered by:
  * holding the dial pressed while plugging in USB or at reset (DT alias
    `mcuboot-button0` = BTN_N); or
  * the app's boot-mode retention request (command 0x08, or the shell):
    `bootmode_set(BOOT_MODE_TYPE_BOOTLOADER)` then `sys_reboot()`. It uses the
    `boot_mode0` retained-RAM partition and the `zephyr,boot-mode` chosen node
    ([§3.1](#31-board-dts-draft)); MCUboot needs the retention options listed
    under `sysbuild/mcuboot.conf` in [§3.4](#34-kconfig-highlights-prjconf).

  With the USB stack inside, MCUboot is about 64 KB. **Size it from a real
  build** before freezing `pm_static.yml`. The verifier warned that 48 KB is
  not credible.
* **MCUboot and the recovery image keep the loads off.** They MUST never
  drive LED_PWR_EN (P1.04), OLED_VCC_EN (P1.02) or MOT_NSLEEP (P1.15) high;
  leave the pins at their reset default so R3, R25 and R70 keep U2, U21 and
  the DRV8837s off. The app's limiter ([§6.3](#63-power-limiter)) is not
  running there, and it is a hardware-protection function (hardware/sim,
  PI-1).
* MCUboot cannot check the battery. The app refuses to mark an upload for test
  unless USB is present or VBAT ≥ 3.6 V rested. A swap of about 600 KB takes
  about 30–60 s (estimate). The W25Q128 needs VDD ≥ 2.7 V, and the LDO tracks
  VBAT in dropout.

### 11.3 DFU paths

| Path | Transport | Tool |
|---|---|---|
| BLE | SMP service, authenticated link | nRF Connect Device Manager (iOS/Android), mcumgr-web (Web Bluetooth) |
| USB | SMP on `cdc_acm_smp` | `mcumgr --conntype serial`, `nrfutil` |
| Recovery | MCUboot serial recovery on USB CDC | Same, from the bootloader |
| Debugger | SWD on TC2030 | `west flash`, `nrfutil device` |

**Confirm policy.** After a test boot the app runs a self-test: TMAG present
and locked, BQ registers written, BLE stack up, settings readable. If it
passes, the app calls `boot_write_img_confirmed()`. Otherwise it reboots and
MCUboot reverts.

### 11.4 Settings schema

Settings live in NVS under keys `dial/…`; calibration is mirrored to
`factory_backup`.

* `cal/enc`, `cal/strength`, `cal/vsys_gain`, `cal/home_edges` (s_ast,L, s_rel,L, spread; [§5.4](#54-homing-with-the-drv5032))
* `cfg/mode`, `cfg/detent`, `cfg/wheel`, `cfg/theme`, `cfg/timeouts`,
  `cfg/slot_modes`, `cfg/nfc` (tag type, NFCID1, NDEF message; [§9.7](#97-nfc-tag-emulation))
* `state/carriage` (x, phase, valid flag). `valid` is cleared before the first
  step of every move and set right after SETTLE ([§5.2](#52-state-machine)).
* `state/vled_fault` (the latched VLED service fault, [§15](#15-fault-handling);
  cleared only by the factory shell)
* `bt/…` (bonds, owned by the BT stack)

Factory data (written once): serial, LED variant, shoe_x_max, hardware
revision.

### 11.5 Debug access and APPROTECT

* `dev` and `factory` builds keep APPROTECT open, so SWD always works.
* Rev 3 silicon (build code Fx0) closes the debug port after reset unless
  firmware opens it, and the module's silicon revision is not stated. Read
  FICR at bring-up. A locked part is recovered with `nrfutil device recover`
  (full erase).
* `release` builds may lock. MCUboot serial recovery is the no-debugger repair
  path.

---

## 12. Power management

### 12.1 States

Currents are battery-side and consistent with the docs/architecture.md §8
budget. The modelled ones are TVP: **measure every state with a PPK2.**

| State | Entered when | Display | LEDs | TMAG | IMU | BLE | nRF | Expected current |
|---|---|---|---|---|---|---|---|---|
| **ACTIVE** | Any input or app activity | On, C7 08–0Ah | Per mode, capped | Tracking | LP 12.5 Hz (HP 400 Hz if tap is enabled) | HID 11.25–15 ms, latency 0; app set advertising | Running | Desk about **29 mA**; game about **104 mA** (range 40–180 mA with LEDs) |
| **DIM** | 10 s without input | AEh or C7 03–04h, VCC on | Ambient or off | Tracking for 2 s after motion, then ARMED | LP | Latency 30 | Mostly idle | About 6–12 mA |
| **DESK_IDLE** | 30 s without input (setting) | Sleep (VCC off) | Rail off | W&S ARMED 10 ms | LP wake | Connected, latency 30 (host-dependent) | System ON idle | About **62 µA** at 25 °C, the architecture.md §8.2 budget, which assumes +8 dBm TX and carries the 17.6 µA OLED line of [§7.2](#72-init-sequence-and-power-sequencing); about 2 µA less at the +4 dBm default of [§9.5](#95-connection-parameters-and-radio) (+130 µA if the host refuses latency) |
| **SLEEP** | Host gone and reconnect advertising timed out (about 11 min), or 30 min in DESK_IDLE (setting; "always connected" keeps DESK_IDLE) | Sleep | Off | W&S DEEP 100 ms | LP wake | Off | System ON idle, SENSE wakes | About **38 µA** (25 °C typical, the architecture.md §8.2 sum; about 70 µA at 60 °C) |
| **SHIP** | VBAT < 3.53 V rested (the BQ25180 VBATPOR max of 3.46 V plus the reading's drift over temperature and ageing, [§12.4](#124-battery-measurement-and-low-battery-policy)); user "power off"; idle more than N days (setting, default off) | Unpowered | | | | | Unpowered (BQ25180 BATFET off) | About **6.2 µA** (BQ 3.2 µA + pack PCM about 3 µA) |
| **SHUTDOWN** | Factory/transport command | Unpowered | | | | | | About 3 µA (PCM only); wakes on USB only |

* **System OFF is not used.** It would save only about 2.6 µA of the 38 µA
  floor, because the always-on peripherals dominate: OLED leakage, BQ25180,
  LDO, TMAG, IMU and DRV5032. It also turns every wake into a reset. System ON
  idle with SENSE wakes is the everyday "off"; ship mode is for storage.
* **Sleep floor breakdown (µA, 25 °C typical, VBAT 3.7 V):**

  | Contributor | µA |
  |---|---|
  | OLED leakage, incl. about 5.4 µA of D21 reverse leakage ([§7.2](#72-init-sequence-and-power-sequencing)) | 17.6 |
  | BQ25180 | 4 |
  | Pack PCM | 3 |
  | nRF | 3 |
  | TMAG (DEEP) | 3 |
  | RT9080 LDO | 2 |
  | DRV5032 | 1.6 |
  | IMU | 1.5 |
  | VSYS divider | 1.2 |
  | QSPI in deep power-down | 1 |
  | DRV8837 ×2 | 0.1 |
  | **Total** | **≈ 38** (sum of the lines) |

  The SPICE suite gives 36.0 / 37.4 / 37.5 µA at VBAT 3.0 / 3.7 / 4.2 V and
  31.5 / 37.4 / 70.0 µA at −10 / 25 / 60 °C (VBAT 3.7 V); the D21 leakage
  drives the temperature spread (hardware/sim, sleep budget). The RT9080 line
  is its no-load IQ; its ground current at the real sleep load is not
  specified and is a bring-up measurement (hardware/sim, LDO-6).

### 12.2 Entry and exit procedures

**Cold boot (application)**

1. Read RESETREAS and the retained rail-state record; then the BQ25180 init
   ([§13.1](#131-register-init-table)), whose FLAG0/STAT reads give
   BAT_OCP_FAULT, BUVLO_STAT, VIN_PGOOD and CHG_STAT.
2. Decide the rails from that: a brown-out or BAT_OCP_FAULT with
   LED_PWR_EN or OLED_VCC_EN recorded high keeps that load off for the
   session ([§15](#15-fault-handling)); a latched `state/vled_fault` keeps
   the LEDs off.
3. With VBUS present: TMR_ILIM = 0xC9 and the 100 mA / no-supplement rules
   until the USB state is known ([§13.3](#133-input-current-strategy-on-usb)).
4. LED limiter active before the first frame ([§6.3](#63-power-limiter));
   encoder init; homing if `state/carriage.valid = 0` (deferred while ILIM
   is 100 mA or VSYS is too low, [§5.8](#58-limits)); OLED init last, under
   the OLED_VCC_EN rules of [§7.2](#72-init-sequence-and-power-sequencing).

**DESK_IDLE / SLEEP entry**

1. Actuator idle: wait for any move to finish (OLED_VCC_EN is not toggled
   during a move below VBAT 3.6 V); brake, then drivers asleep
   ([§5.2](#52-state-machine)).
2. Display sleep sequence ([§7.2](#72-init-sequence-and-power-sequencing)).
3. LED rail off ([§6.4](#64-rail-sequencing)).
4. TMAG armed ([§4.8](#48-wake-on-rotation-wake-upsleep)).
5. IMU in wake configuration ([§14.1](#141-wake-configuration-used-in-desk_idle-and-sleep)).
6. Flash: flush settings, QSPI deep power-down (PM runtime).
7. TWIM1, SPIM3 and SAADC suspended (PM device); NFCT left in field sense.
8. HFXO released.
9. For SLEEP only, also stop all advertising.

**Exit** from any wake source:

1. Resume TWIM0 and start encoder tracking (about 1 ms).
2. LED wake animation (5 ms).
3. OLED wake (about 200–400 ms).
4. BLE: reconnect advertising if not connected.

**SHIP entry**

1. Park the actuator if it is not parked and VSYS ≥ 3.3 V. If the
   "battery empty" screen is to be shown, switch the OLED on before the park
   move, not during it ([§5.8](#58-limits)).
2. Confirm that `state/carriage` holds `valid = 1`: the park move's SETTLE wrote
   it ([§5.2](#52-state-machine)). If the carriage could not be parked, the
   record from its last SETTLE is still valid.
3. Flush settings.
4. Disconnect BLE gracefully.
5. LEDs and OLED off.
6. Write BQ25180 SHIP_RST (0x09) = 0x49. If VBUS is present the charger
   cannot remove SYS, so tell the user to unplug (check the exact
   ship-with-adapter behaviour in the BQ25180 datasheet).
7. Wake is a press of at least 2 s (WAKE2) or USB plug-in, followed by a cold
   boot of about 0.3–0.5 s, including the MCUboot image check.

### 12.3 Wake sources

| Source | Pin / event | From | Latency to response |
|---|---|---|---|
| Rotation | TMAG_INT_N SENSE low (latched W&S INT) | DIM, DESK_IDLE, SLEEP | Trigger after 0.5–4.3° of rotation, plus at most one W&S interval (10/100 ms) |
| Press | BTN_N SENSE low | All System ON states | About 5 ms (debounce) |
| Press (ship) | BQ25180 TS/MR via Q1A, ≥ 2 s hold | SHIP | 2 s + boot |
| Pick-up / shake | IMU_INT1 SENSE high (latched) | DESK_IDLE, SLEEP | ≤ 80 ms (12.5 Hz ODR) |
| USB plug | POWER USBDETECTED (VBUS ≥ 4.3 V guaranteed) | All; BQ adapter wake from SHIP/SHUTDOWN | Immediate |
| Charger status | CHG_INT_N (P1.03) SENSE low | All | Handled silently (charging indicator only) |
| NFC reader field | NFCT FIELDDETECTED | All System ON states | Tag answers the reader; no UI wake needed ([§9.7](#97-nfc-tag-emulation)) |
| BLE | Host data or connection event | DESK_IDLE | Radio timing |
| Timers | RTC1 | All | Battery sample every 60 s (10 min in SLEEP), advertising phases, 4 h TMAG re-arm |

### 12.4 Battery measurement and low-battery policy

**VSYS measurement.** VSYS_SENSE = VSYS/3.2 into AIN0; SAADC gain 1/6, 0.6 V
reference (3.6 V full scale), 12-bit with 8× oversampling, TACQ 40 µs:

* VSYS = code × 3.6/4096 × 3.2 = **code × 2.8125 mV**. For example, 3.70 V
  gives code 1316 and 4.40 V gives 1564.
* The source impedance is 687 kΩ with 100 nF (τ = 69 ms), which also filters
  the 2 kHz LED PWM ripple. Sample at most about 1 Hz; the 100 nF supplies the
  sampling charge, so the error is under 0.03 %.
* **Production one-point calibration** at 3.800 V stores `cal/vsys_gain`
  (test 8). The reference is a DMM at TP1 (VSYS at the divider), or the
  board must draw under 5 mA during calibration, since any load current
  lowers VSYS below the supply setpoint and would be stored as a permanent
  gain error (hardware/sim, VSENSE-5). That brings the ±1 % resistor and
  ±reference tolerances to about ±10 mV, **but only at 25 ± 10 °C on a fresh
  unit**: over −10…60 °C and with ageing the calibrated reading drifts by up
  to ±46 mV (hardware/sim, VSENSE-1, VSENSE-4). Every threshold below is set
  with that drift in mind.
* **On battery:** VSYS ≈ VBAT − I × 55 mΩ (BATFET). **On USB**, SYS is
  regulated at 4.4 V (SYS_REG 0x20, [§13.1](#131-register-init-table)), so
  VBAT cannot be measured; use BQ25180 CHG_STAT instead. The BQ25180 has no
  ADC.
* **Rested estimate:** VOCV ≈ Vmeas + I_est × 0.25 Ω, where I_est is the sum
  of the LED limiter estimate, OLED state, actuator state and a 3 mA base.
  Prefer samples taken after at least 1 s of light load.
* **SoC** from a rested-OCV table (typical LiPo; refine per cell):

  | VOCV (V) | 4.20 | 4.06 | 3.98 | 3.92 | 3.87 | 3.82 | 3.79 | 3.77 | 3.74 | 3.68 | 3.45 | 3.30 |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|
  | SoC (%) | 100 | 90 | 80 | 70 | 60 | 50 | 40 | 30 | 20 | 10 | 5 | 0 |

  The battery % shown to the user is rescaled so that 0 % is the 3.53 V SHIP
  threshold below.

**Low-battery policy** (rested VBAT, with 50 mV of hysteresis upward):

| VBAT | Action |
|---|---|
| ≥ 3.75 V | Normal |
| < 3.75 V | OLED C7 ≤ 08h and ≤ 30 % white area ([§7.4](#74-burn-in-mitigation-and-power-caps); hardware/sim, OLED-BST-2) |
| < 3.60 V | Warning icon; LED cap 100 mA; TMAG DEEP-LOWBAT interval in SLEEP; DFU swap refused unless on USB |
| VSYS < 3.55 V (measured idle) | Only park moves ([§5.8](#58-limits); hardware/sim, MD-2) |
| < 3.53 V | LEDs off except the red cue; quiet sounds; after 3 readings 10 s apart, SHIP entry. The BQ25180 battery-only power-up threshold VBATPOR is 3.08/3.21/3.46 V min/typ/max ([SLUSE99C](https://www.ti.com/lit/ds/symlink/bq25180.pdf)), and the calibrated reading can be up to 46 mV high away from 25 °C or after ageing, so 3.53 V (3.46 V + about 70 mV) lets every unit wake from a button press right after a low-battery ship (hardware/sim, VSENSE-1, VSENSE-4). Self-discharge in storage can still take a cell below VBATPOR, so the last screen always says "Battery empty: plug in to charge (or hold 2 s)". This is 80 mV above the 3.45 V rested cutoff of architecture.md §8.1, which costs about 2 % of capacity (estimate from the OCV table above). |
| POF event (VDD < 2.9 V) | Immediately: LEDs off, OLED off (OLED_VCC_EN low; hardware/sim, PI-4), motor brake then sleep, abort flash writes. If it persists for 100 ms, enter SHIP. |
| VBAT < 3.0 V | BQ25180 BUVLO disconnects the battery in hardware |

### 12.5 Peripheral power hygiene

* QSPI: deep power-down whenever idle (`has-dpd` + PM runtime). The W25Q128
  standby current, tens of µA, would otherwise exceed the whole sleep budget.
  The `qspi_sleep` state pulls SCK and IO0–IO3 down so the flash inputs do
  not float (hardware/sim, SLP-4); verify the floor with the PPK2 (test 22).
* SPIM3 suspended between frames is not needed, because the SPIM idle current
  is small, but suspend it in DESK_IDLE (anomaly 195; measure).
* TWIM1 suspended in sleep. The pull-ups idle high, so no current flows.
* HFXO is requested only by BLE radio events, USB, I2S (every LED frame,
  [§6.1](#61-hardware-facts-used)) and the clock source. Tracking uses
  TWIM/TIMER on HFINT.
* Before removing power from a peripheral, set every pin to it low or
  disconnected (pinctrl sleep states, [§1.3](#13-gpio-configuration)).

---

## 13. BQ25180 charger driver

[BQ25180 DS SLUSE99C](https://www.ti.com/lit/ds/symlink/bq25180.pdf); I2C
0x6A over the link (TWIM1).

### 13.1 Register init table

Register values are as decoded by the power verifier; the charge-current pair
is the corrected one.

| Order | Register (address) | Value | Setting |
|---|---|---|---|
| **1** | IC_CTRL (0x07) | **0x97** | TS_EN = 1, VLOWV 3.0 V, VRCH 100 mV, 2XTMR_EN = 1, safety timer 6 h, **watchdog disabled**. The watchdog starts at the first I2C transaction, so make this the first transaction. |
| 2 | VBAT_CTRL (0x03) | 0x46 | VBATREG = 3.5 V + 70 × 10 mV = **4.20 V** (0x41 = 4.15 V for longer cycle life) |
| 3 | ICHG_CTRL (0x04) | **0x43** | ICHG = 40 + (67 − 31) × 10 = **400 mA**; bit 7 CHG_DIS = 0 |
| 4 | CHARGECTRL0 (0x05) | 0x20 | IPRECHG = 2 × ITERM, ITERM 10 %, VINDPM 4.2 V, TREG 100 °C |
| 5 | CHARGECTRL1 (0x06) | 0x92 | BATOCP 1.5 A, BUVLO 3.0 V, CHG_STATUS INT on, ILIM INT masked, VDPM INT on |
| 6 | TMR_ILIM (0x08) | **0xCD** (or 0xC9, [§13.3](#133-input-current-strategy-on-usb)) | MR long press 20 s, MR_RESET_VIN 0, autowake 1 s, **ILIM code 101 = 500 mA** (450/475/498 mA min/typ/max) |
| 7 | SHIP_RST (0x09) | 0x09 | Long press = hardware reset, WAKE1 300 ms, WAKE2 2 s, EN_PUSH = 1 |
| 8 | SYS_REG (0x0A) | **0x20** | SYS_REG_CTRL = 001: **SYS 4.4 V** on USB (POR default 010 = 4.5 V), normal SYS mode (SLUSE99C Table 8-19). MUST be 001, or 010 at most, never 011–111 (4.6 V up to pass-through) while the LEDs may run; `bq25180.c` asserts this on every SYS_REG write. It holds the LED data margin ([§6.1](#61-hardware-facts-used)) and lowers the coast peak on VSYS (hardware/sim, LED-DATA-V3, LDO-2, MD-5) |
| 9 | TS_CONTROL (0x0B) | **0x90** | TS_HOT = 10 (50 °C), TS_COLD = 01 (3 °C), WARM 45 °C / COOL 10 °C unchanged (Table 8-20). With the 0x00 default the HOT/COLD thresholds sit exactly on the JEITA limits, and the NTC and bias tolerances let charging continue at about −2 °C and +65 °C (hardware/sim, charger_ts-1) |
| 10 | Read STAT0/STAT1/FLAG0 (0x00/0x01/0x02) | | Clears flags; record the initial state, including FLAG0 BAT_OCP_FAULT and STAT1 BUVLO_STAT for the boot checks ([§12.2](#122-entry-and-exit-procedures)) |

* **Why 400 mA with the 500 mA input code:** with ILIM at the 500 mA code
  (475 mA typical) and about 50 mA of system load, a 500 mA charge setting
  could not be delivered (DPPM). Setting 400 mA keeps the two consistent. Full
  charge takes about **2.8–3 h**.
* 0x4D/0xCE (500 mA charge with a 700 mA input) would need a Type-C 1.5 A or
  3 A source, which this hardware cannot detect, so it is not used.
* **Desired register state.** Three registers are changed deliberately at run
  time: ICHG_CTRL (0x39 thermal; CHG_DIS = 1, e.g. 0xC3, for USB suspend, the
  TS-open fault and the cold guard), TMR_ILIM (0xC9 before enumeration, 0xCD
  after) and SYS_REG (0x24 battery-only during USB suspend).
  `bq25180.c` therefore keeps a `struct bq_desired` holding the value every
  register should have *now*: the table above with the current overrides
  applied. USB (attach, configured, suspend, resume), thermal and charger-type
  events update the struct and then write the changed register; nothing writes
  the BQ25180 except through it.
* **When to write what:**
  * At boot, write the whole struct in table order (IC_CTRL first).
  * **After a detected BQ reset**, write the whole struct again (not the bare
    table, which would undo the overrides). Check for a reset on every
    VIN_PGOOD change (via CHG_INT_N), after any TWIM1 NACK at 0x6A once the
    bus recovers, and in the 60 s check below: IC_CTRL reading back other than
    0x97 means the BQ has reset (it returns to its POR default after a POR, a
    20 s hardware reset or a watchdog event).
  * Every 60 s while VBUS is present, read 0x03–0x0B and rewrite any register
    that differs **from the struct**. This keeps the 2.5 mA suspend state, the
    100 mA pre-enumeration limit and the thermal derating intact. The BQ25180
    can change SYS_MODE by itself (it ignores battery-only below BUVLO and
    returns to normal on adapter re-insertion, SLUSE99C §8.3.4); the struct
    is updated from such events rather than fighting them.
* **Thermal:**
  * If STAT1 reports TS WARM, or the nRF die temperature exceeds 45 °C, set
    ICHG to 0x39 (300 mA).
  * JEITA stays enabled, with the 3/10/45/50 °C thresholds of TS_CONTROL =
    0x90 (the B3435 NTC sits on the base-board top, so it reads board and
    pack-air temperature, not the cell skin; SPEC §8).
  * **Cold guard.** While VBUS is present, firmware MUST set CHG_DIS = 1 when
    the nRF die temperature reads below 0 °C and clear it above about 3 °C:
    below about −11 °C the TS bias drives TS/MR above VTS_ENZ, where cold
    protection is not guaranteed (hardware/sim, charger_ts-3).
  * **TS open.** Firmware MUST treat STAT0.TS_OPEN_STAT = 1 (bit 7) as a
    fault: set CHG_DIS = 1 and show "temperature sensor fault" until it
    clears. An open NTC floats TS/MR to its clamp above VTS_ENZ, which can
    disable TS monitoring rather than read cold (hardware/sim,
    charger_ts-v1).
  * TREG at 100 °C throttles by itself.

### 13.2 Status, interrupts and faults

* CHG_INT_N delivers 128 µs active-low pulses. On the SENSE pin the nRF52840
  LATCH register should capture them even if the pulse ends before the ISR
  runs (TVP).
  * While VBUS is present, also poll STAT0 at 1 Hz as a backstop; that costs
    nothing on USB power.
  * Optionally switch CHG_INT_N to a GPIOTE IN channel while VBUS is present,
    since the extra 15 µA does not matter then.
* Decode STAT0: TS_OPEN_STAT, CHG_STAT (not charging / CC / CV / done),
  VIN_PGOOD, and the DPPM, VINDPM, ILIM and thermal-regulation activity
  bits. Decode STAT1: VIN_OVP, BUVLO, TS state, safety-timer fault and the
  WAKE flags (ignored). Decode FLAG0, including BAT_OCP_FAULT (bit 0).
  Publish them on `power_evt`. Exact bit positions per the datasheet register
  map (SLUSE99C Tables 8-9 to 8-11).
* **Faults:**

  | Fault | Response |
  |---|---|
  | VIN_OVP | A flag within about 30 ms of plug-in is benign (the legacy-cable hot-plug overshoot of most plug-ins): do not report it (hardware/sim, V-3). Otherwise "bad charger" icon. Supported VBUS is 4.5–5.25 V; a source near 5.5 V can trip OVP and pause charging, and the unit then runs from the battery (NF-4) |
  | TS cold/hot | "Too cold/hot to charge", except while BTN_N is low and for 5 ms after ([§8.2](#82-press-handling-pressc); hardware/sim, charger_ts-v2) |
  | TS open (STAT0.TS_OPEN_STAT = 1) | CHG_DIS = 1, "temperature sensor fault" ([§13.1](#131-register-init-table) Thermal) |
  | BAT_OCP_FAULT | With LED_PWR_EN or OLED_VCC_EN recorded high: that load stays off ([§15](#15-fault-handling)) |
  | Safety-timer fault | Report; cleared by re-plugging |
  | Charge done | Ring shows green briefly when the user interacts |

* **NTC above about 68 °C** reads as a press on TS/MR (≤ 90 mV threshold), which
  could cause ship wakes or 20 s reset loops in a hot car (verifier). That is
  outside the cell's rating; firmware logs the reset reason, and a hot-NTC
  state is visible as TS HOT in STAT1.

### 13.3 Input-current strategy on USB

1. **VBUS detected** (POWER USBDETECTED or VIN_PGOOD): write TMR_ILIM = 0xC9
   (100 mA) until the USB state is known. With a dead battery the system boots
   from VBUS at the BQ's default limit and then applies this. While the limit
   is 100 mA, apply the load cap of [§6.3](#63-power-limiter) (LEDs ≤ 20 mA,
   no actuator moves, homing deferred): a battery below BUVLO cannot
   supplement SYS (SLUSE99C §8.3.3). OLED_VCC_EN MUST stay low unless the
   battery can supplement (no BUVLO_STAT and VBAT ≥ about 3.15 V), and the
   LEDs show the charging cue instead (hardware/sim, NEW-1, OLED-V1;
   [§7.2](#72-init-sequence-and-power-sequencing)). If the pack is absent,
   below BUVLO or in precharge, the no-supplement profile of §6.3 applies
   (total ≤ 70 mA; hardware/sim, PI-4).
2. **USB configured** by a host (bMaxPower 500 mA granted): TMR_ILIM = 0xCD.
3. **No bus reset or SOF within 2 s** (a dedicated charger shorts D+/D−):
   assume a charger and set TMR_ILIM = 0xCD.
   * At 500 mA without supplement: no actuator moves, LEDs ≤ 100 mA
     peak-limited, OLED C7 ≤ 08h, total ≤ 400 mA (hardware/sim, PI-4).
   * With a pack: the LED instantaneous budget uses the 3.48 V row until
     CHG_STAT reports CV or done, or the total on-USB load stays ≤ 0.40 A
     ([§6.3](#63-power-limiter); hardware/sim, NF-1).
4. **USB suspend:** ICHG_CTRL = 0xC3 (CHG_DIS = 1) and SYS_REG SYS_MODE =
   battery-only (0x24: SYS_MODE = 01 in bits 3:2, SLUSE99C Table 8-19) to
   stay within 2.5 mA ([§10](#10-usb-composite-device); hardware/sim, V-2).
   The alternative is TMR_ILIM = 0xC8 (50 mA). On resume, restore 0x43 and
   0x20. The BQ25180 ignores SYS_MODE = 01 while VBAT < BUVLO and returns to
   00 on adapter re-insertion (§8.3.4).
5. **VBUS removed:** nothing to do; the BQ switches to battery.

### 13.4 Ship and shutdown

* **Ship:** SHIP_RST = **0x49** (EN_RST_SHIP = 10). It wakes on a press of
  ≥ 2 s or on adapter insertion. About 3.2 µA.
* **Shutdown:** SHIP_RST = **0x29** (EN_RST_SHIP = 01). It wakes on adapter
  insertion only. About 15 nA. The last production step writes this, so units
  ship at about 3 µA (pack PCM) and wake on first plug-in.
* The hardware reset by a 20 s press stays enabled as the user-reachable
  "unbrick" path.

---

## 14. LIS2DW12 accelerometer

I2C 0x19 on TWIM1. INT1 is push-pull, active high, latched, on P1.12; INT2 is
on P0.30. The application drives it directly, a driver of about 200 lines
using `i2c_dt_spec` from the `imu` node, because the needs are narrow: wake
configuration, 6D, double-tap and FIFO bursts. Check WHO_AM_I (0x0F) = 0x44 at
init. Register map per LIS2DW12 DS DocID029682 and
[AN5038](https://www.st.com/resource/en/application_note/an5038-lis2dw12-alwayson-3d-accelerometer-stmicroelectronics.pdf).
**Verify each bit field against the datasheet before use.**

### 14.1 Wake configuration (used in DESK_IDLE and SLEEP)

| Register (address) | Value | Meaning |
|---|---|---|
| CTRL2 (0x21) | 0x0C | BDU = 1, IF_ADD_INC = 1 (CS is tied high, so its pull-up does not matter) |
| CTRL1 (0x20) | **0x20** | ODR 12.5 Hz, low-power mode, LP_MODE1 (12-bit). About 1 µA at 1.8 V, somewhat more at 3.3 V. |
| CTRL6 (0x25) | 0x00 | Bandwidth ODR/2, ±2 g, low-noise off |
| CTRL3 (0x22) | 0x10 | LIR = 1 (latched), push-pull, active high |
| WAKE_UP_DUR (0x35) | 0x00 | WAKE_DUR 0, SLEEP_DUR 0 |
| WAKE_UP_THS (0x34) | **0x03** | WK_THS = 3 × FS/64 = 3 × 31.25 mg = **94 mg** (research range 2–4 LSB). Wake-up uses the high-pass (slope) filter, so it does not depend on orientation. |
| CTRL4_INT1_PAD_CTRL (0x23) | 0x20 | INT1_WU |
| CTRL7 (0x3F) | 0x20 | INTERRUPTS_ENABLE |
| ALL_INT_SRC (0x3B) | read | Clear the latch before arming |

On wake, read WAKE_UP_SRC (0x38): WU_IA and the X/Y/Z_WU axis bits. That read
clears the latch and the SENSE line.

### 14.2 Awake configuration (optional features)

| Feature | Configuration | Cost |
|---|---|---|
| 6D orientation (face down = mute/sleep) | Keep 12.5–50 Hz LP. Set 6D_THS in TAP_THS_X (0x30), CTRL4 INT1_6D, CTRL7 LPASS_ON6D. | About 1–3 µA |
| Double tap on the top cover | CTRL1 = 0x74 (400 Hz, high-performance); TAP_THS_X/Y/Z and INT_DUR per AN5038 as tuned starting values; WAKE_UP_THS bit 7 = 1 (single/double); CTRL4 INT1_TAP. Tap through the floating assembly is mechanically filtered (TVP). | About 90 µA, ACTIVE only |
| Drop / free fall | FREE_FALL (0x36), CTRL4 INT1_FF; log events | Small |

### 14.3 Balancing assistant (optional)

* High-performance mode at 400–1600 Hz with the FIFO (32 levels, watermark on
  INT2; FIFO_CTRL 0x2E).
* Timestamp each FIFO batch and interpolate the ring angle from a 1 s history
  of `motion_state`.
* I/Q lock-in: demodulate a_x and a_y with cos/sin of the ring angle, using
  about 1 Hz of bandwidth. The imbalance vector is proportional to
  (I, Q)/ω²; show the heavy-spot angle on the LEDs and OLED.
* The margin is large on paper: about 27 mg of 1×/rev vibration if the puck is
  free, against about 0.1 mg of lock-in noise. On a desk the coupling is
  smaller (TVP).

---

## 15. Fault handling

| Fault | Detection | Response | User-visible | Log code |
|---|---|---|---|---|
| TMAG CRC errors, duplicates or lost conversions | Per frame: CRC, SET_COUNT gap computed **modulo 8** (a 7 → 0 wrap is normal), batch timestamps for gaps ≥ 8 ([§4.5](#45-per-sample-processing)) | Coast; above 1 % over 1 s, re-init | None (or "encoder" if persistent) | E_ENC_CRC |
| TMAG NACK / bus stuck | TWIM ERROR | Stop chain, bus recover, re-init, 3 retries → encoder fault | "Rotation sensor fault"; HID rotation off | E_ENC_BUS |
| TMAG POR/DIAG bit | CONV_STATUS bit 4 (POR, R/W1C) or bit 1 (DIAG_STATUS) in a streamed frame or the wake read. POR is cleared at every init and arm, so POR = 1 means the TMAG reset since then. | Full re-init **including the POR clear and read-back** ([§4.2](#42-tmag5273-tracking-configuration)); recalibration not needed. POR still 1 after the clear (retry once) → encoder fault | None | E_ENC_POR |
| Loss of lock | Tracker supervision | Coast, re-acquire from atan2; mark position relative | None | E_ENC_LOCK |
| TMAG stuck in standby after W&S (0.45 mA) | 50 ms software watchdog after wake; 4 h periodic re-arm | Re-arm | None | E_ENC_ARM |
| Magnet missing or reversed | Calibration self-test | Report pocket index; calibration rejected | "Magnet k fault" (factory) | E_MAG_k |
| Homing failure | Any failed homing phase ([§5.4](#54-homing-with-the-drv5032)): no HOME release within the back-off limit; no released → asserted edge within 375 + 40 approach steps; or HOME not asserted after the final stall at the park stop | 3 retries at 313 PPS, then FAULT, driver asleep | "Detent fault"; mode fixed | E_DET_HOME |
| Lost steps | Primary: HOME not asserted after the re-reference stall that ends every move to FREE. Secondary: a HOME edge seen outside its direction- and speed-dependent window ([§5.4](#54-homing-with-the-drv5032) rule 2) | Primary: full homing. Secondary: re-reference at the next move to FREE; re-home at rest if the error is above 40 steps or repeats | None | E_DET_STEPS |
| Move timeout | Per-move watchdog | Stop, sleep driver, FAULT after 2 | "Detent fault" | E_DET_TMO |
| Actuator move at low battery | VSYS check | Refuse; park only | "Battery low" | W_DET_LOWBAT |
| BQ25180 not responding | TWIM1 NACK at 0x6A | Retry every 5 s; assume no charger info; LED limiter stays on | "Charger comm" (factory) | E_CHG_I2C |
| BQ register differs from the desired state, or BQ reset | 60 s verify on USB against `struct bq_desired`; IC_CTRL ≠ 0x97 marks a reset ([§13.1](#131-register-init-table)) | Rewrite the differing registers from the struct (whole struct after a reset); never rewrite the bare init table | None | W_CHG_RST |
| Charger faults (OVP, TS, TS open, timer) | STAT0/STAT1 | See [§13.2](#132-status-interrupts-and-faults); TS open → CHG_DIS = 1 | Icon; "Temperature sensor fault" | E_CHG_* |
| Battery critical | [§12.4](#124-battery-measurement-and-low-battery-policy) | Derate, then SHIP | Low-battery screen | W_BAT_* |
| Brown-out / POF | POFWARN at 2.9 V | LEDs, OLED and motor off (brake, then sleep), abort flash writes (hardware/sim, PI-4) | None | E_POF |
| VLED fault (shorted LED or VLED bridge; U2 has no current limit) | At boot: RESETREAS reads 0 (power-on or brown-out reset), or FLAG0 BAT_OCP_FAULT = 1, with LED_PWR_EN recorded high in the retained rail-state record | Keep the LEDs off for the session and log a VLED fault (hardware/sim, NEW-5). If a brown-out, POF or BATOCP follows LED_PWR_EN within about 50 ms twice, latch VLED off in `state/vled_fault` and show a service fault (hardware/sim, NF-3) | "Service: LED ring fault" (latched case) | E_VLED |
| OLED rail fault | Same boot check with OLED_VCC_EN recorded high | Leave the OLED off for the session; show an error on the LEDs (hardware/sim, OLED-V3) | LED error pattern | E_OLED_PWR |
| OLED SPI corruption | Not detectable | Full redraw on every wake and every 5 s while static | None | — |
| LED overcurrent | Model only (no sensing) | Average and instantaneous limiter always on ([§6.3](#63-power-limiter)); 12 mA/channel assumed until the variant is set | None | — |
| QSPI failure | JEDEC ID at boot, littlefs mount | Re-format the assets partition and request re-sync from the app; DFU disabled if the ID is wrong | "Storage" (factory) | E_QSPI |
| Settings corruption | NVS mount or CRC per record | Defaults; calibration restored from `factory_backup` | "Settings reset" | W_CFG |
| Thread hang | Task watchdog (4 s, per-thread check-in) | Reset; crash info saved to retained RAM and then `crash_log` | None | E_WDT |
| HardFault / assert | Fault handler | Coredump to `crash_log`, reset | None | E_FAULT |
| Boot loop | 3 crashes within 10 s of boot (retained counter) | **Safe mode:** LEDs off, actuator disabled, BLE SMP + USB CDC only | Safe-mode screen | E_SAFE |
| Pairing failure / bond table full | BT callbacks | Show the message; oldest phone bond is evicted on ID 0 only | Message | W_BT_* |

The crash log is readable over SMP (custom group) and the shell.

The rail-state record is written to retained RAM (CRC-16) just before
LED_PWR_EN or OLED_VCC_EN goes high and again after it goes low. A
power-on or brown-out reset may leave it corrupt; if its CRC fails, the
boot check falls back to FLAG0 BAT_OCP_FAULT alone (*TVP:* whether the record
survives a BATOCP collapse on the real board).

---

## 16. Bring-up and manufacturing tests

**Tools:** PPK2 (current), J-Link or nRF52840-DK as programmer on TC2030, a
USB-C cable, a bench supply on BAT, a scope, an optional Hall probe, and the
nRF Connect app.

The `factory` build exposes the `hw` shell on `cdc_acm_shell`:

| Command | Function |
|---|---|
| `hw i2c scan` | Bus scan |
| `hw tmag dump\|stream\|arm` | TMAG registers, live stream, arm W&S |
| `hw imu id\|selftest` | LIS2DW12 checks |
| `hw bq dump\|init\|ship` | Charger registers, init, ship mode |
| `hw adc vsys` | VSYS reading |
| `hw oled bars\|white\|sleep` | Display patterns and sleep |
| `hw led walk\|all <rgb>` | LED patterns |
| `hw buzz <hz> <ms>` | Piezo tone |
| `hw mot home\|move <steps>\|sweep` | Actuator |
| `hw cal enc\|strength` | Calibrations |
| `hw pm <state>` | Force a power state |
| `hw fdata write …` | Factory data |

A pytest + pyserial script runs the sequence below and prints pass/fail.

| # | Test | Method | Pass criteria |
|---|---|---|---|
| 1 | Power rails (before the module is programmed) | USB on the base board; measure VSYS, +3V3; current with an erased nRF | VSYS 4.5 V ±3 % on USB (BQ25180 POR default; 4.4 V after the [§13.1](#131-register-init-table) init); +3V3 3.3 V ±3 %; no excess current |
| 2 | SWD + silicon | `nrfutil device` read FICR (part, variant, revision), APPROTECT state | Expected part; note Rev 2 or 3 |
| 3 | UICR | Firmware applies NRESET only (NFCPINS left in NFC mode); read UICR.NFCPINS; reset via TC2030 pin 3 | Pin reset works; NFCPINS in NFC mode; CHG_INT_N (P1.03) reads high (R55 10 kΩ pull-up) |
| 4 | Clocks | HFXO start; LFXO start time; count LFXO against HFXO for 1 s | LFXO within ±50 ppm; start < 1 s |
| 5 | QSPI | JEDEC ID; SR2 QE bit; erase/write/read one sector; deep power-down current | EF 40 18; data intact; DPD verified in test 22 |
| 6 | System I2C | Scan TWIM1 at 250 kHz; LIS2DW12 WHO_AM_I; BQ25180 register read | 0x19 (0x44) and 0x6A present |
| 7 | BQ25180 | Write [§13.1](#131-register-init-table), read back; with USB check CHG_STAT and VSYS; with the bench supply on BAT check VIN_PGOOD toggling | All registers match (SYS_REG 0x20, TS_CONTROL 0x90); VSYS 4.4 V ±2 % on USB; TS_OPEN_STAT = 0; charge status sane |
| 8 | VSYS ADC calibration | Battery emulator at 3.800 V, no USB; reference from a DMM at TP1, or LEDs, OLED and motor off with the board under 5 mA (hardware/sim, VSENSE-5) | Raw gain within ±5.5 % (hardware/sim, VSENSE-2); store `cal/vsys_gain`; residual ≤ 10 mV |
| 9 | Ship mode | Write 0x49, unplug, measure; hold the press 2 s | Battery current ≤ 4.5 µA (board side); wakes on the 2 s press |
| 10 | Press | BTN_N press/release counts | 10/10 presses detected, no bounce |
| 11 | OLED | Power sequence, colour bars, full white; measure +13V_OLED at C39 (the net has no test pad); sleep current | VCC 12.7–13.3 V, the production screen for the FB-bias error of the 499 k/52.3 k divider (bring-up B-9.9a; hardware/sim, OLED-BST-1); correct colours and orientation; no garbage on first light |
| 12 | LEDs | VLED ramp and fall at TP3 (scope); walk R/G/B over 48 LEDs; all red at 50 % → current | VLED tON ≤ 5 ms (about 4 ms expected) and fall to 10 % ≤ 30 ms (about 24 ms expected, 26.6 ms worst case; record tFALL, hardware/sim NEW-4; [§6.4](#64-rail-sequencing)); all 48 in order (D101 at θ = 0°, CCW); about 48 × 2.5 mA (C) or 6 mA (B) ±15 % → sets the factory LED variant |
| 13 | Piezo | 4 kHz tone | Audible / mic SPL ≥ spec (optional) |
| 14 | IMU | ST self-test (CTRL3 ST bits); flat-orientation Z ≈ +1 g; tap → INT1 | Self-test within limits; INT1 fires |
| 15 | TMAG basic | ID and manufacturer registers; 6-byte CRC frames streaming with TWIM0 at FREQUENCY = 0x06200000; measured sample rate | CRC OK; rate 2.8–3.4 kSPS (record it); frame length confirmed 6 or 8 |
| 16 | Magnet track | Spin by hand or with a jig motor at about 3 rev/s | 24 electrical cycles/rev; per-pole amplitude within ±15 %; Bt/Bz amplitude 8–25 mT; no reversed pole |
| 17 | Encoder calibration | Run [§4.6](#46-calibration) (a)–(e) | Ellipse residual < 2 %; post-LUT error < 0.2° mech |
| 18 | W&S wake | Arm 10 ms, rotate slowly; measure armed current with the PPK2 | Wake within 5° mech; W&S 10 ms ≤ 25 µA (TMAG share) |
| 19 | Actuator | Home from the click end and from the park stop; learn the HOME edges (5 sweeps each way at 80 PPS, [§5.4](#54-homing-with-the-drv5032)); go to click (x = 0) and read HOME; pluck test f_n → T1; sweep 3 strength points; 20 CLICK ↔ FREE cycles | Both homings complete; HOME asserted after every park stall; **HOME released at x = 0** (else reject or apply the §18 item 2 hardware fix); s_ast,L in 180–240 and s_rel,L in 190–260 steps with a spread ≤ 10; T1(full click) within 13–20 mN·m; no E_DET_STEPS over 20 cycles |
| 20 | Free-spin quality | 50 spin-downs from about 5 rev/s in FREE; histogram of rest angles; spin-down time from 10 rev/s | No preferred rest angle (χ² test over 24 bins). Spin-down from 10 rev/s, median of 10 runs: **≥ 45 s (target ≥ 60 s)**, the verified mechanical acceptance of architecture.md R3 and bringup.md B-13. Record the value and seed the FREE predictor prior with it. SPEC's 2.5–3 N preload is predicted to give only 20–50 s ([§4.7](#47-motion-events-velocity-and-spin-down-prediction)), so a failure here is a mechanical finding (preload, architecture.md D3), not a firmware or test-limit error. |
| 21 | BLE RF and NFC | RSSI at 1 m with nRF Connect; radio test / DTM carrier and TX power; RX sensitivity with the OLED animating vs off. NFC: a phone reads the test NDEF record through the top cover ([§9.7](#97-nfc-tag-emulation)) | RSSI ≥ −65 dBm at 1 m (TVP target); ≤ 3 dB difference animating vs off; tag read reliably (record the range; retune C16/C17 if it is short, TVP) |
| 22 | Sleep current | PPK2 on BAT at room temperature: SLEEP, DESK_IDLE (no host), SHIP | SLEEP ≤ 60 µA, and investigate anything above 45 µA (typical 38 µA at 25 °C; the OLED line alone is 17.6 µA typical and up to about 46 µA at datasheet maxima, [§7.2](#72-init-sequence-and-power-sequencing)). DESK_IDLE (no host, app advertising off): record; expect about 55 µA (the 62 µA budget minus the connection's 7 µA), investigate above 65 µA. SHIP ≤ 8 µA including PCM (board ≤ 4.5 µA) |
| 23 | USB | Enumeration, also from a 4.5 V supply through a 1 m cable (R12 4.7 Ω leaves 28 mV over the nRF's 4.35 V VBUS minimum, hardware/sim USB-1); HID test (Windows Wheel settings, Linux `evtest`); SMP echo on CDC | Enumerates as HID + 2 CDC at both supplies; dial events in the right direction |
| 24 | DFU | Upload over BLE and USB, test boot, confirm; forced revert test; serial recovery (press while plugging) | Swap OK; revert OK; recovery entered |
| 25 | Final | Write factory data (serial, LED variant, shoe_x_max, calibration backup); clear logs; BQ shutdown (0x29) | Unit wakes only on USB |

---

## 17. Implementation plan and host-side tests

| Milestone | Content | Exit criterion |
|---|---|---|
| M0 Bring-up | Board DTS, pinctrl, `hw` shell, stock TMAG driver (`bringup.overlay`), I2C/ADC/QSPI/OLED/LED smoke tests | Tests 1–15 pass on the first board |
| M1 Encoder | PPI/DMA chain, unwrap, tracker, calibration, W&S arm/wake | Tests 15–18; < 0.1 % CRC errors with BLE active |
| M2 Detent | nrfx_pwm stepper, homing, LUT, modes, blanking rules | Test 19; 1000-cycle endurance with no faults |
| M3 Output | LED renderer and limiter; OLED wrapper, LVGL, burn-in policy; piezo | 120 fps LEDs and 30 fps OLED with BLE connected |
| M4 BLE HID | bt_hids, report map, Swift Pair, slots, pairing UX | Windows Dial menu works; macOS scroll; Android volume |
| M5 USB + DFU | Composite USB, MCUboot with QSPI, SMP both ways, serial recovery | Test 24 |
| M6 Power | State machine, BQ25180 driver, battery policy, sleep entry/exit | Tests 9 and 22 currents met |
| M7 Game | Predictor, game service, app (Web Bluetooth first); NFC tag emulation and `nfc_tag` | Prediction error vs actual logged over 100 spins; a phone reads an NDEF record set from the app |
| M8 Production | Factory sequencer, factory data, release build, APPROTECT policy | Full test table on 3 units |

**Host-side unit tests** (`tests/`, ztest on `native_sim`, run in CI):

* unwrap + PLL on synthetic (x, z) streams: constant speed in both
  directions, flick acceleration (check the 26° el phase error and the
  ≈ 1.5 rev/s velocity lag of [§4.5](#45-per-sample-processing)), dropped
  frames, noise;
* the angle conversion for all four quadrants, including **negative atan2f()
  results** (−π < angle < 0 must map to 32768–65535), and the `wrap16()` /
  `floor_div256()` helpers at their boundaries;
* frame validation: SET_COUNT 7 → 0 wrap (no error), duplicates, gaps of 2–7,
  aliased gaps of 8 or more caught by the timestamp cross-check, POR = 1 →
  re-init;
* ellipse fit and harmonic LUT recovery from synthetic distortion;
* the TMAG CRC against datasheet example frames;
* the homing procedure and edge windows against a simulated carriage (HOME
  with the DRV5032 lag and hysteresis, park and click stops, a stall zone);
* the BQ25180 desired-state struct: USB suspend, pre-enumeration and thermal
  overrides survive the 60 s verify and a simulated BQ reset;
* the W&S threshold rule, i.e. the [§4.8](#48-wake-on-rotation-wake-upsleep)
  simulation as a test;
* predictor RLS on simulated spin-downs, with the analytic t_rem/Δθ_rem;
* the LED limiter (token bucket, derating, the instantaneous lit-channel
  budget with its VBAT rows, actuator offset and USB rule);
* the boot rail checks (reset reason × retained rail-state record × FLAG0
  BAT_OCP_FAULT, the VLED latch) and the OLED_VCC_EN rules at ILIM 100 mA;
* HID report packing (int15 dial, sign, clamping, remainder carry);
* BQ25180 register encoders (ICHG and ILIM codes) and the SYS_REG assert
  (only SYS_REG_CTRL 001 or 010 accepted);
* strength LUT inversion;
* settings schema migration.

---

## 18. Open items and to-verify list

**Problems found in SPEC or in the sibling documents that affect firmware**
(reported; SPEC stays the reference, and the sheets and the netlist win where
they disagree with it). Items 1, 6 (first part) and 9 are resolved; they stay
here, marked, so the history is traceable.

1. **TPS22917 CT reference. Resolved.**
   * The TPS22917 datasheet says to connect CT to **VIN**. The `main_power`
     sheet now has C7 = 1 nF from CT to VIN (VSYS), QOD through R4 = 68 Ω
     to VLED and R3 = 100 kΩ as the ON pull-down, and SPEC §5.1 says the
     same. SPEC's "≈ 4 ms rise" is the turn-on time (tON = 3.8 µs/pF at
     3.6 V); the 10–90 % rise is about 1.6 ms (SLVSDW8B §7.6). R4 went from
     100 Ω to 68 Ω so the VLED discharge (≤ 26.6 ms worst case) fits the
     firmware's 30 ms allowance (hardware/sim, LSW-2).
   * SPEC now states that the TPS22918 (CT to GND) is *not* a drop-in, and
     §4 labels P1.04 "TPS22917 ON".
   * The OLED boost-input switch U21 has the same CT wiring (C37 = 1 nF CT to
     VIN), with its QOD tied to OLED_VIN (hardware/sim, SLP-1, LSW-1).
   * Effect on firmware: the 10 ms power-on waits in [§6.4](#64-rail-sequencing)
     and [§7.2](#72-init-sequence-and-power-sequencing) cover the ≈ 4 ms tON
     with margin (LED-DATA-V4, OLED-V2); test 12 checks the VLED ramp.
2. **DRV5032 depth.** With the sensor on the top side, the die sits about
   2.4–2.8 mm above the detent-magnet face (the research recommended
   3.0–3.5 mm). My simulation gives |Bz| = 1.0–1.4 mT at full click, against
   BOP min 1.5 mT, so some units may assert HOME at click. Firmware relies on
   the park stall and screens such units at test 19
   ([§5.4](#54-homing-with-the-drv5032)). Hardware options, from the
   [DRV5032 DS SLVSDC7H](https://www.ti.com/lit/ds/symlink/drv5032.pdf)
   Tables 4-1, 6.5 and 6.6:
   * **FB and FC give no margin.** They have the FA's ±1.5/±3/±4.8 mT BOP and
     ±0.5/±1.5/±3 mT BRP. FB is the 5 Hz version (tS up to 286 ms, worse
     edge lag) and FC is the open-drain version.
   * **DRV5032DU** (SOT-23, push-pull, 20 Hz, same VCC/OUT/GND pin order) is
     **unipolar**: its SOT-23 output responds only to positive B (flux from
     the package bottom to its top), BOP 1.2/2.5/3.9 mT. The return flux at
     the click end is negative (−1.0 to −1.4 mT), so a DU ignores it
     completely, with no pull-up and no extra current. It needs one assembly
     rule: the detent magnet's **N pole faces up**, toward the main board. A
     reversed magnet makes homing fail at test 19. LCSC stock not checked.
   * **DRV5032AJ** (±4/±7/±9.5 mT BOP, ±3/±5.6/±7.5 mT BRP, 20 Hz) clears
     the click field with margin but is **open-drain**: HOME_N then needs a
     pull-up that SPEC does not have, and the output sits low for the whole of
     FREE mode. Use ≥ 1 MΩ to +3V3 (3.3 µA continuous in FREE; add it to the
     budget), never the nRF internal pull-up (about 13 kΩ, about 250 µA). The
     edges move about 0.5 mm closer to park; re-learn them at test 19.
   * **DRV5032ZE is unsafe:** BOP 33–63 mT against only 52.6 mT at park for a
     2.8 mm die height, so some units would never assert.
   * Or keep the FA and raise its die to the researched 3.0–3.5 mm with a
     0.5–1 mm spacer or interposer (32.9 mT at park, −0.47 mT at click at
     3.5 mm). Check the clearance to the top cover above r = 21.5 mm,
     θ = 90° (TVP).
3. **Encoder amplitude.**
   * SPEC's 48 × Ø2×2 track gives only about 13/16 mT (Bt/Bz) at the nominal
     3.1 mm element gap, and 10–22 mT over tolerance.
   * Tracking accuracy is fine, but the A2's 1.04 mT threshold LSB makes
     W&S wake coarse. Δ must be 2 LSB, because 3 LSB fails at the large-gap
     corner.
   * A TMAG5273**A1** (±40 mT, about 0.31 mT/LSB) would match better, but it
     has no JLC stock.
4. **No index magnet.** The absolute ring angle is known only modulo 15° after
   a DEEP wake. That is fine for the virtual wheel, but the per-pole LUT
   depends on the unproven fingerprint lock.
5. **No spare fast GPIO.** If the nRF I2S cannot run with SDOUT alone, only
   P0.04 is available for SCK and there is no fast pin for LRCK. Fallback is
   SPIM2 (`ws2812-spi`) on the same pin. SPIM2 is also the OLED fallback
   ([§7.1](#71-spi-link-and-the-spim3-errata)), so it can rescue only one of
   the two.
6. **Sibling documents.**
   * **Resolved:** docs/architecture.md §6.6 used to say "LVGL on SPIM2".
     Its §6.3, §6.6, decision D6 and risk R19 now agree with SPEC §4 and
     with this document: SPIM3 at 16 MHz with the anomaly 198 and 195
     workarounds, SPIM2 at 8 MHz on the same pins as a devicetree-only
     fallback.
   * architecture.md §2 states 150 Radial Controller units per detent, while
     the MCU research recommends 100 (the Windows default is unverified).
     Firmware makes it a setting, default 100, pending a Windows test.
7. **OLED sleep leakage (accepted for rev A).** About 5 µA leaks through the
   panel's VCI→VCC ESD path into the 499 k/52.3 k divider, 3.3 µA flows in the
   RES# pull-down, and about 5.4 µA of D21 reverse leakage (about 30 µA at
   60 °C) flows through U21's QOD. The OLED line, about 17.6 µA, is about
   46 % of the 38 µA sleep floor ([§12.1](#121-states)). Rev-B options, not
   done: a low-IR rectifier for D21, or the TPS61040 EN on its own GPIO with a
   ≤ 400 kΩ pull-down and U21's QOD open (simulated 32.2 µA total; EN must not
   rise before VIN) (hardware/sim, sleep budget). Further options are listed in
   docs/architecture.md §8.3.
8. **CHG_INT_N** delivers 128 µs pulses into a SENSE pin. Capture relies on
   the nRF52840 LATCH register (TVP); polling while on USB is the backstop.
9. **SPEC behind the sheets. Resolved** (reported as architecture.md §13
   items 12 and 13). SPEC now matches the sheets and the netlist:
   * SPEC §3 and §5.3 describe the OLED boost-input switch as U21 TPS22917
     (VIN = VSYS with C41 10 µF, ON = OLED_VCC_EN with R25 100 kΩ pull-down,
     C37 1 nF from CT to VIN, QOD tied to VOUT = OLED_VIN), as on the
     `display` sheet. Its always-on reverse-current blocking
     (IIN,RCB ≤ 1 µA) keeps OLED_VIN from back-feeding VSYS
     ([§3.1](#31-board-dts-draft), [§7.2](#72-init-sequence-and-power-sequencing)).
   * SPEC §4 and §5.5 give R57/R58 = 470 Ω per piezo side plus the R59 1 MΩ
     bleed, as on the `sensors` sheet ([§8.1](#81-piezo); hardware/sim, PB-1).
10. **Actuator thrust (still open; architecture.md risk R4).** The verified
    worst-case load of 0.8–1.15 N exceeds the 8 mm VSM08102's thrust at any
    battery VSYS (0.93 N best case). Select the 10 mm motor (≥ 1.2 N) or cut
    the preloads to ≤ 0.5 N (hardware/sim, MD-4). Firmware cannot close the
    gap: the 313 PPS homing retries, the 3.55 V move threshold and the
    temperature-compensated duty ([§5.3](#53-stepping-profile)) only keep the
    rated current.
11. **SPICE expected failures that depend on this document.** The suite keeps
    strict xfails for findings that only firmware rules answer: LSW-3 (DIN
    high with VLED off, [§6.4](#64-rail-sequencing)) and NEW-1 (dead battery
    on USB at 100 mA, [§7.2](#72-init-sequence-and-power-sequencing),
    [§13.3](#133-input-current-strategy-on-usb)). The §1.3 GPIO-table drift
    (SLP-V1: CHG_INT_N on P1.03, NFC1/NFC2 on P0.09/P0.10) is fixed in this
    revision, so `test_gpio_sleep_states_from_firmware_doc` should now pass.

**To verify on prototype or against documentation**

* The TMAG XZX 1-byte frame contents (6 vs 8 bytes); the real sample rate;
  the W&S current at 10 ms and 100 ms. (The CONV_STATUS fields are now taken
  from DS Table 8-27, [§4.2](#42-tmag5273-tracking-configuration).)
* ArrayList RXD.PTR behaviour and ISR latency with BLE active (guard frames).
* Zephyr binding property names: `ti,tmag5273`, `st,lis2dw12`, `ti,bq25180`,
  `zephyr,hid-device`, `zephyr,mipi-dbi-spi write-only`; the retention
  bindings (`zephyr,retained-ram`, `zephyr,retention` with `prefix` and
  `checksum`) and MCUboot's `CONFIG_BOOT_SERIAL_BOOT_MODE`; plus the Kconfig
  names marked *(check name)*. The `solomon,ssd1351` properties (all ten
  required, including `current-att`) and the string form of `mipi-mode` were
  checked against Zephyr main in 2026-10.
* Whether `PINCTRL_DT_DEFINE` works on disabled `&i2c0`/`&pwm0` nodes.
* I2S running with SDOUT only; WS2812C V6 timing on the scope; LED per-IC
  current (0.2 mA).
* The U2 (VLED) and U21 (OLED_VIN) turn-on ramps (tON about 4 ms with
  1 nF CT) and the VLED QOD fall (about 24 ms nominal, ≤ 26.6 ms worst case;
  the datasheet tFALL row implies an internal QOD of about 170 Ω, NEW-4),
  against the 10 ms and 30 ms waits of [§3.1](#31-board-dts-draft) and
  [§6.4](#64-rail-sequencing). U21's temperature and the VSYS sag at the
  first OLED enable (≈ 0.3 A for ~2 ms, LSW-4); FB with the OLED off
  (0.26–0.29 V against the TPS61040's 0.3 V abs max, LSW-1).
* LED PWM phase alignment of the summed ring current after power-up, which
  sets whether the instantaneous budget of [§6.3](#63-power-limiter) can be
  relaxed (PI-2).
* I2C with the errata-219 settings: tLOW at U30 pin 1 and U31 pin 1; SCL rise
  time at J3 (above 250 ns, run TWIM1 at 100 kHz); SCL/SDA ringing at J3
  (hardware/sim, NF-1, PB-2, NF-3).
* NFC: read range through the top cover and the C16/C17 retune; the NCS NFC
  Kconfig and API names; whether T2T and T4T link into one image; which
  TIMER the nrfx NFCT driver claims ([§9.7](#97-nfc-tag-emulation)).
* Whether the retained rail-state record survives a BATOCP or brown-out
  collapse ([§15](#15-fault-handling)).
* The RT9080's ground current at the ≈ 20 µA sleep load (LDO-6; the TPS7A0233
  is the alternate).
* Piezo sound level with the 470 Ω series resistors.
* The SSD1351 VCC-to-AFh delay (vendor 200 ms); the A0h remap for the actual
  mounting; SPI edge rates (tR/tF ≤ 15 ns); the anomaly-198 carve-out with
  Partition Manager; SPIM3 sleep current (anomaly 195).
* The W25Q128JV quad-enable requirement (`S2B1v5` vs factory QE = 1).
* MCUboot size with USB CDC serial recovery and QSPI (expected about 64 KB);
  swap duration.
* The Windows RotationResolutionInDegrees default (100 vs 150 units per
  detent); Swift Pair with RPA privacy; directed advertising per OS; whether
  Windows accepts peripheral latency 30.
* GATT authorization callback availability in the NCS version used.
* Stepper thrust above 500 PPS at VSYS 3.55–4.2 V; stroke time; HOME edge
  repeatability and drift with temperature (the ±10-step margin of §5.4);
  homing time; that repeated 50 % stalls at the park stop do not wear or jam
  the nut.
* Bearing friction, spin-down priors, friction-shoe engagement offset and
  torque.
* BQ25180 ship entry with VBUS present; WAKE-flag interrupt behaviour;
  whether a press while charging sets TS_FAULT or pulses /INT
  (charger_ts-v2). (The SYS_MODE and CHG_DIS fields for USB suspend are now
  taken from SLUSE99C Table 8-19 and ICHG_CTRL bit 7, [§13.3](#133-input-current-strategy-on-usb).)
* LIS2DW12 register bit fields, current at 3.3 V, and tap thresholds through
  the floating assembly.
* Flick-artifact press-rejection thresholds.
* Every current in [§12.1](#121-states) (PPK2).

---

## 19. References

* SPEC and nets: `hardware/design/SPEC.md`, `hardware/design/nets.py`;
  docs/architecture.md.
* SPICE suite: `hardware/sim` (tests and `results/report.md`), described in
  docs/simulation.md; the finding ids cited above come from its tests.
* Subsystem research and verifier reports (session scratchpad,
  `research/<key>.full.json`): sensing, detent, display, leds, power,
  mcu_rf_fw, mechanical. The corrected values are used throughout.
* nRF52840 Product Specification, pins and sleep currents:
  https://docs.nordicsemi.com/bundle/ps_nrf52840/page/pin.html,
  https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/_tmp/nrf52840/autodita/current/parameters.i_sleep.html
* nRF52840 PS TWIM: https://docs.nordicsemi.com/bundle/ps_nrf52840/page/twim.html;
  SPIM: https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/spim.html;
  memory: https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/memory.html
* nRF52840 errata 198 (SPIM3):
  http://docs.nordicsemi.com/r/bundle/errata_nrf52840_rev3/page/err/nrf52840/rev3/latest/anomaly_840_198.html
* Raytac MDBT50Q spec:
  https://cdn.sparkfun.com/assets/4/7/4/3/8/_nRF52840__MDBT50Q-1MV2___MDBT50Q-P1MV2_Ver.K_spec.pdf
* TMAG5273 datasheet SLYS045C: https://www.ti.com/lit/ds/symlink/tmag5273.pdf
* DRV5032: https://www.ti.com/lit/ds/symlink/drv5032.pdf;
  DRV8837: https://www.ti.com/lit/ds/symlink/drv8837.pdf
* VSM08102 micro linear stepper:
  https://www.micro-steppermotors.com/sale-28526335-vsm08102-8mm-4-pins-fpc-small-linear-stepper-motor-with-slider-m2-lead-screw.html
* BQ25180 SLUSE99C: https://www.ti.com/lit/ds/symlink/bq25180.pdf;
  TPS22917: https://www.ti.com/lit/ds/symlink/tps22917.pdf;
  TPS61040: https://www.ti.com/lit/ds/symlink/tps61040.pdf
* SSD1351: https://cdn-shop.adafruit.com/datasheets/SSD1351-Revision+1.3.pdf;
  NHD-1.5-128128G: https://newhavendisplay.com/content/specs/NHD-1.5-128128G.pdf;
  Orient AOC128128A0-1.50W: https://www.lcsc.com/datasheet/C20432911.pdf
* WS2812C-2020-V6:
  https://datasheet.lcsc.com/datasheet/pdf/8c7f104c99e52e4adb687ae84e594e95.pdf;
  Zephyr ws2812-i2s binding:
  https://docs.zephyrproject.org/latest/build/dts/api/bindings/led_strip/worldsemi,ws2812-i2s.html;
  driver: https://raw.githubusercontent.com/zephyrproject-rtos/zephyr/main/drivers/led_strip/ws2812_i2s.c
* Zephyr SSD1351 binding:
  https://docs.zephyrproject.org/latest/build/dts/api/bindings/display/solomon,ssd1351.html
* LIS2DW12 AN5038:
  https://www.st.com/resource/en/application_note/an5038-lis2dw12-alwayson-3d-accelerometer-stmicroelectronics.pdf
* Microsoft Radial Controller sample descriptors, input reports and protocol:
  https://learn.microsoft.com/en-us/windows-hardware/design/component-guidelines/radial-controller-sample-report-descriptors,
  https://learn.microsoft.com/en-us/windows-hardware/design/component-guidelines/radial-controller-input-reports,
  https://learn.microsoft.com/en-us/windows-hardware/design/component-guidelines/radial-controller-protocol-implementation
* Prior art: DIY Surface Dial (https://blog.jfedor.org/2022/07/diy-surface-dial.html,
  https://github.com/jfedor2/radial-controller); SmartKnob
  (https://github.com/scottbez1/smartknob).
