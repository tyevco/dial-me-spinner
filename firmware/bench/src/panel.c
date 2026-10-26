/*
 * CO5300 panel: driver bring-up, a raw SPI path for what the driver does not
 * cover, TE timing, test patterns and the "disp" shell.
 *
 * Two write paths reach the same SPIM3 and CS:
 *   driver  display_write() through Zephyr's chipone,co5300 driver. RGB565 and
 *           RGB888 only, at the devicetree clock (32 MHz). This is the path
 *           the product firmware would use.
 *   raw     The same 0x02 framing built here: 0x02, then {0x00, CMD, 0x00},
 *           then parameters or pixels, on one data line. It adds the colour
 *           modes the driver lacks (RGB332, RGB111, RGB666), other SPI
 *           clocks, register reads and re-init after a power cycle.
 * Pixel writes pick the driver path when it can do the job and "disp path"
 * allows it, else the raw path.
 *
 * Unverified until a panel is on the bench (TVP):
 *   - the column offset of 6 (the driver hard-codes it; "disp offset" moves
 *     the raw path's);
 *   - the COLMOD codes for 8-bit and 3-bit colour (DCS 22h/11h are used;
 *     "disp fmt <name> <code>" overrides) and the RGB111 packing (two pixels
 *     per byte, 0RGB0RGB, first pixel in the high nibble);
 *   - the read opcode (03h) and whether reads need dummy cycles;
 *   - red/blue order: the driver sets MADCTL BGR for RGB565 unless the node
 *     has red-blue-swap. "disp cmd 36 00" flips it back.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/display/mipi_display.h>
#include <zephyr/drivers/display.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/spi.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/shell/shell.h>
#include <zephyr/sys/util.h>
#include <zephyr/timing/timing.h>

#include "bench.h"

LOG_MODULE_REGISTER(panel, LOG_LEVEL_INF);

#define W DT_PROP(DISP_NODE, width)
#define H DT_PROP(DISP_NODE, height)
#define BAND_LINES 16
#define MAX_LINE_BYTES (W * 3)

#define CO5300_OP_WRITE 0x02
#define CO5300_OP_READ 0x03
#define CO5300_SPI_MODE 0xC4
#define CO5300_HBM_BRIGHTNESS 0x63

static const struct device *const disp = DEVICE_DT_GET(DISP_NODE);
static const struct spi_dt_spec spi = SPI_DT_SPEC_GET(DISP_NODE, SPI_OP_MODE_CONTROLLER |
							   SPI_WORD_SET(8) | SPI_TRANSFER_MSB);
static const struct gpio_dt_spec reset = GPIO_DT_SPEC_GET(DISP_NODE, reset_gpios);
static const struct gpio_dt_spec te = GPIO_DT_SPEC_GET(USER_NODE, disp_te_gpios);

/* One spi_config per clock: the nrfx SPIM driver caches its setup by config pointer. */
static const uint32_t clocks_mhz[] = {32, 16, 8, 4, 2, 1};
static struct spi_config raw_cfg[ARRAY_SIZE(clocks_mhz)];
static const struct spi_config *wr_cfg = &raw_cfg[0];
static const struct spi_config *rd_cfg = &raw_cfg[ARRAY_SIZE(clocks_mhz) - 1];

struct fmt {
	const char *name;
	uint8_t colmod;
	uint8_t bits;			/* bits per pixel on the wire */
	enum display_pixel_format pf;	/* 0: the driver cannot do it */
};

static struct fmt fmts[] = {
	{"rgb565", MIPI_DCS_PIXEL_FORMAT_16BIT, 16, PIXEL_FORMAT_RGB_565},
	{"rgb888", MIPI_DCS_PIXEL_FORMAT_24BIT, 24, PIXEL_FORMAT_RGB_888},
	{"rgb666", MIPI_DCS_PIXEL_FORMAT_18BIT, 24, 0},
	{"rgb332", MIPI_DCS_PIXEL_FORMAT_8BIT, 8, 0},
	{"rgb111", MIPI_DCS_PIXEL_FORMAT_3BIT, 4, 0},
};

static const struct fmt *cur_fmt = &fmts[0];
static bool prefer_driver = true;
static uint16_t col_off = 6;		/* the driver's value */
static uint8_t brightness = 0xFF;
static bool driver_ready;

static uint8_t band[BAND_LINES * MAX_LINE_BYTES] __aligned(4);

