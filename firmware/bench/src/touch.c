/*
 * Touch controller over raw I2C on i2c0 (P0.26 SDA / P0.27 SCL), with TP_INT
 * on P0.28 and TP_RST_N on P0.29.
 *
 * The panel carries a Hynitron CST9217 (Viewe and Huaxin parts, the Waveshare
 * board) or a CST820B (TailorPixels). Zephyr has no CST9217 driver, and no
 * datasheet for it was found (display-study.md §3.1, §3.6), so this file
 * talks to it directly. The register layout follows the third-party drivers
 * (Espressif's esp_lcd_touch_cst9217, Lewis He's SensorLib) and is
 * UNVERIFIED: "touch raw" reads any register when it turns out different.
 *
 *   CST9217 (addr 0x5A, 16-bit registers, big-endian)
 *     D101h write: enter command mode; D109h: back to normal mode
 *     D204h read 4: project id (LE16), chip type (LE16, expect 9217h)
 *     D000h read 10: touch frame. [5] & 7Fh = points, [6] = ABh ack marker,
 *       point 0 at [0..4]: [0] & 0Fh = 6 when pressed,
 *       x = [1] << 4 | [3] >> 4, y = [2] << 4 | [3] & 0Fh.
 *       Then write D0h 00h ABh to release the frame.
 *   CST816/CST820 (addr 0x15, 8-bit registers)
 *     01h read 6: gesture, points, XH (bits 3:0), XL, YH (bits 3:0), YL
 *     A7h/A8h/A9h: chip id, project id, firmware version
 *
 * Touch I2C voltage (the issue #5 question): as fitted, R14/R15 tie the bus
 * to the DK at VDD (3.0 V). The 1.8 V option goes through U2 (PCA9306); this
 * code is the same for both.
 */
#include <stdlib.h>
#include <string.h>

#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/shell/shell.h>

#include "bench.h"

LOG_MODULE_REGISTER(touch, LOG_LEVEL_INF);

#define CST9217_ADDR 0x5A
#define CST8XX_ADDR 0x15

static const struct device *const i2c = DEVICE_DT_GET(DT_NODELABEL(i2c0));
static const struct gpio_dt_spec tp_int = GPIO_DT_SPEC_GET(USER_NODE, tp_int_gpios);
static const struct gpio_dt_spec tp_rst = GPIO_DT_SPEC_GET(USER_NODE, tp_rst_gpios);

static uint8_t addr = CST9217_ADDR;
static struct gpio_callback int_cb;
static K_SEM_DEFINE(int_sem, 0, 1);
static volatile uint32_t int_count;

static void int_isr(const struct device *port, struct gpio_callback *cb, uint32_t pins)
{
	ARG_UNUSED(port);
	ARG_UNUSED(cb);
	ARG_UNUSED(pins);
	int_count++;
	k_sem_give(&int_sem);
}

int touch_init(void)
{
	int ret;

	if (!device_is_ready(i2c) || !gpio_is_ready_dt(&tp_int) || !gpio_is_ready_dt(&tp_rst)) {
		return -ENODEV;
	}
	/* Hold the controller in reset until "touch reset": the panel may be unpowered. */
	ret = gpio_pin_configure_dt(&tp_rst, GPIO_OUTPUT_ACTIVE);
	ret = ret ? ret : gpio_pin_configure_dt(&tp_int, GPIO_INPUT);
	if (ret < 0) {
		return ret;
	}
	gpio_init_callback(&int_cb, int_isr, BIT(tp_int.pin));
	ret = gpio_add_callback(tp_int.port, &int_cb);
	return ret ? ret : gpio_pin_interrupt_configure_dt(&tp_int, GPIO_INT_EDGE_TO_ACTIVE);
}

static bool is_16bit(void)
{
	return addr != CST8XX_ADDR;
}

static int reg_read(uint16_t reg, uint8_t *buf, size_t len)
{
	uint8_t r[2] = {reg >> 8, reg & 0xFF};

	if (is_16bit()) {
		return i2c_write_read(i2c, addr, r, 2, buf, len);
	}
	return i2c_write_read(i2c, addr, &r[1], 1, buf, len);
}

