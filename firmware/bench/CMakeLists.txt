# Rev B bench firmware: AMOLED shield and NFC on an nRF52840-DK.
cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(dial_bench)

target_sources(app PRIVATE
	src/main.c
	src/power.c
	src/panel.c
	src/touch.c
	src/nfc.c
)