/* ---- TE --------------------------------------------------------------- */

static struct gpio_callback te_cb;
static K_SEM_DEFINE(te_sem, 0, 1);
static volatile uint32_t te_count;
static volatile uint32_t te_last;
static volatile uint32_t te_min = UINT32_MAX;
static volatile uint32_t te_max;
static volatile uint64_t te_sum;

static inline uint32_t cyc_now(void)
{
	return (uint32_t)timing_counter_get();
}

static inline uint32_t cyc_to_us(uint32_t cyc)
{
	return (uint32_t)(timing_cycles_to_ns(cyc) / 1000U);
}

static void te_isr(const struct device *port, struct gpio_callback *cb, uint32_t pins)
{
	ARG_UNUSED(port);
	ARG_UNUSED(cb);
	ARG_UNUSED(pins);
	uint32_t now = cyc_now();

	if (te_count > 0) {
		uint32_t d = now - te_last;

		te_sum += d;
		te_min = MIN(te_min, d);
		te_max = MAX(te_max, d);
	}
	te_last = now;
	te_count++;
	k_sem_give(&te_sem);
}

static void te_reset_stats(void)
{
	unsigned int key = irq_lock();

	te_count = 0;
	te_sum = 0;
	te_min = UINT32_MAX;
	te_max = 0;
	irq_unlock(key);
}

/* ---- raw SPI ---------------------------------------------------------- */

int panel_cmd(uint8_t cmd, const uint8_t *data, size_t len)
{
	uint8_t hdr[4] = {CO5300_OP_WRITE, 0x00, cmd, 0x00};
	struct spi_buf bufs[2] = {
		{.buf = hdr, .len = sizeof(hdr)},
		{.buf = (void *)data, .len = len},
	};
	struct spi_buf_set set = {.buffers = bufs, .count = (data && len) ? 2 : 1};

	return spi_write(spi.bus, wr_cfg, &set);
}

static int panel_cmd1(uint8_t cmd, uint8_t v)
{
	return panel_cmd(cmd, &v, 1);
}

static int panel_read(uint8_t cmd, uint8_t *out, size_t len)
{
	uint8_t hdr[4] = {CO5300_OP_READ, 0x00, cmd, 0x00};
	struct spi_buf tx = {.buf = hdr, .len = sizeof(hdr)};
	struct spi_buf rx[2] = {
		{.buf = NULL, .len = sizeof(hdr)},
		{.buf = out, .len = len},
	};
	struct spi_buf_set txs = {.buffers = &tx, .count = 1};
	struct spi_buf_set rxs = {.buffers = rx, .count = 2};

	return spi_transceive(spi.bus, rd_cfg, &txs, &rxs);
}

static int raw_window(uint16_t x, uint16_t y, uint16_t w, uint16_t h)
{
	uint16_t xs = x + col_off, xe = x + col_off + w - 1;
	uint16_t ye = y + h - 1;
	uint8_t ca[4] = {xs >> 8, xs & 0xFF, xe >> 8, xe & 0xFF};
	uint8_t pa[4] = {y >> 8, y & 0xFF, ye >> 8, ye & 0xFF};
	int ret = panel_cmd(MIPI_DCS_SET_COLUMN_ADDRESS, ca, sizeof(ca));

	return ret ? ret : panel_cmd(MIPI_DCS_SET_PAGE_ADDRESS, pa, sizeof(pa));
}

/* ---- pixels ----------------------------------------------------------- */

static size_t line_bytes(uint16_t w)
{
	return ((size_t)w * cur_fmt->bits + 7U) / 8U;
}

static void put_px(uint8_t *line, uint16_t i, uint32_t rgb)
{
	uint8_t r = rgb >> 16, g = rgb >> 8, b = rgb;

	switch (cur_fmt->bits) {
	case 16: {
		uint16_t v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);

		line[2 * i] = v >> 8;	/* MSB first on the wire */
		line[2 * i + 1] = v & 0xFF;
		break;
	}
	case 24:
		if (cur_fmt->colmod == MIPI_DCS_PIXEL_FORMAT_18BIT) {
			r &= 0xFC;
			g &= 0xFC;
			b &= 0xFC;
		}
		line[3 * i] = r;
		line[3 * i + 1] = g;
		line[3 * i + 2] = b;
		break;
	case 8:
		line[i] = (r & 0xE0) | ((g & 0xE0) >> 3) | (b >> 6);
		break;
	case 4: {
		uint8_t n = ((r >> 7) << 2) | ((g >> 7) << 1) | (b >> 7);

		if (i & 1) {
			line[i / 2] = (line[i / 2] & 0xF0) | n;
		} else {
			line[i / 2] = (uint8_t)(n << 4);
		}
		break;
	}
	default:
		break;
	}
}

