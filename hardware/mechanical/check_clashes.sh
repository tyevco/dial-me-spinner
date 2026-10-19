#!/usr/bin/env bash
# Interference check for dial_spinner.scad (OpenSCAD 2021.01, CGAL). Usage: ./check_clashes.sh [margin_mm]
# margin 0: rotor envelope, press/rest travel and FA-internal pairs; margin > 0: rotor envelope only.
set -eu
cd "$(dirname "$0")"
exec python3 clash_check.py "$@"
