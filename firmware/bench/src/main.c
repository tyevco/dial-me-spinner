/*
 * Rev B bench firmware: the 1.75 in CO5300 AMOLED shield and the NFC bench
 * boards on an nRF52840-DK. See firmware/bench/README.md for the commands and
 * docs/rev-b-bench.md for the boards.
 */
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include "bench.h"

LOG_MODULE_REGISTER(bench, LOG_LEVEL_INF);

int main(void)
{
	int ret;

	LOG_INF("dial-me-spinner rev B bench firmware");

	ret = power_init();
	if (ret < 0) {
		LOG_ERR("power rails: %d", ret);
		return 0;
	}
	ret = panel_init();
	if (ret < 0) {
		LOG_ERR("panel: %d", ret);
	}
	ret = touch_init();
	if (ret < 0) {
		LOG_WRN("touch: %d", ret);
	}
	ret = nfc_init();
	if (ret < 0) {
		LOG_WRN("nfc: %d", ret);
	}

	if (IS_ENABLED(CONFIG_BENCH_AUTO_POWERUP)) {
		ret = power_up();
		if (ret == 0) {
			(void)panel_test_bars();
		}
	} else {
		LOG_INF("panel unpowered (CONFIG_BENCH_AUTO_POWERUP=n): run \"power up\"");
	}

	LOG_INF("ready: type \"help\", or \"power\", \"disp\", \"te\", \"touch\", \"nfc\"");
	return 0;
}
