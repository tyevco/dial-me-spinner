#!/usr/bin/env bash
# Export every printable / machined part of dial_spinner.scad to stl/ (binary STL, on the bed).
# rotor_ring, spindle, spindle_hub, lower_spacer and cap_ring are turned / cut metal parts: the STL is a
# drawing aid only. It carries no tolerances, threads or finish (ring knurl, spindle Ø8 h6 and M4x0.5,
# hub M2 tappings): quote and machine from mechanical sections 5 and 13, not from the mesh.
set -eu
cd "$(dirname "$0")"
mkdir -p stl
parts=(base_cup top_cover light_box diffuser fa_lower_plate rotor_carrier detent_carriage link_plate \
       oled_bracket stepper_saddle carriage_rail spindle spindle_hub lower_spacer cap_ring rotor_ring)
export_one() {
  openscad -o "stl/$1.stl" --export-format binstl -D 'view="part"' -D "part=\"$1\"" \
    -D 'fn_big=128' -D 'fn_mid=48' -D 'fn_small=24' -D 'show_knurl=false' dial_spinner.scad 2>&1 \
    | grep -E "WARNING|ERROR" | sed "s/^/[$1] /" || true
}
export -f export_one
printf '%s\n' "${parts[@]}" | xargs -P 4 -I{} bash -c 'export_one {}'
ls -l stl
