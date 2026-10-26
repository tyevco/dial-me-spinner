/*
 * Panel power rails and the bring-up order.
 *
 * Order (docs/rev-b-bench.md, docs/display-study.md §3.5):
 *   1. DISP_VBAT_EN high: U1 (TPS22917) connects VBAT_IN to the panel's VBAT.
 *   2. DISP_VCI_EN high: the tail's power chip (BV6802W) starts.
 *   3. Reset and CO5300 init (the Zephyr driver the first time).
 *   4. Sleep-out wait, then display on.
 * Power-down runs it backwards: display off, sleep in, VCI_EN low, VBAT off.
 *
 * VCI, IOVCC and TP_VDD are not switched: they come from the DK's VDD through
 * the J5 shunt, so the CO5300 logic stays powered while VBAT and VCI_EN cycle.
 */
#include <stdlib.h>
#include <string.h>

#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/shell/shell.h>

#include "bench.h"

LOG_MODULE_REGISTER(power, LOG_LEVEL_INF);

static const struct gpio_dt_spec vbat_en = GPIO_DT_SPEC_GET(USER_NODE, disp_vbat_en_gpios);
static const struct gpio_dt_spec vci_en = GPIO_DT_SPEC_GET(USER_NODE, disp_vci_en_gpios);

static bool driver_done;
static bool panel_up;

int power_init(void)
{
	int ret;

	if (!gpio_is_ready_dt(&vbat_en) || !gpio_is_ready_dt(&vci_en)) {
		return -ENODEV;
	}
	/* Both start low, matching the R2/R9 pull-downs that held them through reset. */
	ret = gpio_pin_configure_dt(&vbat_en, GPIO_OUTPUT_INACTIVE);
	if (ret == 0) {
		ret = gpio_pin_configure_dt(&vci_en, GPIO_OUTPUT_INACTIVE);
	}
	return ret;
}

int power_vbat(bool on)
{
	LOG_INF("DISP_VBAT_EN (P1.02) %s", on ? "on" : "off");
	return gpio_pin_set_dt(&vbat_en, on);
}

int power_vci_en(bool on)
{
	LOG_INF("DISP_VCI_EN (P1.05) %s", on ? "on" : "off");
	return gpio_pin_set_dt(&vci_en, on);
}

bool power_vbat_get(void)
{
	return gpio_pin_get_dt(&vbat_en) > 0;
}

bool power_vci_en_get(void)
{
	return gpio_pin_get_dt(&vci_en) > 0;
}

int power_up(void)
{
	int64_t t0 = k_uptime_get();
	int ret;

	LOG_INF("bring-up 1/4: VBAT switch");
	ret = power_vbat(true);
	if (ret < 0) {
		return ret;
	}
	k_msleep(CONFIG_BENCH_VBAT_SETTLE_MS);

	LOG_INF("bring-up 2/4: VCI_EN (+%lld ms)", k_uptime_get() - t0);
	ret = power_vci_en(true);
	if (ret < 0) {
		return ret;
	}
	k_msleep(CONFIG_BENCH_VCI_SETTLE_MS);

	LOG_INF("bring-up 3/4: reset and CO5300 init (+%lld ms)", k_uptime_get() - t0);
	if (!driver_done) {
		ret = panel_driver_init();
		driver_done = true;	/* device_init() runs once, pass or fail */
	} else {
		ret = panel_raw_init();
	}
	if (ret < 0) {
		LOG_ERR("panel init failed: %d", ret);
		return ret;
	}

	LOG_INF("bring-up 4/4: sleep-out wait %d ms, display on (+%lld ms)",
		CONFIG_BENCH_SLPOUT_MS, k_uptime_get() - t0);
	k_msleep(CONFIG_BENCH_SLPOUT_MS);
	ret = panel_display_on(true);
	if (ret < 0) {
		return ret;
	}
	panel_up = true;
	LOG_INF("bring-up done in %lld ms", k_uptime_get() - t0);
	return 0;
}

int power_down(void)
{
	int ret;

	LOG_INF("power-down: display off (28h), sleep in (10h)");
	ret = panel_display_on(false);
	if (ret == 0) {
		ret = panel_cmd(0x10, NULL, 0);
	}
	if (ret < 0) {
		LOG_WRN("panel commands failed (%d); cutting the rails anyway", ret);
	}
	/* DCS: sleep-in takes up to 120 ms to stop the panel's charge pumps. */
	k_msleep(120);
	(void)power_vci_en(false);
	k_msleep(10);
	(void)power_vbat(false);
	panel_up = false;
	return 0;
}

static int parse_onoff(const struct shell *sh, const char *arg, bool *on)
{
	if (strcmp(arg, "on") == 0 || strcmp(arg, "1") == 0) {
		*on = true;
	} else if (strcmp(arg, "off") == 0 || strcmp(arg, "0") == 0) {
		*on = false;
	} else {
		shell_error(sh, "expected on or off");
		return -EINVAL;
	}
	return 0;
}

static int cmd_status(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	shell_print(sh, "DISP_VBAT_EN %s, DISP_VCI_EN %s, panel %s",
		    power_vbat_get() ? "on" : "off", power_vci_en_get() ? "on" : "off",
		    panel_up ? "up" : "down");
	return 0;
}

static int cmd_up(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	int ret = power_up();

	if (ret < 0) {
		shell_error(sh, "bring-up failed: %d", ret);
	}
	return ret;
}

static int cmd_down(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(sh);
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	return power_down();
}

static int cmd_vbat(const struct shell *sh, size_t argc, char **argv)
{
	bool on;

	ARG_UNUSED(argc);
	if (parse_onoff(sh, argv[1], &on) < 0) {
		return -EINVAL;
	}
	if (!on) {
		panel_up = false;
	}
	return power_vbat(on);
}

static int cmd_vci(const struct shell *sh, size_t argc, char **argv)
{
	bool on;

	ARG_UNUSED(argc);
	if (parse_onoff(sh, argv[1], &on) < 0) {
		return -EINVAL;
	}
	if (!on) {
		panel_up = false;
	}
	return power_vci_en(on);
}

static int cmd_cycle(const struct shell *sh, size_t argc, char **argv)
{
	int off_ms = argc > 1 ? atoi(argv[1]) : 500;

	(void)power_down();
	shell_print(sh, "rails off for %d ms", off_ms);
	k_msleep(off_ms);
	return cmd_up(sh, 1, argv);
}

SHELL_STATIC_SUBCMD_SET_CREATE(power_cmds,
	SHELL_CMD(status, NULL, "Rail and panel state", cmd_status),
	SHELL_CMD(up, NULL, "Bring-up: VBAT, VCI_EN, reset + init, sleep-out, display on", cmd_up),
	SHELL_CMD(down, NULL, "Display off, sleep in, VCI_EN off, VBAT off", cmd_down),
	SHELL_CMD_ARG(cycle, NULL, "cycle [off_ms]: down, wait, up", cmd_cycle, 1, 1),
	SHELL_CMD_ARG(vbat, NULL, "vbat on|off: DISP_VBAT_EN alone (U1)", cmd_vbat, 2, 0),
	SHELL_CMD_ARG(vci, NULL, "vci on|off: DISP_VCI_EN alone", cmd_vci, 2, 0),
	SHELL_SUBCMD_SET_END);

SHELL_CMD_REGISTER(power, &power_cmds, "Panel power rails and bring-up", NULL);