static int reg_write(uint16_t reg, const uint8_t *data, size_t len)
{
	uint8_t b[2 + 8];

	if (len > 8) {
		return -EINVAL;
	}
	b[0] = reg >> 8;
	b[1] = reg & 0xFF;
	if (len) {
		memcpy(&b[2], data, len);
	}
	if (is_16bit()) {
		return i2c_write(i2c, b, 2 + len, addr);
	}
	return i2c_write(i2c, &b[1], 1 + len, addr);
}

static void dump(const struct shell *sh, const uint8_t *b, size_t n)
{
	for (size_t i = 0; i < n; i++) {
		shell_fprintf(sh, SHELL_NORMAL, " %02X", b[i]);
	}
	shell_print(sh, "");
}

/* Returns 1 with a point, 0 without, negative on a bus error. */
static int read_point(const struct shell *sh, uint16_t *x, uint16_t *y, bool verbose)
{
	uint8_t d[10];
	int ret;

	if (is_16bit()) {
		static const uint8_t ack = 0xAB;

		ret = reg_read(0xD000, d, sizeof(d));
		if (ret < 0) {
			return ret;
		}
		(void)reg_write(0xD000, &ack, 1);
		if (verbose) {
			shell_fprintf(sh, SHELL_NORMAL, "D000h:");
			dump(sh, d, sizeof(d));
		}
		if (d[6] != 0xAB) {
			if (verbose) {
				shell_warn(sh, "no ABh marker at [6]: layout differs from the "
					   "third-party drivers");
			}
			return 0;
		}
		if ((d[5] & 0x7F) == 0 || (d[0] & 0x0F) != 0x06) {
			return 0;
		}
		*x = (d[1] << 4) | (d[3] >> 4);
		*y = (d[2] << 4) | (d[3] & 0x0F);
		return 1;
	}

	ret = reg_read(0x01, d, 6);
	if (ret < 0) {
		return ret;
	}
	if (verbose) {
		shell_fprintf(sh, SHELL_NORMAL, "01h:");
		dump(sh, d, 6);
	}
	if (d[1] == 0) {
		return 0;
	}
	*x = ((d[2] & 0x0F) << 8) | d[3];
	*y = ((d[4] & 0x0F) << 8) | d[5];
	return 1;
}

static int cmd_reset(const struct shell *sh, size_t argc, char **argv)
{
	uint32_t wait = argc > 1 ? strtoul(argv[1], NULL, 0) : 200;

	ARG_UNUSED(argv);
	gpio_pin_set_dt(&tp_rst, 1);
	k_msleep(10);
	gpio_pin_set_dt(&tp_rst, 0);
	k_msleep(wait);
	shell_print(sh, "TP_RST_N pulsed 10 ms low, waited %u ms; TP_INT is %s", wait,
		    gpio_pin_get_dt(&tp_int) ? "asserted (low)" : "idle (high)");
	return 0;
}

static int cmd_scan(const struct shell *sh, size_t argc, char **argv)
{
	uint8_t b;
	int found = 0;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	for (uint8_t a = 0x08; a < 0x78; a++) {
		if (i2c_read(i2c, &b, 1, a) == 0) {
			shell_print(sh, "  0x%02X answers%s", a,
				    a == CST9217_ADDR ? " (CST9217?)" :
				    a == CST8XX_ADDR ? " (CST816/CST820?)" : "");
			found++;
		}
	}
	shell_print(sh, "%d device(s) on i2c0 (P0.26/P0.27)", found);
	return 0;
}

static int cmd_addr(const struct shell *sh, size_t argc, char **argv)
{
	if (argc > 1) {
		addr = strtoul(argv[1], NULL, 16);
	}
	shell_print(sh, "touch address 0x%02X, %s registers", addr, is_16bit() ? "16-bit" : "8-bit");
	return 0;
}

