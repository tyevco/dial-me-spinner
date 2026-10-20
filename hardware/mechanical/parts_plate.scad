// Overview of the exported parts (renders/parts.png). Run export_stl.sh first.
names = ["base_cup", "top_cover", "light_box", "diffuser", "fa_lower_plate", "rotor_carrier", "rotor_ring",
         "detent_carriage", "link_plate", "oled_bracket", "stepper_saddle", "carriage_rail",
         "spindle", "spindle_hub", "lower_spacer", "cap_ring"];
pos = [[0, 0], [80, 0], [160, 0], [240, 0], [0, -80], [80, -80], [320, 0], [150, -66], [180, -66], [215, -75],
       [250, -66], [278, -66], [150, -100], [185, -100], [215, -110], [250, -105]];
cols = ["#3a3e45", "#2b2d31", "#262626", "#d8d6cc", "#5f6b7a", "#4b5563", "#9aa3ad", "#9a9a9a", "#c8b560", "#4d4d4d",
        "#9c8f7a", "#9a9a9a", "#9aa3ad", "#b8962e", "#b8962e", "#9aa3ad"];
for (i = [0:len(names) - 1]) translate([pos[i][0], pos[i][1], 0]) {
    color(cols[i]) import(str("stl/", names[i], ".stl"));
    color("#111111") translate([0, i < 7 ? -42 : -14, 0])
        linear_extrude(0.3) text(names[i], size = i < 7 ? 5 : 2.4, halign = "center", font = "DejaVu Sans");
}
