/*
 * NFC Type 2 tag on the nRF52840's NFCT, for the coil plate and base read-range
 * tests (docs/rev-b-bench.md §2, "Phones").
 *
 * The usual route is nrfxlib's nfc_t2t library, but nrfxlib is part of the nRF
 * Connect SDK, not of the Zephyr tree this app builds on. So this is a minimal
 * read-only Type 2 tag on nrfx_nfct (hal_nordic), which is: the NFCT hardware
 * does anticollision and CRC, and the app answers READ (30h) and HALT (50h).
 * That is all a phone needs to read an NDEF message from a static tag.
 * Nothing else is answered (no WRITE, no NTAG GET_VERSION), so a phone sees a
 * plain read-only Type 2 tag.
 *
 * Wiring: the plate's J2 to the DK's NFC connector (P0.09/P0.10). The DK
 * leaves UICR.NFCPINS in NFC mode.
 */
#include <stdlib.h>
#include <string.h>

#include <zephyr/drivers/clock_control/nrf_clock_control.h>
#include <zephyr/irq.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/shell/shell.h>

#include <nrfx_nfct.h>

#include "bench.h"

LOG_MODULE_REGISTER(nfc, LOG_LEVEL_INF);

#define T2T_READ 0x30
#define T2T_HALT 0x50
#define T2T_DATA_BYTES 128			/* CC size field = 128 / 8 */
#define T2T_MEM_BYTES (16 + T2T_DATA_BYTES)	/* 4 header blocks + data area */
#define NDEF_URI_HTTPS 0x04

static const char default_uri[] = "github.com/tyevco/dial-me-spinner";

static uint8_t mem[T2T_MEM_BYTES];
static uint8_t rx_buf[16];
static uint8_t tx_buf[16];
static uint8_t nfcid1[NRFX_NFCT_NFCID1_DOUBLE_SIZE];

static bool running;
static volatile uint32_t n_field, n_select, n_read, n_other, n_rxerr;
static const struct device *const hfclk = DEVICE_DT_GET(DT_NODELABEL(hfclk));

static void rx_next(void)
{
	nrfx_nfct_data_desc_t d = {.p_data = rx_buf, .data_size = sizeof(rx_buf)};

	(void)nrfx_nfct_rx(&d);
}

static void handle_frame(const nrfx_nfct_evt_rx_frameend_t *f)
{
	const uint8_t *p = f->rx_data.p_data;

	if (f->rx_status != 0 || f->rx_data.data_size == 0) {
		n_rxerr++;
		rx_next();
		return;
	}
	if (p[0] == T2T_READ && f->rx_data.data_size >= 2) {
		/* 16 bytes from block p[1], rolling over at the end of memory. */
		uint32_t off = (uint32_t)p[1] * 4U;

		for (int i = 0; i < 16; i++) {
			tx_buf[i] = mem[(off + i) % sizeof(mem)];
		}
		nrfx_nfct_data_desc_t d = {.p_data = tx_buf, .data_size = 16};

		n_read++;
		if (nrfx_nfct_tx(&d, NRF_NFCT_FRAME_DELAY_MODE_WINDOWGRID) != 0) {
			rx_next();
		}
		return;
	}
	if (p[0] == T2T_HALT) {
		nrfx_nfct_init_substate_force(NRFX_NFCT_ACTIVE_STATE_SLEEP);
		return;
	}
	/* Anything else: no answer, as a read-only tag that ignores it. */
	n_other++;
	rx_next();
}

static void nfct_handler(const nrfx_nfct_evt_t *evt)
{
	switch (evt->evt_id) {
	case NRFX_NFCT_EVT_FIELD_DETECTED:
		n_field++;
		/* HFXO is held on while the tag runs, so activate straight away. */
		nrfx_nfct_state_force(NRFX_NFCT_STATE_ACTIVATED);
		break;
	case NRFX_NFCT_EVT_SELECTED:
		n_select++;
		rx_next();
		break;
	case NRFX_NFCT_EVT_RX_FRAMEEND:
		handle_frame(&evt->params.rx_frameend);
		break;
	case NRFX_NFCT_EVT_TX_FRAMEEND:
		rx_next();
		break;
	case NRFX_NFCT_EVT_FIELD_LOST:
	default:
		break;
	}
}

/* Lay out the tag memory: UID, lock bytes, CC, then an NDEF TLV with one URI record. */
static int build_tag(const char *uri)
{
	size_t ul = strlen(uri);
	size_t payload = 1 + ul;			/* URI prefix code + text */
	size_t rec = 4 + payload;			/* short record header */
	uint8_t *d = &mem[16];

	if (3 + rec > T2T_DATA_BYTES - 1) {
		return -E2BIG;
	}
	memset(mem, 0, sizeof(mem));
	/* Block 0-2: UID0-2, BCC0 = 88h ^ UID0-2, UID3-6, BCC1, internal, lock 0, lock 1. */
	mem[0] = nfcid1[0];
	mem[1] = nfcid1[1];
	mem[2] = nfcid1[2];
	mem[3] = 0x88 ^ nfcid1[0] ^ nfcid1[1] ^ nfcid1[2];
	memcpy(&mem[4], &nfcid1[3], 4);
	mem[8] = nfcid1[3] ^ nfcid1[4] ^ nfcid1[5] ^ nfcid1[6];
	/* Block 3: capability container. NDEF 1.0, data area size, read-only access. */
	mem[12] = 0xE1;
	mem[13] = 0x10;
	mem[14] = T2T_DATA_BYTES / 8;
	mem[15] = 0x0F;
	/* NDEF TLV */
	d[0] = 0x03;
	d[1] = (uint8_t)rec;
	d[2] = 0xD1;				/* MB ME SR, TNF well-known */
	d[3] = 0x01;				/* type length */
	d[4] = (uint8_t)payload;
	d[5] = 'U';
	d[6] = NDEF_URI_HTTPS;
	memcpy(&d[7], uri, ul);
	d[2 + rec] = 0xFE;			/* terminator TLV */
	return 0;
}

