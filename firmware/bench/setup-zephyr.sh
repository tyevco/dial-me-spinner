#!/usr/bin/env bash
# Reproduce the bench firmware toolchain: west in a venv, a minimal Zephyr
# workspace, and the Zephyr SDK's arm-zephyr-eabi toolchain only.
#
# Run inside Linux (WSL Ubuntu 24.04 on the project laptop):
#   bash firmware/bench/setup-zephyr.sh
# Everything lands under $ZEPHYR_WS (default ~/zephyrproject). Nothing is
# installed system-wide. Sources: github.com/zephyrproject-rtos and PyPI only.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="${ZEPHYR_WS:-$HOME/zephyrproject}"
SDK_VER="1.0.1"          # zephyr/SDK_VERSION at v4.5.0-rc3
SDK_DIR="$WS/zephyr-sdk-$SDK_VER"
SDK_URL="https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v$SDK_VER"

mkdir -p "$WS"

# 1. Python venv with west, cmake and ninja (PyPI wheels, no apt packages).
if [ ! -x "$WS/.venv/bin/west" ]; then
	python3 -m venv "$WS/.venv"
	"$WS/.venv/bin/pip" install --upgrade pip
	"$WS/.venv/bin/pip" install west cmake ninja
fi
# shellcheck disable=SC1091
. "$WS/.venv/bin/activate"

# 2. Minimal workspace from this directory's west.yml.
mkdir -p "$WS/manifest"
cp "$HERE/west.yml" "$WS/manifest/west.yml"
if [ ! -d "$WS/.west" ]; then
	(cd "$WS" && west init -l manifest)
fi
(cd "$WS" && west update --narrow -o=--depth=1)
pip install -r "$WS/zephyr/scripts/requirements-base.txt"

# 3. Zephyr SDK: the minimal bundle plus the arm toolchain only.
if [ ! -d "$SDK_DIR/gnu/arm-zephyr-eabi" ] && [ ! -d "$SDK_DIR/arm-zephyr-eabi" ]; then
	DL="$(mktemp -d)"
	(
		cd "$DL"
		curl -fsSLO "$SDK_URL/sha256.sum"
		curl -fsSLO "$SDK_URL/zephyr-sdk-${SDK_VER}_linux-x86_64_minimal.tar.xz"
		grep " zephyr-sdk-${SDK_VER}_linux-x86_64_minimal.tar.xz\$" sha256.sum | sha256sum -c -
		tar -xf "zephyr-sdk-${SDK_VER}_linux-x86_64_minimal.tar.xz" -C "$WS"
	)
	rm -rf "$DL"
	# setup.sh fetches toolchain_gnu_linux-x86_64_arm-zephyr-eabi from the same
	# release and registers the SDK's CMake package (-c).
	(cd "$SDK_DIR" && ./setup.sh -t arm-zephyr-eabi -c)
fi

cat <<MSG

Zephyr workspace ready in $WS. Build the bench firmware with:
  . $WS/.venv/bin/activate
  west build -b nrf52840dk/nrf52840 -d ~/build/bench <repo>/firmware/bench
MSG