static int cmd_id(const struct shell *sh, size_t argc, char **argv)
{
	uint8_t d[4];
	int ret;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	if (is_16bit()) {
		ret = reg_write(0xD101, NULL, 0);	/* command mode */
		k_msleep(10);
		ret = ret ? ret : reg_read(0xD204, d, 4);
		(void)reg_write(0xD109, NULL, 0);	/* normal mode */
		if (ret == 0) {
			shell_print(sh, "D204h: project %04Xh, chip type %04Xh (CST9217 = 9217h)",
				    d[0] | (d[1] << 8), d[2] | (d[3] << 8));
		}
	} else {
		ret = reg_read(0xA7, d, 3);
		if (ret == 0) {
			shell_print(sh, "chip id %02Xh, project %02Xh, firmware %02Xh", d[0], d[1],
				    d[2]);
		}
	}
	if (ret < 0) {
		shell_error(sh, "no answer at 0x%02X (%d): try \"touch reset\", \"touch scan\"",
			    addr, ret);
	}
	return ret;
}

static int cmd_read(const struct shell *sh, size_t argc, char **argv)
{
	uint16_t x, y;
	int ret;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	ret = read_point(sh, &x, &y, true);
	if (ret < 0) {
		shell_error(sh, "read failed: %d", ret);
	} else if (ret == 0) {
		shell_print(sh, "no touch (TP_INT %s, %u INT edges so far)",
			    gpio_pin_get_dt(&tp_int) ? "low" : "high", int_count);
	} else {
		shell_print(sh, "touch at x %u, y %u", x, y);
	}
	return ret < 0 ? ret : 0;
}

static int cmd_watch(const struct shell *sh, size_t argc, char **argv)
{
	uint32_t secs = argc > 1 ? strtoul(argv[1], NULL, 0) : 10;
	int64_t end = k_uptime_get() + secs * 1000LL;
	uint32_t edges0 = int_count, points = 0;

	shell_print(sh, "printing touches for %u s (on TP_INT edges, and every 50 ms)", secs);
	while (k_uptime_get() < end) {
		uint16_t x, y;

		(void)k_sem_take(&int_sem, K_MSEC(50));
		if (read_point(sh, &x, &y, false) == 1) {
			shell_print(sh, "  %6lld ms  x %3u  y %3u", k_uptime_get(), x, y);
			points++;
		}
	}
	shell_print(sh, "%u points, %u TP_INT edges", points, int_count - edges0);
	return 0;
}

static int cmd_raw(const struct shell *sh, size_t argc, char **argv)
{
	uint8_t buf[32];
	uint16_t reg = strtoul(argv[1], NULL, 16);
	size_t n = argc > 2 ? CLAMP(strtoul(argv[2], NULL, 0), 1, sizeof(buf)) : 1;
	int ret = reg_read(reg, buf, n);

	if (ret < 0) {
		shell_error(sh, "read failed: %d", ret);
		return ret;
	}
	shell_fprintf(sh, SHELL_NORMAL, "0x%02X reg %04Xh:", addr, reg);
	dump(sh, buf, n);
	return 0;
}

SHELL_STATIC_SUBCMD_SET_CREATE(touch_cmds,
	SHELL_CMD_ARG(reset, NULL, "reset [wait_ms]: pulse TP_RST_N, then wait", cmd_reset, 1, 1),
	SHELL_CMD(scan, NULL, "Probe every 7-bit address on i2c0", cmd_scan),
	SHELL_CMD_ARG(addr, NULL, "addr [hex]: 5A = CST9217 (16-bit regs), 15 = CST8xx",
		      cmd_addr, 1, 1),
	SHELL_CMD(id, NULL, "Read the chip id", cmd_id),
	SHELL_CMD(read, NULL, "Read one touch frame and decode it", cmd_read),
	SHELL_CMD_ARG(watch, NULL, "watch [s]: print touches as they come", cmd_watch, 1, 1),
	SHELL_CMD_ARG(raw, NULL, "raw <reg hex> [n]: read n bytes from a register",
		      cmd_raw, 2, 1),
	SHELL_SUBCMD_SET_END);

SHELL_CMD_REGISTER(touch, &touch_cmds, "Touch controller (raw I2C)", NULL);