typedef uint32_t (*color_fn)(uint16_t x, uint16_t y, void *ctx);

static void fill_line(uint8_t *line, uint16_t x0, uint16_t y, uint16_t w, color_fn fn, void *ctx)
{
	for (uint16_t i = 0; i < w; i++) {
		put_px(line, i, fn(x0 + i, y, ctx));
	}
}

struct blit_stats {
	uint32_t bytes;
	uint32_t cycles;
};

/*
 * Write a w x h window at (x, y). With "uniform", every line is the same, so
 * one band is filled once and resent: that keeps pattern generation out of
 * the frame-rate figures.
 */
static int blit(uint16_t x, uint16_t y, uint16_t w, uint16_t h, color_fn fn, void *ctx,
		bool uniform, struct blit_stats *st)
{
	size_t lb = line_bytes(w);
	bool via_driver = prefer_driver && driver_ready && cur_fmt->pf != 0 && wr_cfg == &raw_cfg[0];
	uint32_t t0, busy = 0;
	int ret = 0;

	if (w == 0 || h == 0 || x + w > W || y + h > H) {
		return -EINVAL;
	}
	if (uniform) {
		fill_line(band, x, y, w, fn, ctx);
		for (int l = 1; l < BAND_LINES; l++) {
			memcpy(&band[l * lb], band, lb);
		}
	}
	if (!via_driver) {
		t0 = cyc_now();
		ret = raw_window(x, y, w, h);
		busy += cyc_now() - t0;
	}
	for (uint16_t by = 0; by < h && ret == 0; by += BAND_LINES) {
		uint16_t bh = MIN(BAND_LINES, h - by);

		if (!uniform) {
			for (uint16_t l = 0; l < bh; l++) {
				fill_line(&band[l * lb], x, y + by + l, w, fn, ctx);
			}
		}
		t0 = cyc_now();
		if (via_driver) {
			struct display_buffer_descriptor d = {
				.buf_size = bh * lb,
				.width = w,
				.height = bh,
				.pitch = w,
				.frame_incomplete = (by + bh) < h,
			};

			ret = display_write(disp, x, y + by, &d, band);
		} else {
			ret = panel_cmd(by == 0 ? MIPI_DCS_WRITE_MEMORY_START :
					MIPI_DCS_WRITE_MEMORY_CONTINUE, band, bh * lb);
		}
		busy += cyc_now() - t0;
	}
	if (st) {
		st->bytes = lb * h;
		st->cycles = busy;
	}
	return ret;
}

static uint32_t solid(uint16_t x, uint16_t y, void *ctx)
{
	ARG_UNUSED(x);
	ARG_UNUSED(y);
	return *(uint32_t *)ctx;
}

static const uint32_t bar_colors[8] = {
	0xFFFFFF, 0xFFFF00, 0x00FFFF, 0x00FF00, 0xFF00FF, 0xFF0000, 0x0000FF, 0x000000,
};

static uint32_t bars(uint16_t x, uint16_t y, void *ctx)
{
	ARG_UNUSED(y);
	ARG_UNUSED(ctx);
	return bar_colors[(x * 8U) / W];
}

struct grid_ctx {
	uint16_t pitch;
	uint32_t color;
};

/* Grid lines, a red centre cross, and green circles at r 232 (the 466 px edge) and r 220. */
static uint32_t grid(uint16_t x, uint16_t y, void *ctx)
{
	const struct grid_ctx *g = ctx;
	int dx = 2 * x - (W - 1), dy = 2 * y - (H - 1);	/* doubled, centre at 0 */
	int r2 = dx * dx + dy * dy;

	if (x == W / 2 || y == H / 2) {
		return 0xFF0000;
	}
	for (int r = 220; r <= 232; r += 12) {
		int lo = 2 * r - 1, hi = 2 * r + 1;

		if (r2 >= lo * lo && r2 <= hi * hi) {
			return 0x00FF00;
		}
	}
	if (x % g->pitch == 0 || y % g->pitch == 0 || x == W - 1 || y == H - 1) {
		return g->color;
	}
	return 0x000000;
}

