#!/usr/bin/env bash
# Interference check for dial_spinner.scad (OpenSCAD 2021.01, CGAL).
# For every stationary part: (rotor swept envelope ∩ part) must be empty, and
# for the base parts: (base part ∩ floating assembly moved down by STOP_TRAVEL)
# must be empty.  Prints CLEAR / CLASH per pair.  Usage: ./check_clashes.sh [margin_mm]
set -u
cd "$(dirname "$0")"
M=${1:-0}
OUT=$(mktemp -d)
names=(base_cup base_board battery antenna guide_pins fa_lower_plate spindle lower_spacer \
       spindle_hub main_board detent@click detent@free light_box oled_bracket oled_glass top_cover)
run() {  # mode item
  local f="$OUT/$1_$2.stl"
  local log
  log=$(openscad -o "$f" -D "view=\"clash_geom\"" -D "clash_mode=\"$1\"" -D "clash_item=$2" \
        -D "clash_margin=$M" -D 'fn_big=96' -D 'show_knurl=false' dial_spinner.scad 2>&1)
  if echo "$log" | grep -qiE "top level object is empty|No top level geometry"; then
    echo "CLEAR  $1  ${names[$2]}"
  elif [ -s "$f" ]; then
    vol=$(python3 - "$f" <<'PY'
import sys,struct
# signed volume of an ASCII STL
v=0.0; tri=[]
for ln in open(sys.argv[1]):
    ln=ln.strip()
    if ln.startswith('vertex'):
        tri.append(tuple(map(float,ln.split()[1:4])))
        if len(tri)==3:
            (a,b,c)=tri; tri=[]
            v+=(a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
print(f"{abs(v):.3f}")
PY
)
    echo "CLASH  $1  ${names[$2]}  overlap ≈ ${vol} mm^3"
  else
    echo "??     $1  ${names[$2]}  ($(echo "$log" | tail -1))"
  fi
}
export -f run; export OUT M
{
  for i in $(seq 0 15); do echo "rotor $i"; done
  for i in 0 1 2 3 4; do echo "press $i"; done
} | xargs -P 4 -L 1 bash -c 'names=(base_cup base_board battery antenna guide_pins fa_lower_plate spindle lower_spacer spindle_hub main_board detent@click detent@free light_box oled_bracket oled_glass top_cover); '"$(declare -f run)"'; run $0 $1' | sort -k2,2 -k3
rm -rf "$OUT"
