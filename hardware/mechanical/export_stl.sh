#!/usr/bin/env bash
# Export every printable / machined part of dial_spinner.scad to stl/ (binary STL, on the bed).
# rotor_ring, spindle, spindle_hub, lower_spacer and cap_ring are turned / cut metal parts, and these
# STLs are only the assembly views' mesh: no tolerances, threads or finish, and no CNC vendor takes an
# STL anyway. Order those five from step/*.step plus drawings/*.pdf, which drawgen.py builds from the
# same constants and which do carry the fits, threads, knurl and general tolerance.
set -eu
cd "$(dirname "$0")"
mkdir -p stl
parts=(base_cup top_cover light_box diffuser fa_lower_plate rotor_carrier magnet_shim magnet_shim_blank detent_carriage \
       link_plate oled_bracket stepper_saddle carriage_rail spindle spindle_hub lower_spacer cap_ring \
       rotor_ring)
export_one() {
  openscad -o "stl/$1.stl" --export-format binstl -D 'view="part"' -D "part=\"$1\"" \
    -D 'fn_big=128' -D 'fn_mid=48' -D 'fn_small=24' -D 'show_knurl=false' dial_spinner.scad 2>&1 \
    | grep -E "WARNING|ERROR" | sed "s/^/[$1] /" || true
}
export -f export_one
printf '%s\n' "${parts[@]}" | xargs -P 4 -I{} bash -c 'export_one {}'
ls -l stl
