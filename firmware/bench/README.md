# Rev B bench firmware

A Zephyr app for the rev B bench phase ([issue #5](https://github.com/tyevco/dial-me-spinner/issues/5),
[rev-b-bench.md](../../docs/rev-b-bench.md)). It runs on an **nRF52840-DK** carrying the AMOLED shield
(`hardware/kicad/bench_display`), and it acts as the NFC tag for the coil plate and base. It brings the 1.75 in
CO5300 panel up in the documented order, then gives one shell command for each check on the bench list.

**Status: it builds with no warnings, but has never run.** No board exists yet. Everything that depends on the
panel's behaviour is listed under [Unverified until the bench](#unverified-until-the-bench).

| | |
|---|---|
| Zephyr | **v4.5.0-rc3**, the first tag whose `chipone,co5300` driver supports SPI. v4.4.2, the newest final release, has only the MIPI-DSI variant. Move to v4.5.0 when it is tagged. |
| SDK | Zephyr SDK 1.0.1, `arm-zephyr-eabi` toolchain only |
| Board | `nrf52840dk/nrf52840` (PCA10056) |
| Size | 97.3 KB flash (9.3 % of 1 MB), 41.1 KB RAM (15.7 % of 256 KB) |

## Setup

The toolchain is Linux. On the project laptop it lives in WSL (`Ubuntu-24.04`), in `~/zephyrproject`, kept apart
from the hardware venv. [`setup-zephyr.sh`](setup-zephyr.sh) reproduces it:

```sh
wsl -d Ubuntu-24.04 -- bash -lc 'bash /mnt/c/source/tyevco/dial-me-spinner/firmware/bench/setup-zephyr.sh'
```

It installs nothing system-wide and downloads only from github.com/zephyrproject-rtos and PyPI:

- a venv at `~/zephyrproject/.venv` with west, cmake and ninja from PyPI, plus Zephyr's `requirements-base.txt`;
- a minimal workspace from [`west.yml`](west.yml): `zephyr` plus the `cmsis`, `cmsis_6` and `hal_nordic`
  modules (name-allowlist, shallow clones), about 1.2 GB instead of a full `west update`;
- the SDK's minimal bundle and its arm toolchain, hash-checked, at `~/zephyrproject/zephyr-sdk-1.0.1`.

CMake prints `Could NOT find Dtc`. That is expected: dtc only adds extra devicetree lint, and the build does not
need it.

## Build

Keep the build tree off `/mnt/c`, which is slow from WSL.

```sh
. ~/zephyrproject/.venv/bin/activate
cd ~/zephyrproject
west build -b nrf52840dk/nrf52840 -d ~/build/bench /mnt/c/source/tyevco/dial-me-spinner/firmware/bench -o=-j4
```

`-o=-j4` keeps ninja to four jobs. Without it, ninja starts one job per core, and this laptop has run short of
memory that way.

Kconfig options (in [`Kconfig`](Kconfig), set in `prj.conf` or with `-- -DCONFIG_...`):

| Option | Default | |
|---|---|---|
| `BENCH_AUTO_POWERUP` | y | Run the bring-up at boot and show colour bars. Set it to n to start dark and type `power up` with the PPK2 already logging. |
| `BENCH_VBAT_SETTLE_MS` | 10 | DISP_VBAT_EN → VCI_EN. U1's tON is about 4 ms with CT = 1 nF. |
| `BENCH_VCI_SETTLE_MS` | 20 | VCI_EN → reset. A guess: no BV6802W datasheet was found. |
| `BENCH_SLPOUT_MS` | 120 | Sleep-out (11h) → display-on (29h) |

## Flash and connect

The DK's interface MCU shows up on Windows as a **JLINK** USB drive. The simplest way to flash is to copy
`\\wsl$\Ubuntu-24.04\home\tyler\build\bench\zephyr\zephyr.hex` onto that drive. `west flash -d ~/build/bench`
also works, but it needs the SEGGER J-Link tools and, under WSL, the DK passed through with usbipd-win.

The shell and the log share the DK's VCOM port (the JLink CDC UART) at **115200 8N1**. Any terminal works, for
example PuTTY or `python -m serial.tools.miniterm COMx 115200`.

## Hardware setup

- **Shield** on the DK's Arduino headers. **J4** 1–2 takes VBAT from **J3** (a PPK2 in source mode). 2–3 uses
  the DK's VDD, which at 3.0 V is below the panel's 3.7 V pin-table minimum.
- **J5** shunt fitted for normal use. Take it off and put a PPK2 across it, as an ammeter, to log VCI + IOVCC +
  TP_VDD.
- **NFC:** the coil plate's J2 goes to the DK's NFC connector. The DK leaves UICR.NFCPINS in NFC mode.

## Bring-up

At boot (or on `power up`) the firmware follows the order in
[rev-b-bench.md](../../docs/rev-b-bench.md#firmware-a-dk-overlay) and
[display-study.md](../../docs/display-study.md) §3.5, and logs each step:

1. `DISP_VBAT_EN` (P1.02) high. U1 (TPS22917) connects VBAT_IN to the panel. Wait 10 ms.
2. `DISP_VCI_EN` (P1.05) high, which starts the tail's power chip. Wait 20 ms.
3. Reset and init. The first time, this goes through Zephyr's driver (`device_init()` on the
   `zephyr,deferred-init` node): reset low for 150 ms, then a 150 ms wait, then C4h 80h (SPI mode), 36h/3Ah,
   35h (TE on), 53h 20h, 51h FFh, 63h FFh, 11h and 29h. The driver can be initialised only once, so after a power
   cycle the app repeats the same sequence over its raw path, with a 10 ms reset pulse.
4. Wait 120 ms after sleep-out, then display on (29h) again. The driver sends 29h immediately after 11h.

Power-down (`power down`) runs it backwards: 28h, 10h, 120 ms, VCI_EN low, VBAT off. VCI, IOVCC and TP_VDD are
not switched. They come from the DK's VDD through J5, so they stay up.

## Commands

`help` and `<command> -h` list everything. Colours are names (`white`, `red`, `grey`, ...) or `RRGGBB` hex.
Numbers are decimal unless marked hex.

| Command | What it does |
|---|---|
| `power status` | Rail states and whether the panel is up |
| `power up` / `power down` | The full bring-up / power-down above |
| `power cycle [off_ms]` | Down, wait (500 ms by default), up |
| `power vbat on\|off` | DISP_VBAT_EN alone |
| `power vci on\|off` | DISP_VCI_EN alone |
| `disp info` | Format, write path, SPI clock, column offset, brightness |
| `disp bars` | Eight vertical colour bars |
| `disp fill <colour>` | Solid full screen. Prints the bytes sent and the time on the bus. |
| `disp grid [pitch] [colour]` | Grid (32 px by default), red centre cross, green circles at r 220 and r 232 (the 466 px edge) |
| `disp area <percent> [colour]` | The top `percent` of rows lit, the rest black |
| `disp rect <x> <y> <w> <h> <colour>` | A partial-window write. Warns about odd coordinates (the CO5300 wants them even). |
| `disp fmt [name] [COLMOD hex]` | List the formats, or switch: `rgb565`, `rgb888` (through the driver), `rgb666`, `rgb332`, `rgb111` (raw). A second argument overrides the COLMOD code. |
| `disp bright <0-255>` | Brightness, 51h |
| `disp hbm <0-255>` | High-brightness level, 63h |
| `disp on` / `disp off` | 29h / 28h |
| `disp sleep in\|out` | 10h / 11h |
| `disp te [ms]` | Count TE edges over a window (1 s by default). Prints the rate and the period's mean, min and max, timed on the DWT counter. |
| `disp fps [frames] [w] [h] [nosync]` | Frame rate: alternating red/blue frames of w × h (full screen by default), each started on a TE edge. Prints fps, the write time per frame, the bus rate and the TE edges per frame. |
| `disp init` | Raw re-init (reset, init sequence, sleep-out, display on) |
| `disp cmd <hex> [hex ...]` | Send any command with up to 16 parameter bytes |
| `disp read <hex> [n]` | Read a register: opcode 03h, data on SIO1 (P0.30), at 1 MHz by default |
| `disp freq [write MHz] [read MHz]` | Raw-path SPI clocks: 32, 16, 8, 4, 2 or 1 MHz |
| `disp path [driver\|raw]` | Which path pixel writes prefer. Raw formats and clocks other than 32 MHz always use the raw path. |
| `disp offset [cols]` | The raw path's column offset (6 by default, the driver's fixed value) |
| `touch reset [wait_ms]` | Pulse TP_RST_N (P0.29) for 10 ms, then wait (200 ms by default) |
| `touch scan` | Probe every I2C address on i2c0 |
| `touch addr [hex]` | 5A = CST9217 (16-bit registers, the default), 15 = CST816/CST820 |
| `touch id` | Chip id |
| `touch read` | One touch frame, as a raw dump and decoded |
| `touch watch [s]` | Print touches as they come (on TP_INT, P0.28), and count INT edges |
| `touch raw <reg hex> [n]` | Read any register |
| `nfc start [uri]` | Start the Type 2 tag, holding one `https://` URI (`github.com/tyevco/dial-me-spinner` by default). Keeps HFXO on. |
| `nfc stop` / `nfc status` / `nfc dump` | Stop it; the field, select and read counters; the tag memory |
| `i2c ...`, `gpio ...`, `kernel ...` | Zephyr's own shells, for anything else |