struct area_ctx {
	uint16_t rows;
	uint32_t color;
};

static uint32_t area(uint16_t x, uint16_t y, void *ctx)
{
	const struct area_ctx *a = ctx;

	ARG_UNUSED(x);
	return y < a->rows ? a->color : 0x000000;
}

/* ---- init ------------------------------------------------------------- */

int panel_init(void)
{
	int ret;

	for (size_t i = 0; i < ARRAY_SIZE(clocks_mhz); i++) {
		raw_cfg[i] = spi.config;
		raw_cfg[i].frequency = MHZ(clocks_mhz[i]);
	}
	timing_init();
	timing_start();

	if (!gpio_is_ready_dt(&te) || !gpio_is_ready_dt(&reset) || !spi_is_ready_dt(&spi)) {
		return -ENODEV;
	}
	/* Hold reset asserted (as R8's pull-down does) until the rails are up. */
	ret = gpio_pin_configure_dt(&reset, GPIO_OUTPUT_ACTIVE);
	if (ret < 0) {
		return ret;
	}
	/* Pulled down so a dark panel does not leave the TE input floating. */
	ret = gpio_pin_configure_dt(&te, GPIO_INPUT | GPIO_PULL_DOWN);
	if (ret < 0) {
		return ret;
	}
	gpio_init_callback(&te_cb, te_isr, BIT(te.pin));
	ret = gpio_add_callback(te.port, &te_cb);
	if (ret < 0) {
		return ret;
	}
	return gpio_pin_interrupt_configure_dt(&te, GPIO_INT_EDGE_TO_ACTIVE);
}

int panel_driver_init(void)
{
	int ret;

	LOG_INF("device_init(%s): reset 150 ms low + 150 ms, C4h 80h, 36h/3Ah, 35h, 53h, "
		"51h, 63h, 11h, 29h", disp->name);
	ret = device_init(disp);
	if (ret < 0 && ret != -EALREADY) {
		return ret;
	}
	driver_ready = device_is_ready(disp);
	cur_fmt = &fmts[0];
	return driver_ready ? 0 : -EIO;
}

int panel_raw_init(void)
{
	uint8_t madctl = MIPI_DCS_ADDRESS_MODE_BGR;	/* as the driver sets for RGB565 */
	int ret;

	LOG_INF("raw init: reset 10 ms low, 120 ms wait");
	gpio_pin_set_dt(&reset, 1);
	k_msleep(10);
	gpio_pin_set_dt(&reset, 0);
	k_msleep(120);

	if (cur_fmt->bits == 24 && cur_fmt->colmod == MIPI_DCS_PIXEL_FORMAT_24BIT) {
		madctl = 0;
	}
	ret = panel_cmd1(CO5300_SPI_MODE, 0x80);
	ret = ret ? ret : panel_cmd1(MIPI_DCS_SET_ADDRESS_MODE, madctl);
	ret = ret ? ret : panel_cmd1(MIPI_DCS_SET_PIXEL_FORMAT, cur_fmt->colmod);
	ret = ret ? ret : panel_cmd(MIPI_DCS_SET_TEAR_ON, NULL, 0);
	ret = ret ? ret : panel_cmd1(MIPI_DCS_WRITE_CONTROL_DISPLAY, 0x20);
	ret = ret ? ret : panel_cmd1(MIPI_DCS_SET_DISPLAY_BRIGHTNESS, brightness);
	ret = ret ? ret : panel_cmd1(CO5300_HBM_BRIGHTNESS, 0xFF);
	if (ret) {
		return ret;
	}
	k_msleep(50);
	LOG_INF("raw init: sleep out (11h), format %s", cur_fmt->name);
	return panel_cmd(MIPI_DCS_EXIT_SLEEP_MODE, NULL, 0);
}

int panel_display_on(bool on)
{
	if (driver_ready && prefer_driver) {
		return on ? display_blanking_off(disp) : display_blanking_on(disp);
	}
	return panel_cmd(on ? MIPI_DCS_SET_DISPLAY_ON : MIPI_DCS_SET_DISPLAY_OFF, NULL, 0);
}

int panel_test_bars(void)
{
	return blit(0, 0, W, H, bars, NULL, true, NULL);
}

/* ---- shell ------------------------------------------------------------ */

