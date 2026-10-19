#!/usr/bin/env bash
# Export every printable part of dial_spinner.scad to stl/ (binary STL, on the bed).
set -eu
cd "$(dirname "$0")"
mkdir -p stl
parts=(base_cup top_cover light_box diffuser fa_lower_plate rotor_carrier detent_carriage \
       oled_bracket spindle_hub lower_spacer bearing_retainer stepper_saddle carriage_rail)
export_one() {
  openscad -o "stl/$1.stl" --export-format binstl -D 'view="part"' -D "part=\"$1\"" \
    -D 'fn_big=128' -D 'fn_mid=48' -D 'fn_small=24' -D 'show_knurl=false' dial_spinner.scad 2>&1 \
    | grep -E "WARNING|ERROR|Simple:" | sed "s/^/[$1] /" || true
}
export -f export_one
printf '%s\n' "${parts[@]}" | xargs -P 4 -I{} bash -c 'export_one {}'
ls -l stl