## The bench checklist, command by command

| Issue #5 item | How |
|---|---|
| **Bring-up sequence** | The boot log (or `power up`) logs each step with its time. Scope DISP_VBAT, VCI_EN and RESET while it runs. Use `power cycle`, and the `BENCH_*_MS` options, to find the shortest delays that still work. Then add margin. |
| **1-wire 0x02 framing at 32 MHz** | `disp bars` and `disp fill white` through the driver at 32 MHz. Probe TP1–TP4 (SCK, SIO0, CS, TE) with a spring ground and check edges ≤ 3.5 ns (20–80 %). If the picture breaks up, `disp freq 16` (then 8) shows whether the clock is the cause. Then swap R6/R7 for 22–33 Ω. `disp read 04 3` (display ID) checks the read path. |
| **RGB565, RGB332 and RGB111** | `disp fmt rgb332`, then `disp bars`. Then `disp fmt rgb111`, `disp bars`. `disp fps` in each mode gives the full-screen rate to set against the study's 9 / 18–22 / 37 fps. If 22h or 11h is not the right COLMOD code, try others with `disp fmt rgb332 <code>`. |
| **TE pin and partial windows** | `disp te` gives the refresh rate. `disp fps` (synced) and `disp fps 30 466 466 nosync` show the tearing difference. `disp fps 60 200 100` times a small window. `disp rect` with odd and even coordinates checks the even-alignment rule. |
| **Current against content (PPK2)** | PPK2 on J3 (VBAT) or across J5 (logic). Step through `disp fill black`, `disp area 10`/`30`/`50`/`100`, `disp fill white`/`red`/`green`/`blue`, and `disp bright 0…255`. `disp off`, `disp sleep in` and `power down` give the idle floors. |
| **VBAT sweep 3.0–4.5 V** | PPK2 source on J3, with J4 on 1–2. At each step run `power cycle` (a cold start at that voltage) and `disp bars`, then `disp fill white`, the worst case. Note where brightness drops or the panel browns out. |
| **Touch I2C: 1.8 V or 3.3 V?** | As fitted (3.0 V): `touch reset`, `touch scan`, `touch id`, `touch watch`. Then refit for 1.8 V (U2, U3 and the parts listed in rev-b-bench.md) and repeat. The firmware is the same; only the shield changes. |
| **NFC: reads with 2–3 phones** | `nfc start`, then hold each phone at contact, 1, 2, 3 and 4 cm. `nfc status` shows the field and read counts, which separates "no field detected" from "field, but no read". |
| NFC: NanoVNA L, Q, f₀ | Needs no firmware: J2 is unplugged for that step. |