static const struct {
	const char *name;
	uint32_t rgb;
} named[] = {
	{"black", 0x000000}, {"white", 0xFFFFFF}, {"red", 0xFF0000}, {"green", 0x00FF00},
	{"blue", 0x0000FF}, {"cyan", 0x00FFFF}, {"magenta", 0xFF00FF}, {"yellow", 0xFFFF00},
	{"grey", 0x808080},
};

static int parse_color(const struct shell *sh, const char *s, uint32_t *rgb)
{
	char *end;

	for (size_t i = 0; i < ARRAY_SIZE(named); i++) {
		if (strcmp(s, named[i].name) == 0) {
			*rgb = named[i].rgb;
			return 0;
		}
	}
	*rgb = strtoul(s, &end, 16);
	if (*end != '\0' || *rgb > 0xFFFFFF) {
		shell_error(sh, "colour: a name (white, red, ...) or RRGGBB hex");
		return -EINVAL;
	}
	return 0;
}

static void report(const struct shell *sh, const char *what, const struct blit_stats *st)
{
	uint32_t us = cyc_to_us(st->cycles);

	shell_print(sh, "%s: %u bytes in %u.%03u ms (%u kbit/s on the bus incl. framing)", what,
		    st->bytes, us / 1000, us % 1000, us ? (uint32_t)((uint64_t)st->bytes * 8000 / us) : 0);
}

static int cmd_info(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	shell_print(sh, "%ux%u, format %s (COLMOD %02Xh, %u bit/px), path %s, SPI %u MHz, "
		    "column offset %u, brightness %u, driver %s",
		    W, H, cur_fmt->name, cur_fmt->colmod, cur_fmt->bits,
		    (prefer_driver && cur_fmt->pf && wr_cfg == &raw_cfg[0]) ? "driver" : "raw",
		    wr_cfg->frequency / 1000000U, col_off, brightness,
		    driver_ready ? "ready" : "not initialised");
	return 0;
}

static int cmd_fill(const struct shell *sh, size_t argc, char **argv)
{
	struct blit_stats st;
	uint32_t c;

	ARG_UNUSED(argc);
	if (parse_color(sh, argv[1], &c) < 0) {
		return -EINVAL;
	}
	int ret = blit(0, 0, W, H, solid, &c, true, &st);

	if (ret == 0) {
		report(sh, "fill", &st);
	}
	return ret;
}

static int cmd_bars(const struct shell *sh, size_t argc, char **argv)
{
	struct blit_stats st;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	int ret = blit(0, 0, W, H, bars, NULL, true, &st);

	if (ret == 0) {
		report(sh, "bars", &st);
	}
	return ret;
}

static int cmd_grid(const struct shell *sh, size_t argc, char **argv)
{
	struct grid_ctx g = {.pitch = 32, .color = 0xFFFFFF};

	if (argc > 1) {
		g.pitch = CLAMP(strtoul(argv[1], NULL, 0), 2, W);
	}
	if (argc > 2 && parse_color(sh, argv[2], &g.color) < 0) {
		return -EINVAL;
	}
	return blit(0, 0, W, H, grid, &g, false, NULL);
}

static int cmd_area(const struct shell *sh, size_t argc, char **argv)
{
	struct area_ctx a = {.color = 0xFFFFFF};
	uint32_t pct = CLAMP(strtoul(argv[1], NULL, 0), 0, 100);

	if (argc > 2 && parse_color(sh, argv[2], &a.color) < 0) {
		return -EINVAL;
	}
	/* Whole rows from the top: an even row count keeps the window rules. */
	a.rows = (uint16_t)((H * pct / 100U) & ~1U);
	shell_print(sh, "%u of %u rows lit (%u %% of the square; the circle differs)", a.rows, H,
		    pct);
	return blit(0, 0, W, H, area, &a, false, NULL);
}

static int cmd_rect(const struct shell *sh, size_t argc, char **argv)
{
	struct blit_stats st;
	uint16_t x = strtoul(argv[1], NULL, 0), y = strtoul(argv[2], NULL, 0);
	uint16_t w = strtoul(argv[3], NULL, 0), h = strtoul(argv[4], NULL, 0);
	uint32_t c;

	ARG_UNUSED(argc);
	if (parse_color(sh, argv[5], &c) < 0) {
		return -EINVAL;
	}
	if ((x | y | w | h) & 1) {
		shell_warn(sh, "odd start or size: the CO5300 wants even x, y, w and h "
			   "(display-study §3.1); sending it anyway");
	}
	int ret = blit(x, y, w, h, solid, &c, true, &st);

	if (ret == -EINVAL) {
		shell_error(sh, "window outside %ux%u", W, H);
	} else if (ret == 0) {
		report(sh, "rect", &st);
	}
	return ret;
}