int nfc_init(void)
{
	nrfx_nfct_config_t cfg = {
		/* RX/TX events to forward; field, select and error events always come. */
		.rxtx_int_mask = NRFX_NFCT_EVT_RX_FRAMEEND | NRFX_NFCT_EVT_TX_FRAMEEND,
		.cb = nfct_handler,
		.irq_priority = 2,
	};
	int ret;

	IRQ_CONNECT(DT_IRQN(DT_NODELABEL(nfct)), 2, nrfx_isr, nrfx_nfct_irq_handler, 0);
#if NRF_ERRATA_STATIC_CHECK(52, 79) || NRF_ERRATA_STATIC_CHECK(52, 190)
	/* nrfx_nfct's field-detect workaround runs on TIMER4 (NRFX_NFCT_CONFIG_TIMER_INSTANCE_ID). */
	IRQ_CONNECT(TIMER4_IRQn, 2, nrfx_isr, nrfx_nfct_workaround_timer_handler, 0);
#endif

	ret = nrfx_nfct_init(&cfg);
	if (ret < 0) {
		return ret;
	}

	/* A 7-byte NFCID1: the FICR's NFC tag header (5Fh = Nordic, then a device-unique part). */
	ret = nrfx_nfct_nfcid1_default_bytes_get(nfcid1, sizeof(nfcid1));
	if (ret < 0) {
		return ret;
	}
	nrfx_nfct_param_t p = {
		.id = NRFX_NFCT_PARAM_ID_NFCID1,
		.data.nfcid1 = {.p_id = nfcid1, .id_size = sizeof(nfcid1)},
	};

	ret = nrfx_nfct_parameter_set(&p);
	if (ret < 0) {
		return ret;
	}
	p.id = NRFX_NFCT_PARAM_ID_SEL_RES;
	p.data.sel_res_protocol = 0;	/* Type 2: no ISO-DEP */
	ret = nrfx_nfct_parameter_set(&p);
	if (ret < 0) {
		return ret;
	}
	return build_tag(default_uri);
}

static int cmd_start(const struct shell *sh, size_t argc, char **argv)
{
	int ret;

	if (running) {
		nrfx_nfct_disable();
	} else {
		/* The NFCT needs HFXO when activated; hold it for the whole test. */
		ret = nrf_clock_control_request_sync(hfclk, NULL, K_MSEC(100));
		if (ret < 0) {
			shell_error(sh, "HFXO request: %d", ret);
			return ret;
		}
	}
	ret = build_tag(argc > 1 ? argv[1] : default_uri);
	if (ret < 0) {
		shell_error(sh, "URI too long for the %d-byte data area", T2T_DATA_BYTES);
		/* HFXO is held here either way: requested above, or still held from the last start. */
		(void)nrf_clock_control_release(hfclk, NULL);
		running = false;
		return ret;
	}
	n_field = n_select = n_read = n_other = n_rxerr = 0;
	nrfx_nfct_enable();
	running = true;
	shell_print(sh, "Type 2 tag on: https://%s (UID %02X%02X%02X%02X%02X%02X%02X; HFXO held on)",
		    argc > 1 ? argv[1] : default_uri, nfcid1[0], nfcid1[1], nfcid1[2], nfcid1[3],
		    nfcid1[4], nfcid1[5], nfcid1[6]);
	return 0;
}

static int cmd_stop(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	if (running) {
		nrfx_nfct_disable();
		(void)nrf_clock_control_release(hfclk, NULL);
		running = false;
	}
	shell_print(sh, "tag off");
	return 0;
}

static int cmd_status(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	shell_print(sh, "tag %s, field now %s; since start: %u fields, %u selects, %u reads, "
		    "%u other frames, %u RX errors",
		    running ? "on" : "off", (running && nrfx_nfct_field_check()) ? "on" : "off",
		    n_field, n_select, n_read, n_other, n_rxerr);
	return 0;
}

static int cmd_dump(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	for (size_t b = 0; b < sizeof(mem) / 4; b++) {
		shell_print(sh, "  block %2u: %02X %02X %02X %02X", (unsigned int)b, mem[4 * b],
			    mem[4 * b + 1], mem[4 * b + 2], mem[4 * b + 3]);
	}
	return 0;
}

SHELL_STATIC_SUBCMD_SET_CREATE(nfc_cmds,
	SHELL_CMD_ARG(start, NULL, "start [uri without https://]: run the Type 2 tag",
		      cmd_start, 1, 1),
	SHELL_CMD(stop, NULL, "Stop the tag and release HFXO", cmd_stop),
	SHELL_CMD(status, NULL, "Field, select and read counters", cmd_status),
	SHELL_CMD(dump, NULL, "Print the tag memory by block", cmd_dump),
	SHELL_SUBCMD_SET_END);

SHELL_CMD_REGISTER(nfc, &nfc_cmds, "NFC Type 2 tag (NFCT, P0.09/P0.10)", NULL);