## What is real and what is a stand-in

- **Real:** the rails and the bring-up order; the upstream `chipone,co5300` driver for init, RGB565/RGB888,
  brightness and blanking; an app-side copy of its framing for the other colour modes, clocks and reads; TE timing
  on the DWT counter; patterns, partial windows and the frame-rate test; raw-I2C touch; and the NFC Type 2 tag.
- **The NFC tag is not nrfxlib's `nfc_t2t`.** That library comes with the nRF Connect SDK. It is not on
  github.com/zephyrproject-rtos and not in Zephyr's manifest. Instead, [`src/nfc.c`](src/nfc.c) is a minimal
  read-only Type 2 tag on `nrfx_nfct` (hal_nordic). The NFCT hardware does anticollision and CRC, and the app
  answers READ (30h) and HALT (50h) from a 144-byte memory: UID, CC `E1 10 10 0F`, then one NDEF URI record. Any
  other command gets no answer, which a reader treats as a read-only tag. That covers reading a URL with phones. A
  writable tag or Type 4 would need NCS.
- **The touch decoding is unverified.** No CST9217 datasheet was found, so the register layout comes from the
  third-party drivers (Espressif's `esp_lcd_touch_cst9217`, SensorLib). `touch raw` reads around it if it is
  wrong.

## Unverified until the bench

- **Column offset 6.** The driver hard-codes it. The `disp grid` circles should be centred and complete.
- **Colour order.** The driver sets MADCTL's BGR bit in RGB565 unless the node has `red-blue-swap`. If red and
  blue swap in `disp bars`, use `disp cmd 36 00` (or `08`), then add `red-blue-swap` to the overlay.
- **COLMOD codes and packing for 8-bit and 3-bit colour.** The DCS codes 22h/11h are assumed, and RGB111 is packed
  two pixels per byte (0RGB0RGB, first pixel high). The CO5300 datasheet should settle both.
- **The read opcode** (03h, data on SIO1) and whether reads need dummy clocks.
- **Delays:** VCI_EN settling (20 ms, a guess), reset (150 ms in the driver, 10 ms raw), and sleep-out (120 ms).
- **The touch address and registers** (above). Whether TP_INT pulses per frame or holds low is also unknown;
  `touch watch` polls every 50 ms as well, so either works.
- **SPIM3 anomaly 198.** The workaround is on (`CONFIG_NRF52_ANOMALY_198_WORKAROUND`), and it stalls the CPU on
  any access to the band buffer's RAM block during a transfer. That is harmless here, but it is part of the
  `disp fps` timing.
- **The HFXO** is held on while `nfc start` runs, so subtract it (about 250 µA) from DK current readings taken
  then.

## Files

| | |
|---|---|
| [`boards/nrf52840dk_nrf52840.overlay`](boards/nrf52840dk_nrf52840.overlay) | SPIM3 pinctrl, the `chipone,co5300` node, the power, TE and touch GPIOs, `spi1` disabled. `hardware/design/tests/test_bench_display.py` checks its pins against the shield's netlist. |
| [`src/power.c`](src/power.c) | Rails, bring-up and power-down; `power` |
| [`src/panel.c`](src/panel.c) | Driver and raw paths, formats, patterns, TE, frame rate; `disp` |
| [`src/touch.c`](src/touch.c) | Raw-I2C CST9217 / CST8xx; `touch` |
| [`src/nfc.c`](src/nfc.c) | Type 2 tag on `nrfx_nfct`; `nfc` |
| [`west.yml`](west.yml), [`setup-zephyr.sh`](setup-zephyr.sh) | The minimal workspace and the toolchain install |