static int cmd_fmt(const struct shell *sh, size_t argc, char **argv)
{
	struct fmt *f = NULL;
	int ret;

	if (argc < 2) {
		for (size_t i = 0; i < ARRAY_SIZE(fmts); i++) {
			shell_print(sh, "%c %s  COLMOD %02Xh  %2u bit/px  %s",
				    &fmts[i] == cur_fmt ? '*' : ' ', fmts[i].name, fmts[i].colmod,
				    fmts[i].bits, fmts[i].pf ? "driver or raw" : "raw only");
		}
		return 0;
	}
	for (size_t i = 0; i < ARRAY_SIZE(fmts); i++) {
		if (strcmp(argv[1], fmts[i].name) == 0) {
			f = &fmts[i];
		}
	}
	if (f == NULL) {
		shell_error(sh, "unknown format; \"disp fmt\" lists them");
		return -EINVAL;
	}
	if (argc > 2) {
		f->colmod = strtoul(argv[2], NULL, 16);
	}
	if (f->pf && driver_ready && argc < 3) {
		ret = display_set_pixel_format(disp, f->pf);	/* 36h + 3Ah */
	} else {
		ret = panel_cmd1(MIPI_DCS_SET_PIXEL_FORMAT, f->colmod);
	}
	if (ret == 0) {
		cur_fmt = f;
		shell_print(sh, "COLMOD %02Xh (%s); redraw to see it", f->colmod, f->name);
	}
	return ret;
}

static int cmd_bright(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(sh);
	ARG_UNUSED(argc);
	brightness = strtoul(argv[1], NULL, 0);
	if (driver_ready) {
		return display_set_brightness(disp, brightness);	/* 51h */
	}
	return panel_cmd1(MIPI_DCS_SET_DISPLAY_BRIGHTNESS, brightness);
}

static int cmd_hbm(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(sh);
	ARG_UNUSED(argc);
	return panel_cmd1(CO5300_HBM_BRIGHTNESS, strtoul(argv[1], NULL, 0));
}

static int cmd_on(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(sh);
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	return panel_display_on(true);
}

static int cmd_off(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(sh);
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	return panel_display_on(false);
}

static int cmd_sleep(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(sh);
	ARG_UNUSED(argc);
	if (strcmp(argv[1], "in") == 0) {
		return panel_cmd(MIPI_DCS_ENTER_SLEEP_MODE, NULL, 0);
	}
	return panel_cmd(MIPI_DCS_EXIT_SLEEP_MODE, NULL, 0);
}

static int cmd_init(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	int ret = panel_raw_init();

	if (ret == 0) {
		k_msleep(CONFIG_BENCH_SLPOUT_MS);
		ret = panel_cmd(MIPI_DCS_SET_DISPLAY_ON, NULL, 0);
	}
	if (ret < 0) {
		shell_error(sh, "init: %d", ret);
	}
	return ret;
}

static int cmd_cmd(const struct shell *sh, size_t argc, char **argv)
{
	uint8_t data[16];
	size_t n = argc - 2;

	if (n > sizeof(data)) {
		shell_error(sh, "at most %u parameter bytes", (unsigned int)sizeof(data));
		return -EINVAL;
	}
	for (size_t i = 0; i < n; i++) {
		data[i] = strtoul(argv[2 + i], NULL, 16);
	}
	return panel_cmd(strtoul(argv[1], NULL, 16), data, n);
}

static int cmd_read(const struct shell *sh, size_t argc, char **argv)
{
	uint8_t buf[16];
	uint8_t cmd = strtoul(argv[1], NULL, 16);
	size_t n = argc > 2 ? CLAMP(strtoul(argv[2], NULL, 0), 1, sizeof(buf)) : 1;
	int ret = panel_read(cmd, buf, n);

	if (ret < 0) {
		return ret;
	}
	shell_fprintf(sh, SHELL_NORMAL, "%02Xh @ %u MHz:", cmd, rd_cfg->frequency / 1000000U);
	for (size_t i = 0; i < n; i++) {
		shell_fprintf(sh, SHELL_NORMAL, " %02X", buf[i]);
	}
	shell_print(sh, "");
	return 0;
}

