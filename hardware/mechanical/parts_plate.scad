// Overview of the exported printable parts (renders/parts.png). Run export_stl.sh first.
names = ["base_cup", "top_cover", "light_box", "diffuser", "fa_lower_plate", "rotor_carrier",
         "detent_carriage", "oled_bracket", "spindle_hub", "lower_spacer", "bearing_retainer",
         "stepper_saddle", "carriage_rail"];
pos = [[0, 0], [80, 0], [160, 0], [240, 0], [0, -80], [80, -80], [150, -68], [205, -75],
       [245, -68], [278, -68], [262, -100], [150, -100], [185, -100]];
cols = ["#3a3e45", "#2b2d31", "#262626", "#d8d6cc", "#5f6b7a", "#4b5563", "#9a9a9a", "#4d4d4d",
        "#7c6f5a", "#e0dccf", "#4b5563", "#9c8f7a", "#9a9a9a"];
for (i = [0:len(names) - 1]) translate([pos[i][0], pos[i][1], 0]) {
    color(cols[i]) import(str("stl/", names[i], ".stl"));
    color("#111111") translate([0, i < 6 ? -42 : -19, 0])
        linear_extrude(0.3) text(names[i], size = i < 6 ? 5 : 2.6, halign = "center", font = "DejaVu Sans");
}
