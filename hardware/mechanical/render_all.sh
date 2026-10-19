#!/usr/bin/env bash
# Regenerate every render, STL and calculation output of hardware/mechanical/.
# Needs OpenSCAD 2021.01, xvfb-run, python3 + numpy + matplotlib.  ~4 min on 4 cores.
set -eu
cd "$(dirname "$0")"
mkdir -p renders stl
S="xvfb-run -a openscad --colorscheme=Tomorrow"
$S -o renders/assembly.png     --imgsize=1200,900 --camera=118,-136,104,0,0,17 -D 'view="assembly"' dial_spinner.scad
$S -o renders/exploded.png     --imgsize=1200,900 --camera=380,-390,380,25,20,96 -D 'view="exploded"' dial_spinner.scad
$S -o renders/board_bottom.png --imgsize=1200,900 --camera=0,-30,-165,0,0,28 -D 'view="board_bottom"' dial_spinner.scad
$S -o renders/clash.png        --imgsize=1200,900 --camera=55,-105,-30,0,-2,25 -D 'view="clash"' -D 'fn_big=96' dial_spinner.scad
$S -o renders/section.png      --imgsize=1600,620 --camera=172,0,21,0,0,21 --projection=o -D 'view="section"' dial_spinner.scad
$S -o renders/section_xz.png   --imgsize=1200,900 --camera=0,150,18,0,0,18 --projection=o -D 'view="section_xz"' dial_spinner.scad
./export_stl.sh
$S -o renders/parts.png        --imgsize=1400,800 --camera=135,-380,520,135,-50,0 parts_plate.scad
python3 calcs.py > calcs_output.txt
./check_clashes.sh 0 > clash_report.txt
echo "--- near misses (rotor envelope grown 0.3 mm) ---" >> clash_report.txt
./check_clashes.sh 0.3 >> clash_report.txt
cat clash_report.txt