static int set_clock(const struct shell *sh, const char *arg, const struct spi_config **cfg)
{
	uint32_t mhz = strtoul(arg, NULL, 0);

	for (size_t i = 0; i < ARRAY_SIZE(clocks_mhz); i++) {
		if (clocks_mhz[i] == mhz) {
			*cfg = &raw_cfg[i];
			return 0;
		}
	}
	shell_error(sh, "SPIM3 clocks here: 32, 16, 8, 4, 2, 1 MHz");
	return -EINVAL;
}

static int cmd_freq(const struct shell *sh, size_t argc, char **argv)
{
	if (argc > 1 && set_clock(sh, argv[1], &wr_cfg) < 0) {
		return -EINVAL;
	}
	if (argc > 2 && set_clock(sh, argv[2], &rd_cfg) < 0) {
		return -EINVAL;
	}
	shell_print(sh, "write %u MHz%s, read %u MHz", wr_cfg->frequency / 1000000U,
		    wr_cfg == &raw_cfg[0] ? "" : " (raw path: the driver runs at the DT clock)",
		    rd_cfg->frequency / 1000000U);
	return 0;
}

static int cmd_path(const struct shell *sh, size_t argc, char **argv)
{
	if (argc > 1) {
		prefer_driver = strcmp(argv[1], "raw") != 0;
	}
	shell_print(sh, "pixel writes prefer the %s path", prefer_driver ? "driver" : "raw");
	return 0;
}

static int cmd_offset(const struct shell *sh, size_t argc, char **argv)
{
	if (argc > 1) {
		col_off = strtoul(argv[1], NULL, 0);
	}
	shell_print(sh, "raw path column offset %u (the driver's is fixed at 6)", col_off);
	return 0;
}

static int cmd_te(const struct shell *sh, size_t argc, char **argv)
{
	uint32_t ms = argc > 1 ? strtoul(argv[1], NULL, 0) : 1000;
	uint32_t n, mean = 0;

	te_reset_stats();
	k_msleep(ms);
	n = te_count;
	if (n == 0) {
		shell_warn(sh, "no TE edges in %u ms: panel off or asleep, 35h not sent, or A5 open",
			   ms);
		return 0;
	}
	if (n > 1) {
		mean = cyc_to_us((uint32_t)(te_sum / (n - 1)));
	}
	shell_print(sh, "TE: %u edges in %u ms, period mean %u us (%u.%02u Hz), min %u, max %u us",
		    n, ms, mean, mean ? 1000000U / mean : 0,
		    mean ? (100000000U / mean) % 100U : 0, cyc_to_us(te_min), cyc_to_us(te_max));
	return 0;
}

static int cmd_fps(const struct shell *sh, size_t argc, char **argv)
{
	static const uint32_t pair[2] = {0xFF0000, 0x0000FF};
	uint32_t frames = argc > 1 ? strtoul(argv[1], NULL, 0) : 30;
	uint16_t w = argc > 2 ? strtoul(argv[2], NULL, 0) : W;
	uint16_t h = argc > 3 ? strtoul(argv[3], NULL, 0) : H;
	bool sync = !(argc > 4 && strcmp(argv[4], "nosync") == 0);
	uint32_t busy = 0, worst = 0, bytes = 0;
	uint32_t t_start, t_all, te0;
	int ret = 0;

	w = MIN(w & ~1U, W);
	h = MIN(h & ~1U, H);
	if (w == 0 || h == 0 || frames == 0) {
		return -EINVAL;
	}
	uint16_t x = ((W - w) / 2) & ~1U, y = ((H - h) / 2) & ~1U;

	te_reset_stats();
	te0 = te_count;
	t_start = cyc_now();
	for (uint32_t i = 0; i < frames && ret == 0; i++) {
		struct blit_stats st;

		if (sync) {
			k_sem_reset(&te_sem);
			if (k_sem_take(&te_sem, K_MSEC(200)) != 0) {
				shell_warn(sh, "no TE within 200 ms: running unsynced");
				sync = false;
			}
		}
		ret = blit(x, y, w, h, solid, (void *)&pair[i & 1], true, &st);
		busy += st.cycles;
		bytes += st.bytes;
		worst = MAX(worst, st.cycles);
	}
	t_all = cyc_to_us(cyc_now() - t_start);
	if (ret < 0) {
		shell_error(sh, "write failed: %d", ret);
		return ret;
	}
	uint32_t avg = cyc_to_us(busy / frames);
	uint32_t fps10 = t_all ? (uint32_t)((uint64_t)frames * 10000000U / t_all) : 0;

	shell_print(sh, "%u frames of %ux%u %s, %s, SPI %u MHz, %s path", frames, w, h,
		    cur_fmt->name, sync ? "TE-synced" : "unsynced", wr_cfg->frequency / 1000000U,
		    (prefer_driver && driver_ready && cur_fmt->pf && wr_cfg == &raw_cfg[0]) ?
		    "driver" : "raw");
	shell_print(sh, "  %u.%01u fps over %u ms; write mean %u.%03u ms, worst %u.%03u ms",
		    fps10 / 10U, fps10 % 10U, t_all / 1000,
		    avg / 1000, avg % 1000, cyc_to_us(worst) / 1000, cyc_to_us(worst) % 1000);
	/* Synced, one TE edge per frame means each write fit in one refresh period. */
	shell_print(sh, "  %u bytes per frame, %u kbit/s while writing, %u TE edges for %u frames",
		    bytes / frames, busy ? (uint32_t)((uint64_t)bytes * 8000 / cyc_to_us(busy)) : 0,
		    te_count - te0, frames);
	return 0;
}

