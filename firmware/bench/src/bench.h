/*
 * Rev B bench firmware: shared declarations.
 */
#ifndef BENCH_H_
#define BENCH_H_

#include <stdbool.h>
#include <stdint.h>
#include <zephyr/devicetree.h>

#define DISP_NODE DT_NODELABEL(co5300)
#define USER_NODE DT_PATH(zephyr_user)

/* power.c */
int power_init(void);
int power_vbat(bool on);
int power_vci_en(bool on);
bool power_vbat_get(void);
bool power_vci_en_get(void);
/* Full bring-up: VBAT, VCI_EN, reset + init, sleep-out wait, display on. */
int power_up(void);
/* Display off, sleep in, VCI_EN low, VBAT off. */
int power_down(void);

/* panel.c */
int panel_init(void);
/* First init through the Zephyr driver (device_init on the deferred node). */
int panel_driver_init(void);
/* Re-init after a power cycle: the driver can only be initialised once. */
int panel_raw_init(void);
int panel_cmd(uint8_t cmd, const uint8_t *data, size_t len);
int panel_display_on(bool on);
int panel_test_bars(void);

/* touch.c */
int touch_init(void);

/* nfc.c */
int nfc_init(void);

#endif /* BENCH_H_ */