SHELL_STATIC_SUBCMD_SET_CREATE(disp_cmds,
	SHELL_CMD(info, NULL, "Format, path, clock, offset, brightness", cmd_info),
	SHELL_CMD(init, NULL, "Raw re-init: reset, C4h, 36h, 3Ah, 35h, 53h, 51h, 11h, 29h", cmd_init),
	SHELL_CMD(on, NULL, "Display on (29h)", cmd_on),
	SHELL_CMD(off, NULL, "Display off (28h)", cmd_off),
	SHELL_CMD_ARG(sleep, NULL, "sleep in|out: 10h / 11h", cmd_sleep, 2, 0),
	SHELL_CMD_ARG(bright, NULL, "bright <0-255>: 51h", cmd_bright, 2, 0),
	SHELL_CMD_ARG(hbm, NULL, "hbm <0-255>: 63h, high-brightness level", cmd_hbm, 2, 0),
	SHELL_CMD_ARG(fmt, NULL, "fmt [rgb565|rgb888|rgb666|rgb332|rgb111] [COLMOD hex]",
		      cmd_fmt, 1, 2),
	SHELL_CMD_ARG(fill, NULL, "fill <colour>: solid full screen", cmd_fill, 2, 0),
	SHELL_CMD(bars, NULL, "Eight colour bars", cmd_bars),
	SHELL_CMD_ARG(grid, NULL, "grid [pitch] [colour]: grid, centre cross, r 220/232 circles",
		      cmd_grid, 1, 2),
	SHELL_CMD_ARG(area, NULL, "area <percent> [colour]: lit rows from the top, for current "
		      "vs content", cmd_area, 2, 1),
	SHELL_CMD_ARG(rect, NULL, "rect <x> <y> <w> <h> <colour>: partial-window write",
		      cmd_rect, 6, 0),
	SHELL_CMD_ARG(fps, NULL, "fps [frames] [w] [h] [nosync]: TE-synced frame rate",
		      cmd_fps, 1, 4),
	SHELL_CMD_ARG(te, NULL, "te [ms]: count TE edges, period mean/min/max", cmd_te, 1, 1),
	SHELL_CMD_ARG(cmd, NULL, "cmd <hex> [hex ...]: raw command with parameters",
		      cmd_cmd, 2, 16),
	SHELL_CMD_ARG(read, NULL, "read <hex> [n]: raw register read (03h) on SIO1",
		      cmd_read, 2, 1),
	SHELL_CMD_ARG(freq, NULL, "freq [write MHz] [read MHz]: raw-path SPI clocks",
		      cmd_freq, 1, 2),
	SHELL_CMD_ARG(path, NULL, "path [driver|raw]: which path pixel writes prefer",
		      cmd_path, 1, 1),
	SHELL_CMD_ARG(offset, NULL, "offset [cols]: raw-path column offset", cmd_offset, 1, 1),
	SHELL_SUBCMD_SET_END);

SHELL_CMD_REGISTER(disp, &disp_cmds, "CO5300 AMOLED bench commands", NULL);
