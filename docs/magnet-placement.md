# Magnet placement: decision, budget, and the prototype that settles it

Status: research complete, **nothing ordered**. Written against commit `cfa0a18` (48 magnets in a
printed PA12 shim, not in blind pockets milled into the 316L ring).

The model changes in §8 have since been made, so §§1–6 are the reasoning and §7 is the work that is
still outstanding. Three things were corrected while implementing it, and they are marked **[corrected
in build]** where they appear:

* The recess and the shim OD had been one constant (`SHIM_RO`), which is the whole reason the
  zero-clearance fit in §3 B existed. They are now two: `RECESS_RO` (the recess turned in the steel,
  unchanged at Ø62.00) and `SHIM_RO` (the plate's own turned OD, Ø61.90, later Ø61.88 — see below).
* §8 claimed that shrinking the shim OD takes the outer web from 0.950 to 1.000 mm. It does not —
  shrinking the OD *reduces* the outer web. The 0.985 figure is the **inner** web, which improves
  because the bore shrinks from Ø2.10 to Ø2.03.
* This report was written while the branch carrying `cfa0a18` was in flight, and it concluded from
  `git ls-remote --heads` that the work had never been pushed. It had: PR #8 merged as `dc96515`, and
  the branch was deleted on merge, which is what the listing was showing.

A second review of the built design found four more, also marked **[corrected in build]**:

* **The pattern callout contradicted the eccentricity finding.** §7's Ø0.60 PLTZF lets the pattern sit
  0.30 mm off centre, a 0.59° 1/rev encoder error — 2.4× the budget §6 itself sets. It is Ø0.05 now, which
  is cheap because the bores are cut from the OD in one setup.
* **The mandrel fix cannot work and is not needed.** The plate's ID is left as printed, ±0.3, so a mandrel
  in the Ø54 ring ID locates nothing; and the 1.58× figure was computed for a Ø61.80 plate with 0.40 mm of
  clearance. What actually centres the pattern is the recess fit — and the ring drawing gave the recess Ø
  **no tolerance**, so it fell to ISO 2768-m, ±0.3. It is Ø62.00 +0.02/0, coaxial to the Ø54 H7 bore within
  Ø0.02, and the three terms total 0.227°, 0.91× the budget (`docs/mechanical.md` §5).
* **The thermal paragraph used the wrong channel.** Uniform growth is tangentially neutral, as §6 says, but
  it lands in the 0.05–0.08 mm OD clearance, not a 0.30 mm channel. PA12-GF fits (0.052 mm at 60 °C, with
  the OD now Ø61.88); unfilled PA12 and SLA resin do not. That settles item 7a's material: PA12-GF only.
* **A 0.01 bin is the wrong width.** The bore is floor + 0.04 +0.01/0, so worst-case clearance is 0.025
  whatever the bin width; a 0.01 bin of a normal ±0.05 lot yields ~45 of 200, short of 48. The bin is 0.02,
  chosen as the densest of the *measured* lot, and the clearance is 0.010–0.025 (not 0.015–0.037).

The numbers in §§2–6 are **not** re-derived here. Where one of them is soft — and the most important
one is — the report says so in place.

---

## 1. Recommendation

**Print the shim blank solid and machine the 48 bores.** Change `stl/magnet_shim.stl` to a plain Ø62/Ø54 × 1.95 annulus with no holes, then drill-and-ream 48 × **Ø2.03 +0.01/0** through, on a programmed 48-position polar pattern at R 29.000, holding the blank on a mandrel in the Ø54 ID — the same post-print-machining pattern the repo already uses twice on the rotor carrier (`docs/mechanical.md:324`, `docs/assembly.md:694`). Turn the OD to Ø61.90 in the same setup **[corrected in build: Ø61.88 +0/−0.02, and the pattern held to it within Ø0.05]**. Pair it with a diameter-sorted magnet lot.

It is recommended for one reason, and it is not accuracy per se: **a printed hole cannot locate a magnet, and the bore must locate the magnet.**

- The prior analysis's step 3d is the finding that survives everything: a clearance bore that *contains* the magnet cannot meet the budget, independently of what the plate is made of.
- JLC3DP publishes **±0.3 mm hole tolerance** for SLA 9600, MJF PA12 and SLS PA12 alike, with the stated bias that "holes will shrink and become smaller" (`jlc3dp.com/help/article/3D-Printing-Design-Guideline`). A Ø2.10 nominal therefore spans Ø1.80–2.40. **At the low end it refuses a Ø1.95 magnet entirely.** At the high end the float is 0.225 mm.
- The repo's own rule — "Measure your batch and set the pocket to max Ø + 0.03–0.05" (`docs/mechanical.md:376`) — was written for a flat-bottom **milled steel pocket** and is unorderable on a printed hole by a factor of 10–15.
- At the published tolerance **there is no printed bore nominal that both admits the magnet and locates it.** Ø2.35 guarantees admission and allows 0.350 mm of float (7× the budget). This is arithmetic, not a judgement call.

What the machining buys beyond position: the 0.95 mm bore-to-recess web stops being a *printed* thin wall (it becomes a machined web in a part printed solid, which dissolves the open risk at `docs/mechanical.md:319-320`); the OD becomes a real fit instead of a nominal-zero-clearance cylinder; and Ø2.03 on a sorted 1.99–2.00 bin puts the radial clearance *c* at 0.015–0.037 mm, inside the magnetostatic **self-centring window** (below, §5).

Cost: $0.32 for the blank plus one 48-hole secondary operation. **That operation's price at qty 1 is the single unquoted number in this recommendation** and is the first thing to get (§7, P2).

### Runner-up: a 3-pole stationary detent head

Replace the single Ø3×2 N52 in the detent carriage with **three Ø1.59×1.59 N52 discs at 15° spacing, same polarity** (or three at 7.5° with alternating faces, which halves the head width). Nothing on the rotor changes.

This is the only option found that makes the requirement *disappear* rather than paying to meet it. Each detent's angular position is currently set at gain **0.730 by ONE magnet** — not averaged over 48 (`gains 0.730 / 0.133 / 0.138, sum 1.001`, an identity that must hold and does). A multi-pole head spreads that gain: measured `gmax` falls to 0.2921, so the per-magnet tangential budget multiplies by **2.50×** → 0.125 mm, which the as-built design already meets. It also multiplies the **axial** crown budget by the same factor, which is the one channel the drilled bore does not touch, and it *reduces* free-mode cogging (1.37 vs 2.64 µN·m) and eddy drag (0.06×).

It is the runner-up, not the recommendation, because of one number: slider thrust goes from **0.98 N to 1.12 N (+14 %)**, taking the margin on the VSM08102's 0.78 N rating from 0.80× to 0.70× and on the 0.93 N best-case delivery MD-4 measured from 0.95× to 0.83×. Architecture risk **R4 is already open** at 0.79× (`docs/mechanical.md:459-470`), and +14 % is spending the project's scarcest resource on a problem the drilled bore solves for free.

### What would change my mind

| If this turns out true | Then |
|---|---|
| R4 forces a different actuator anyway (MD-4 already says 0.8–1.15 N demand vs 0.93 N best-case delivery) | The K=3 head becomes nearly free and **should lead**, because it retires the axial channel and the lot-sorting requirement too. Build the force-neutral Ø1.3-class variant (F_MAG 0.279 N vs the 0.281 N baseline) if max click torque can fall 16.5 → 11.3 mN·m. |
| The 48-hole drill/ream quote lands above ~$30/unit at qty 1 | K=3 head wins on cost (<$2 of parts, no vendor, no MOQ, no lead time). |
| Measured local plate scatter is ≤ 0.02 mm **and** a print vendor will contract to a Ø0.07 position callout | Keep printing the bores; machine nothing. Nobody publishes such a callout today (§8). |
| The 2AFC panel (§7, P4) shows σ = 0.04 mm is undetectable on the real rotor | The committed design is acceptable as drawn once the three assembly blockers are fixed. Do nothing else. |
| The pin-gauge ladder shows any printed bore refuses a magnet | Machining is not a choice, it is mandatory, and the recommendation hardens. |

---

## 2. The placement budget and its derivation

### 2.1 The number

| Channel | Budget (max per magnet) | Set by | Hardness |
|---|---|---|---|
| **Tangential** | **0.050 mm** (band 0.035–0.15) | detent feel | mechanics hard, threshold **soft** |
| Radial | 0.30 mm | detent torque uniformity | second order, not a design constraint |
| Axial (crown) | 0.04 mm | detent feel | reproduces the existing ±0.03 flushness spec |
| Polarity | zero | go/no-go | hard |

Equivalently, if specified statistically: process **σ_t ≤ 0.017 mm** (3σ over 48 magnets). Put the basis in the drawing note so it is not quietly re-tightened.

### 2.2 The mechanical half — solid

One magnet displaced tangentially by *d* shifts its own detent well at gain 0.730 and its two repelling neighbours at 0.133 / 0.138. With `T1 = 16.5 mN·m` (`docs/mechanical.md:410`) and `k = N_DET × T1 = 0.396 N·m/rad` (`hardware/mechanical/calcs.py:616`):

```
peak |dT| = T1 × 24 × 0.730 × d / R_t
          = 16.5 × 24 × 0.730 × d / 29.0
          = 9.97 N·mm per mm of tangential error
```

Two independently written models agree: **9.97** (closed form, from the published gains) and **9.60** (magnetic-charge pole-sheet model), a 4 % spread. The pole-sheet model was validated six ways against committed repo numbers before any sensitivity was taken — sensor field 15.919 / 13.443 mT vs the repo's 15.9 / 13.4 (`docs/firmware.md:938`, 0.1–0.3 %); detent peak 16.25 mN·m vs the 16.5 LUT point with `calcs.py:622`'s stated 2–5 % R_t-30→29 caveat; the 10 %-per-0.1 mm gap slope (`docs/mechanical.md:294`, ~1 %); and the two `[verifier]`-supplied force terms in `calcs.py:817` that nobody in the repo had derived — F_MAG 0.29 N (model 0.281) and N_V 0.70 N (model 0.696). **This half of the derivation is trustworthy.**

### 2.3 The psychophysical half — soft, and this is where the old number was wrong

Primary source is the Purdue HIRL / Ford work, and the **2008 IEEE Transactions on Haptics journal version** (Tan, Yang, Pizlo, Buttolo, Johnston, 1(2):96–107) supersedes the 2003 EuroHaptics conference paper everything was previously built on — 6 subjects instead of 5, three experiments instead of two, and a regression showing the threshold-vs-spatial-period law has a log-log slope of **exactly −1 for every individual participant** (their Table 2). Our 15° detent period is **inside** the measured 2.8–180° range, so the interpolation carries essentially no extrapolation risk. The earlier framing that "it rests on one 2003 conference paper interpolated outside its measured range" is wrong on both counts.

Threshold line: `threshold = c × P` with `c = 0.0393–0.0480 N·mm per degree of spatial period`. At P = 15°: **0.59–0.72 N·mm**.

Three readings of the same data:

| Reading | Threshold | Budget | Verdict |
|---|---|---|---|
| Relative (1–3 % of peak) | 0.17–0.50 N·mm | 0.017–0.052 mm | **Reject** — assumes threshold ∝ reference torque (exponent 1.0) |
| Absolute, as measured at 15° | 0.59–0.72 N·mm | 0.059–0.072 mm | optimistic (no reference-torque correction) |
| Absolute, scaled 30 → 16.5 N·mm | 0.42–0.51 N·mm | **0.042–0.051 mm** | **use this** |

The scaling exponent is **0.576**, derived from the only study that ever varied reference torque for a rotary control: Woodruff & Helson 1967 found the relative threshold fell from 12.6 % to 4.4 % as the reference rose from 8.35 to 100 equivalent-gram-metres, i.e. absolute threshold ~ R^0.576. `(16.5/30)^0.576 = 0.709`. Read second-hand from the quotation in Yang 2003 — **the original was not read, and this exponent is the single hinge between 0.035 mm and 0.050 mm.**

**That exponent is the whole correction.** Under exponent 1.0 the arithmetic reproduces the old 0.035 mm exactly (0.0325–0.0397). Under 0.576 it gives 0.042–0.051. The prior derivation used the relative reading, which is the special case of an exponent nobody has measured.

### 2.4 How soft, and in which direction

Every unresolved correction **loosens** the number except one:

- **Grip radius (2.3–5×, UNSOURCED).** Tan does not state the radius at which participants held the knob — only "between the fingerpad of the thumb and one side of the middle phalange of the index finger". If detection is force-limited at the skin, as Kuehner's diameter result implies (detection threshold rose 2.08× for a 1.8× knob-diameter increase, while the JND did not move at all), our 35 mm knurled rim loosens the budget by that factor.
- **Single-cycle burst vs continuous sinusoid (up to 3.8×, UNSOURCED).** Tan presented a continuous ripple over a 90° sweep; our defect is one cycle. Spatial summation means a burst needs more amplitude.
- **Noise width vs peak deviation (2–3.5×).** Yang Exp. I's 0.5–1.5 N·mm is the *width* of a uniform noise distribution, not a peak. Comparing a peak |dT| to a distribution width is apples-to-oranges in the looser direction.
- **Rotor inertia masking: ~1×, and this is now SOURCED, not estimated.** Tan et al. 2008 ran the experiment (their Fig. 11): thresholds were **unaffected** until the apparatus inertia exceeded ~2.3× its original value, with significant deviation only at 6.1×. Reflected at the grip point our rotor is 92.2 g, equivalent to 1.0–4.5× their baseline depending on the unstated grip radius — i.e. at or barely outside the band they verified as having no effect. Mechanically: the in-well natural frequency is **f_n = (1/2π)√(k/I) = 9.43 Hz**, reproducing the repo's tabulated 9.2 Hz (`docs/mechanical.md:410`) to 2.5 %. Below 9.43 Hz the rotor is detent-**stiffness** dominated and the profile reaches the finger intact, so there is no masking at a 0.2 rev/s deliberate turn and little at 1 rev/s. **The earlier guess that inertia masking is a large loosening factor is not supported.**
- **Speed: settled, it does not matter.** Tan Exp. III turned the same switch at 2× different rates and found "no systematic difference"; the same data do *not* align when converted to temporal frequency, which is the proof that perception here is spatially determined.
- **Felt-shoe friction: does not raise the threshold.** Both source experiments measured their thresholds *on top of* a 30 N·mm constant torque offset. Our shoe is 1.3–1.9 N·mm (`docs/mechanical.md:522`) — a DC term **16–23× smaller** than the one they resolved 0.11 N·mm against. The worry that Coulomb friction is not a pure DC offset in a reversing pass is correct in principle and does not bite: within one detent pass the velocity does not reverse. The *real* friction risk is different and the literature names it — Knowles & Sheridan 1966 found preference falls with friction and viscous is preferred over stick-slip, so a felt pad that judders makes the rotor feel worse while leaving the scatter exactly where it was.
- **The one correction pointing TIGHTER, and unsourced:** a user turns the rotor many times, and repeated exposure to one repeating defect should lower the threshold. This is why the number stays at 0.050 and not 0.10 despite three loosening corrections being available. Anyone arguing for 0.10 mm has to deal with this term.

### 2.5 Detection is not annoyance — and the product cares about annoyance

**No published figure exists** for the level at which a user calls a rotary torque-profile defect objectionable. Searched: TU Darmstadt / bedienhaptik, Reisinger (TU Munich / BMW), MacLean's group, ISO 9241-910/920. Bounds instead:

- Kuehner et al. (World Haptics 2011) measured both on one rig: detection threshold 0.13 mN·m·s (20 mm knob) / 0.27 (36 mm), JND ≈ 20 % of a 2 mN·m·s standard = 0.4. **Same-apparatus DT→JND step = 1.5–3.1×.**
- Reisinger's dissertation measured the discrimination threshold for a rotary control's detent *amplitude*: x50 % = **20 %** (σ 4 %), shape-independent, and his own footnote frames it as a production tolerance. That is 40× looser than our per-magnet sensitivity, but it is a different task (two whole controls compared from memory) and must not be read as a within-revolution ripple threshold.
- Tan et al. 2008 state in their own discussion that preference tasks behave differently and show large individual variability — primary-source acknowledgement that the question is open.
- **ISO 9241-920:2024 contains nothing usable.** Its scope covers tactile/haptic encoding, object design, layout and interaction techniques; no rotary-control detent uniformity requirement appears in the scope or any reachable description. Full text paywalled, so this is "no requirement found", not "none exists". Nobody should spend more time here.

**Working figure: annoyance ≈ 1–3× detection, i.e. 0.10–0.25 mm.** This is a reasoned bound, not a measured ratio, and it is the single largest remaining uncertainty in the budget. At 0.10 mm the committed design passes as drawn.

### 2.6 The harmonic-resolved budget (a diagnostic, not the spec)

From the primary source's own period scaling (`threshold ∝ period^1.025`, fitted to Yang Exp. II's endpoints and reproducing its own relative figures to 3 %):

| m (spatial order) | period | budget |
|---|---|---|
| 1 (eccentricity) | 360° | 1.30 mm |
| 2 (ovality) | 180° | 0.64 mm |
| 4 | 90° | 0.31 mm |
| 8 | 45° | 0.154 mm |
| 12 | 30° | 0.102 mm |

**Use max\|dt\| as the spec and this table only as a diagnostic** — it is what tells a global-shrink or ovality problem apart from a local-scatter problem on a measured part, which a single max number cannot do. Two honest caveats: it assumes the single-magnet torque sensitivity applies per harmonic, which was not validated against a magnetostatic model; and the table's anchor at m=24 is inconsistent with the separate (correct) finding that the m=24 **alternating** mode `dt_i = A·(−1)^i` is a *gauge mode* — with the 0.730/0.133/0.138 gains every one of the 24 wells shifts by the identical 0.459A, a uniform rotation of the detent grid that calibration step (c) removes. Do not read the table at m=24.

**Gauge modes to project out of any measurement:** m=0 (rigid rotation) and m=24-alternating. Both are feel-neutral; spending stimulus or tolerance on either is waste.

### 2.7 What the firmware can and cannot absorb

The encoder is a **spectator** in this tolerance, by 4.7×, and the repo's §5 text overstates it three ways:

- The claimed "4.74° electrical" per 0.10 mm is right as that magnet's own displacement in electrical degrees but **is not the encoder's error**: two magnets make one electrical period, so the measured phase moves by only 0.542 of it — **2.57° electrical / 0.107° mechanical**. Overstated by 1.84×.
- The comparison against §14's 3.5° XZX skew is the wrong comparison on three counts: that skew is **speed-dependent** (0.12° electrical at a 1 rev/s hand turn, not 3.5°), `docs/mechanical.md:911` already says firmware corrects it as a function of speed, and it is **common-mode** across all 48 poles — which is exactly what the pole-averaged LUT removes.
- "absorb it into a 48-entry LUT" (`docs/mechanical.md:315`) is wrong three ways: the LUT is **64** entries, it is indexed by electrical angle and explicitly "averaged over all poles" so it is structurally incapable of holding 48 per-magnet corrections, and the step that *could* — the 24×16 per-pole map — is gated on the fingerprint lock, which `docs/firmware.md:1193` marks "optional, TVP" with the plain statement "Until locked, only (a) and (c) apply, which gives about ±0.25° mechanical." **±0.25° mechanical = 0.233 mm** is the correct unlocked encoder budget.

**Provably not calibratable:** detent well positions and per-detent torque. The actuator has exactly one degree of freedom — the carriage's radial offset, one global strength for all 24 detents (`docs/mechanical.md:405-406`). There is no per-detent authority anywhere in the machine, which is why feel binds and nothing else does.

---

## 3. Three defects that outrank the whole tolerance question

None of these is in `docs/mechanical.md` §15's 21-item prototype checklist, and each can stop a build.

**(A) The committed bore may refuse the magnet.** Ø2.10 against a published ±0.3 mm hole tolerance spans Ø1.80–2.40; Ø1.80 does not admit a Ø1.95 magnet. Independent corroboration: Ø3 mm holes on an HP MJF 4200 in PA12 matched nominal in only one of four build orientations, going oval with up to ~10 % reduction elsewhere (PMC8398662) — scaled to Ø2.10 that is Ø1.89, a refusal. Counter-evidence honestly reported: Ø14 and Ø30 holes on an MJF 5210 deviated only 0.21–1.43 % (PMC13457958), but at 14–30 mm those are not small-hole data. **The probability shape at Ø2 is UNSOURCED** — no vendor or paper publishes it, and JLC3DP never states whether ±0.3 mm is a 3σ, a typical, or a limit.

**(B) The shim may not seat in the recess.** `dial_spinner.scad:169` puts a Ø62.00 shim into a Ø62.00 +0.02/0 recess (`docs/mechanical.md:297`) — **nominally zero clearance**, against JLC3DP's own minimum assembly clearance of 0.2 mm (SLA) to 0.2–0.4 mm (MJF/SLS). On the measured global-scale distribution for SLS PA12 (mean −0.094 %, σ 0.104 %, range −0.390 % to +0.130 % over 404 CMM fits) a Ø62 nominal prints Ø61.76–62.08, so the positive tail is **0.06–0.08 mm of diametral interference**. A shim that does not seat breaks the magnets-bottom-on-steel datum that sets the entire 1.0 mm detent gap — far worse than a loose fit.

**(C) The 0.95 mm web is under minimum for every process at this footprint, not merely under a recommendation.** `docs/mechanical.md:319` cites "0.8 mm hard minimum / 1.2 mm recommended". Neither is the applicable row. JLC3DP's current table is indexed by part footprint: SLA 1.0 mm at 50×50 rising to 1.5 at 100×100; MJF and SLS 1.5 mm at 50×50 rising to 2.0. A Ø62 part sits between those rows, so 0.95 mm is **1.05× under for SLA and 1.58× under for MJF/SLS**. The repo's 0.8 and 1.2 are the 10×10 rows. The recommendation dissolves this by making the web machined, not printed.

**(D) Not a defect but a resolution needed:** BOM item 7a names "MJF PA12 or SLS PA12-GF" and records the price as a **9600 SLA resin** quote (`docs/mechanical.md:838`). Those are different processes with different published tolerances (±0.2 vs ±0.3 mm envelope, 1.0 vs 1.5 mm wall), and 9600's **heat deflection temperature is 59 °C** — which puts the shim *below* the magnets' own 60 °C limit (`docs/mechanical.md:378`), making it the rotor's thermal weak point. The repo already bakes PCBAs at 70–75 °C (`docs/assembly.md:350`); a 59 °C part must stay out of that oven. The rotor mass table books the shim as PA12-GF at 1.37 g (`docs/mechanical.md:882`), which would also need recomputing.

---

## 4. Decision table

Per-magnet tangential error, worst case, against the **0.050 mm** budget. "As-built" = plate hole position + the magnet's float inside the bore, summed rather than RSS'd, because the magnet is magnetically driven to one bore wall (§5).

| Option | Tangential (worst case) | Cost qty 1 | Cost qty 100 | Lead time | What it breaks | Rotor inertia |
|---|---|---|---|---|---|---|
| **Drilled/reamed printed blank + sorted lot** ★ RECOMMENDED | **0.036–0.066 mm** (machine position 0.02–0.05 + self-centred park 0.016) | $0.32 blank + 48-hole op, **UNQUOTED** | blank $0.32 + amortised op | 48–120 h print + 1 setup | nothing; **relieves** the 0.95 mm web risk and the Ø62 jam | 0 % |
| **K=3 multi-pole head** (runner-up) | budget × **2.50** → 0.125 mm; needs the bore fixed too | < $2 of discs + carriage reprint | same | days (if D11-N52 in stock) | **+14 % slider thrust** on R4 at 0.79×; 2.8° of keep-out margin left at 15° spacing; full click 16.5 → 15.3 mN·m (−7 %) | 0 % |
| K=2 head from 12 BOM spares | budget × **1.74** → 0.087 mm | **$0** (spares; deletes item 6) | $0 | zero parts to order | +13 % thrust; DRV5032 home field 60.8 → 4.2 mT | 0 % |
| Ground/sorted magnets + matched reamed bore | **0.0200 mm** float *[corrected from 0.0175]* + plate position | $37 for ~200 pcs *[corrected from $12–15/60 pcs]* | lower | 2–6 wk (CN, unquoted) or $250 min + 7–9 wk (US) | nothing | **+0.019 %** *[corrected from 0.000 %]* |
| Committed printed shim, unchanged | **0.12–0.17 mm** (plate E[max] 0.056–0.092 + float 0.075) = 2.4–3.3× over | $0.32 | $0.32 | 48–120 h | may not assemble (§3 A/B/C) | 0 % |
| Open bore to Ø2.35 only (assembles, doesn't locate) | 0.350 mm = 7× over | $0 | $0 | immediate | web 0.95 → 0.825 mm | −0.076 % |
| 316L reamed metal shim | 0.045–0.075 mm *[corrected from 0.032; RSS of two maxima is invalid]* | $45–55 (re-derived from the repo's own $18.96 pocket-machining delta) | < $30 | 1–2 wk | 304 cold-work magnetism risk at the bore wall, 48/rev, not calibratable; swarf in 48 bores | **+5.50 to +5.62 %** (clears the 35 s gate) |
| Revert to 48 milled pockets | 0.025 mm position *[corrected from 0.020, from the repo's own pre-commit ±0.05° callout]*; **0.079 mm as-built** (bore float unchanged) | +$18.64 net *[corrected from $18.96]* | unsourced | same vendor | scraps a $52.49 ring instead of a $0.32 shim; depth must be 2.20 not 2.05 or axial fails | **+5.6 %** *[corrected from +3.3 %; the 1.192e-4 baseline already netted the pockets]* |
| One-piece 48-pole bonded ring | 0.0375 mm (RLS AM at D 62) — **passes at 0.050** | ~$20k tooling + $4.4k fixture | $0.22/pc at 10 k | 8–12 wk + MOQ 500–5000 | polarity and axial scatter **cease to exist**; but see §6 | +3.2 to +3.4 % *[corrected: spin-down 34.92 s, not 35.33–35.49 s]* |

---

## 5. The self-centring finding, which is why Ø2.03 is the right bore

The clearance is not pure float. In a complete alternating array a magnet sees a net **inward radial pull of 7.82–7.85 mN** and a **destabilising tangential stiffness of +0.127 N/mm**. Below a critical clearance the field parks the magnet hard against the inner bore wall and the whole clearance is consumed **radially**, where sensitivity is second order (`dT1/T1 = −0.111 d²`, i.e. −0.09 % at 0.10 mm) and no well shifts at all.

Corrected numbers *(the original candidate's 9.25 mN, "constant to within 0.2 %", and c_crit 0.058 mm were all wrong — the pull varies ±21–24 % across the clearance disc, and evaluating it at the inner wall where the magnet actually sits moves the threshold)*:

| | ideal complete array | under the documented two-mask cure |
|---|---|---|
| c_crit | **0.047–0.048 mm** | **0.037–0.040 mm** |
| park \|dt\| at c = 0.050 | 0.013 mm | 0.032 mm |
| park \|dt\| at c = 0.055 | 0.026 mm | 0.039 mm — **fails the old budget** |

**Gate: c ≤ 0.037 mm**, i.e. bore ≤ (min measured magnet Ø + 0.075 mm diametral). A Ø2.03 +0.01/0 bore on a diameter-sorted 1.99–2.00 bin gives c = 0.015–0.025 — inside the window by construction, and it admits the whole bin. **[corrected in build]** The bin is 0.02 wide (1.99–2.01, c = 0.010–0.025), chosen from the measured lot: a 0.01 bin does not yield 48 from 200.

Two honest limits on this mechanism: it is a **necessary condition, not a locator**, and it covers at most 24 of 48 magnets as the build is written. Mask A's 24 same-polarity magnets see +1.4 mN *outward* with 26× weaker tangential stiffness, so they park on the outer wall and their position is set by the dispenser, not the field. Placing all 48 before any cure restores c_crit to 0.0485 but defeats the polarity masks' reason for existing.

---

## 6. Dead ends — do not re-walk these

**Ruled out by magnetics or by a hard constraint:**

- **Aluminium shim.** `docs/assembly.md` §10.1 step 3 prices a rotating aluminium web at 0.13–1.6 N·mm of eddy drag against ~0.15 N·mm of bearing friction — up to 10× the whole friction budget. An independent calculation for a 1.95 mm Al 6061 annulus at r 27–31 gives **0.917 mN·m at 10 rev/s, 6.1× the budget**, taking the 35.3 s spin-down to roughly 5 s. Even 0.2 mm of aluminium is 63 % of the budget. Copper is 1.66× worse. Brass looks pre-approved because the BOM uses it for screws and spacers — but those are **stationary**; `docs/mechanical.md:329` prices a C360 brass *ring* at "about 11× the eddy drag".
- **Steel keeper plate under the magnets during cure.** Backwards. A μ=∞ plate on one pole face produces a *same-sign* image, so the neighbour force falls only 0.3 % (66.83 → 66.60 mN) while the tangential instability gets 22 % **worse** and the useful inward pull drops 5 %. Peeling a loaded shim off it is a 48 × 1.47 N = 70 N operation.
- **Let the magnets self-space magnetically.** Quantified and actively negative: a magnet between its two *attracting* neighbours sits at an **unstable** equilibrium, `d²U/du² = −132 N/m`, giving 9.9 mN of destabilising force at 0.075 mm against a magnet weight of 0.46 mN — a factor of 21. Pass 1 is weakly self-centring; pass 2 is actively self-**de**centring. The float therefore **saturates** rather than distributing mildly, which is why the as-built error is a worst-case sum.
- **Assemble unmagnetised blanks, magnetise the finished track.** Four independent kills: the patent literature puts ~5 mm as the hard pole-pitch limit for wire-threaded multipole fixtures against our 3.79 mm; no vendor stocks unmagnetised NdFeB discs; a PA12 carrier cannot sit in a fixture's pole structure and N52 is capped at 60 °C; and it fixes the force channel, not position.
- **Tapered or conical bores.** Centre perfectly in plane and convert diameter error into axial seating error: `dz = dD/(2 tan α)` is ±0.142 mm at a 10° half-angle for ±0.05 mm of diameter — 3.5× the 0.04 mm crown budget — and holds the magnet off the steel floor that is the gap datum.
- **Flexure fingers, crush ribs, trilobular bores.** No room: 0.95 mm of wall radially, and a tangentially-acting feature maps diameter error straight back into tangential error. Also, all of them zero the float term and leave the plate's position error untouched, so none can pay while the plate is printed.
- **Fine-pitch purchased scales (RLS 2 mm poles, AS5311/AS5304 2.4 mm, optical).** An alternating track's field falls as `exp(−2πz/λ)` with λ = 2 × pitch. Our λ = 7.59 mm at z = 3.10 gives 0.0768; a 2 mm-pole ring gives 0.0077 — **a 10× loss** — and RLS's own curves stop at 1.6 mm ride height against our 3.13 mm sensor gap. **The achievable air gap scales with the pole pitch**: you cannot buy a fine vendor-accurate scale and keep this gap stack.
- **A second magnetic track of any kind.** No radial room: the recess is r 27.0–31.0, Ø61 would leave 0.45 mm walls (unmanufacturable), and past Ø63.2 the felt shoe lands on plastic.
- **Every mA-class alternative sensor** (AS5047P 15 mA, IPS2200 8.4–12 mA, AEDR-8300 up to 23 mA, MA600 7.5 mA, iC-MU ~48 mA) against a 4.2 mA fidget-dark total, and **none has a µA-class wake-on-rotation**, so the TMAG5273 stays regardless and all of them are purely additive.
- **A second streamed TMAG5273.** The nRF52840 exposes TWIM0 and TWIM1 only; TWIM0 is dedicated and PPI drives a single ADDRESS register. The zero-CPU chain streams exactly one sensor.

**Ruled out because they fix the wrong term:**

- **Adhesive as a restraint during cure.** Off by three to five orders of magnitude: shearing a 0.05 mm film of DP420 at its published 20,000–50,000 cP gives ~11 N·s/m, so the 66.8 mN one-sided force crosses the entire clearance in **0.8–8 ms** against a 15–30 minute work life. A 500 Pa·s thixotropic paste buys 92 ms. The useful corollary: "drift during cure" is not the failure mode — the magnet reaches its final position within milliseconds of placement.
- **Cure shrinkage.** 1.7 % linear on a 0.05 mm film is **0.85 µm**, 2.4 % of the budget. Even 10 % would stay inside.
- **Adhesive and PA12 CTE / uniform thermal growth.** An isotropic in-plane scale factor maps (R, θ) → ((1+e)R, θ): **every magnet moves radially and none moves tangentially**, exactly. All of the shim's axisymmetric growth lands in the radial direction (0.049 mm for PA12-GF over 22→60 °C). Adhesive CTE contributes 0.12 µm.
- **Tightening the shim-to-recess fit for feel.** A bulk eccentricity is a 1/rev error; measured directly, a rigid 0.10 mm translation perturbs the profile 1.12 % of peak against 7.93 % for an equal pure-tangential 1/rev error — a 7× attenuation — and the harmonic table allows 1.30 mm at m=1. **But** see the encoder finding below.
- **A fully epoxy-bonded PA12 shim to the steel floor.** Hard dead end: the free radial mismatch at r 31 over 22→60 °C is 0.052–0.158 mm, which in a 0.05 mm glue line is **104–316 % shear strain** against EA 9466's 3 % elongation. The joint cracks on the first thermal cycle.

**Refuted candidates (listed so nobody revives them as written):**

- **PCB as a bonding jig** — FATAL. The seated magnet protrudes into the FR4 guide by only **0.05 mm of its 2.00 mm length** (MAG_H 2.00 − SHIM_PLATE_T 1.95), so the jig guides the magnet during descent and releases it at the one moment that matters. It also blocks the clamp-plate flushness press and needs two 24-hole boards, not one, because the masks exist for polarity staging.
- **Photo-etched locating plate (as the accuracy carrier)** — FATAL, same 0.05 mm engagement problem, plus its ±0.010 mm is a **position** figure while the hole that touches the magnet is governed by a **size** figure (±10 % of thickness). Delivered error 0.050–0.065 mm, not 0.010.
- **Thick (1.95 mm) photo-etched shim** — etching has the best published hole *position* of anything found (Fotofab ±0.013 mm over 6 inches) but its feature tolerance is ±10–20 % of thickness, so at 1.95 mm the hole is ±0.195–0.390 mm and a Ø2.1 hole in 1.95 mm stock is an hourglass.
- **Datum-face fixture + tangentially-slotted shim** — the 2.45 mm slot leaves 0.225–0.250 mm of half-clearance *[corrected from 0.175]* against a ±0.2–0.3 mm print tolerance, so the printed slot wall becomes the stop again; the wall is 1.211 mm *[corrected from 1.346]*, exactly at JLC3DP's recommendation, and opening the slot enough to work drives it to 0.805 mm. All three cited patents were misread and none states any numeric angular tolerance — the nearest with numbers (US6015000) **accepts 0.064 mm of lateral float**.
- **External cure jig with radial-bisector V-notches** — the kinematics are exact and valuable (diameter error maps to the bisector, so a radial V puts it in the 0.30 mm radial channel) but as written the V orientation and the preload direction are self-contradictory, the V-plate and the shim compete for the same radial band with only 0.05 mm of axial slack, and the float formula is wrong (0.0200 not 0.0175).
- **One-piece bonded ring** — the **feel refutation is withdrawn**: at a 0.050 mm budget the RLS magnetisation-accuracy figure (±4.6/D = 0.0375 mm at D 62) passes. It is still refuted, for different reasons: no bonded-magnet maker publishes a pole-position tolerance; the anisotropic MAGFINE grade that makes the torque is magnetised **in the mould**, so the one cited accuracy source (a post-magnetising fixture's 0.03° pitch spec) describes a process the specified part does not use; the isotropic grades a fixture *can* pattern top out at Br 0.68–0.81 T and miss full click by ~8 % derated; and ~$20k of tooling with MOQ 500–5000 at 8–12 weeks against a $3.32 BOM line is not a qty-1 path. Its real strengths stand and are worth remembering: **polarity flips and per-magnet axial crown scatter cease to exist**, and the whole polarity jig disappears.

**Standards and sources that were supposed to settle this and do not:**

- **ISO/ASTM 52902:2023 defines no hole-position or hole-pattern measurand.** Its eight artefacts are Linear, Circular, Z-axis, Resolution pins/holes/rib/slot and Surface texture; "Resolution holes" is a *minimum-feature-size* test. The nearest analogue is the Linear artefact (clause 7.2.1), a 1D spacing/position capability test on a 55 × 5 × 8 mm bar. **No 52902 results published for MJF or SLS polymer**, position or otherwise.
- **ISO 20457 does not apply** — it covers non-porous *moulded* parts. Useful only if the shim is ever injection moulded.
- **ISO 2768 contains no position class** in either part, so the default state of a printed hole pattern at every vendor checked is "position unspecified".
- **No print vendor publishes a hole-position tolerance or mentions GD&T** — checked JLC3DP, Protolabs, Protolabs Network, Sculpteo. The only useful published statement is Protolabs': "holes and other small features, even on very large parts, will generally exhibit good accuracy in and of themselves, **although their positional location might be affected**." The only contractual hook is Protolabs Network's "unless otherwise agreed between the parties".
- **The AM literature has exactly one usable local-position source**, and the paper does not report it: Leirmo & Semeniuta, *Applied Sciences* 11(5):2031 (2021) analyses only diameter, cylindricity and flatness, but its CC0 dataset (DOI 10.18710/DHACHZ) contains Calypso position .X/.Y characteristics. Extracting 11,340 rows over 404 CMM measurement sets and fitting translation + rotation + isotropic scale gives the number this whole sweep was missing (§7, below). Everything else checked reports diameter, roundness or overall dimensions only. Minetola et al., *Additive Manufacturing* 32:101103 (2020) is the best unread second opinion — paywalled.

**One finding that cuts the other way and is NOT a dead end — an unbudgeted encoder error nobody flagged.** A rigid eccentricity *e* of the whole pattern displaces every magnet in a fixed direction, so the track's tangential offset swings ±e once per revolution **at gain 1.0, not the 0.542 single-magnet gain**: `e/R_t = 0.198° mechanical per 0.1 mm`. At the Ø61.80 spec's worst-case 0.40 mm diametral clearance that is 0.395° mechanical — **1.58× the entire ±0.25° the unlocked firmware accepts** (`docs/firmware.md:1196`). Feel is indifferent (m=1 budget 1.30 mm), which is exactly why it was missed. Fix: centre the shim on a mandrel in the Ø54 ring ID at bond time — the existing polarity masks already register there — rather than letting the recess wall do it. At e ≤ 0.03 mm it is 0.059°, 0.24× the budget. **[corrected in build]** The mandrel cannot locate a plate whose ID is as printed; the recess fit does the job instead, once the recess has a tolerance (it had none). See the status note at the top.

---

## 7. Prototype plan

Ordered by cost. P1 and P2 run this week and together cost about $41.

### P1 — Measure one committed shim ($1 of parts + $40 of pin gauges, 1 week)

Order 3 × `stl/magnet_shim.stl` as drawn ($0.32 each) and a metric class-Z pin ladder, 1.90–2.45 mm in 0.01 steps.

| Measurement | Decides |
|---|---|
| **Pin-gauge all 144 bores.** GO = (measured magnet d_max + 0.01) enters all 48. NO-GO = Ø2.16 enters none. | **Does the committed part assemble at all?** If any bore refuses, machining is mandatory and the recommendation hardens from "best" to "only". Also yields the as-printed bore distribution in 10 µm steps, which nobody publishes. |
| **Micrometer the shim OD; try it in the recess.** | Does the shim seat? If it interferes, `SHIM_RO` must come down. |
| **4800 dpi CIS flatbed scan**, M=4 and M=5 rotational self-calibration (9 scans), 48 sub-pixel centroids, fit and remove rigid translation + rotation + isotropic scale, report σ(dt), max\|dt\| and harmonics m=2..23. | **Is the plate's local scatter 0.03 mm or 0.3 mm?** This is the number that decides whether the plate's *process* needs changing or only its *bores*. |

Protocol notes that matter: use a **CIS** scanner, not CCD — a CIS rod-lens bar views near-normal everywhere, so a 1.95 mm deep bore has the same parallax at every platen position, whereas a CCD flatbed's single off-axis lens shifts a deep hole's apparent centroid across the platen and manufactures an m=1/m=2 artefact indistinguishable from part ovality. Centroid noise is 0.40 µm (σ_edge 10 µm over 1247 perimeter pixels), 30× inside the budget, so hole roughness is not the limit; the scanner's own 4–7 µm geometric field is, which is what the M-fold averaging removes (contaminated harmonic sets {4,8,12,16,20} and {5,10,15,20} intersect only at m=20). Index hole #1 with an ink dot. **Gate: if the σ=0 part's own residual exceeds 0.03 mm the instrument cannot resolve the budget** and a tighter plate is needed before anything else is measured.

**Predicted result, from the one usable published analogue** (Leirmo's 404 CMM measurement sets on EOS P395 PA2200, features at r 18.0–41.9 mm straddling our R_t 29.0, two independent extraction routes agreeing to 2–4 µm):

- **Isotropic scale → the radial channel:** mean −0.094 %, σ 0.104 %, range −0.390 % to +0.130 %. At R 29 that is a mean radial error of −0.027 mm with σ 0.030 mm — **10× inside the 0.30 mm radial budget at 1σ**, costing −0.008 % of detent torque. The earlier premise was right: an envelope tolerance on a Ø62 part is dominated by scale, and on a pitch circle scale maps almost purely radially.
- **Low-order terms:** going similarity → full affine buys almost nothing (26.0 → 25.4 µm), so < 15 % of the post-scale residual is low-order.
- **Local random scatter → the tangential channel:** **σ 22.5 µm (x) / 36.7 µm (y)**, CMM repeatability only 4.8/6.7 µm, cross-checked independently against the mutual scatter of nominally coaxial features within a single measurement (20.4/34.6 and 23.3/24.8 µm) with no fitting involved. Over 48 holes, `E[max|dt|] = 2.496σ` = **0.056–0.092 mm**.

So the printed plate is **1.1–1.8× over the 0.050 mm budget on its own**, not 8.6× over. Caveats: different machine, vendor and material grade, and features of 4–24 mm diameter rather than Ø2.1 holes. **Small holes are plausibly worse and by how much is UNSOURCED** — if 2× worse the plate is back to 4–6× over and the verdict shifts again. That single uncertainty is why P1 costs $1 and ranks first.

### P2 — Two quotes and one question (free, concurrent)

1. **Quote the 48-hole drill/ream secondary operation** on a customer-supplied printed blank, with the composite position callout below. This is the only unquoted number in the recommendation. Order-of-magnitude anchor from the repo's own data: 48 depth-controlled flat-bottom pockets held to ±0.02 in stainless cost **$18.96** of machining (`docs/mechanical.md:837`), and 48 through holes in a 1.95 mm plastic plate is a strictly smaller job.
2. **Ask JLC3DP, PCBWay and Protolabs Network whether they will contract to a hole-position tolerance on a printed part, and at what price step.** Not published by any of them. If the answer is yes at a reasonable step, the machining may be unnecessary.
3. **Resolve item 7a's material** — 9600 SLA resin (as quoted, 59 °C HDT) or MJF/SLS PA12 (as specified)?

The callout to send, per ASME Y14.5-2018 §10.5 composite positional tolerancing (clause number sourced second-hand; confirm before release):

```
48X Ø2.03 (+0.01/0) THRU
  ⌖ | Ø0.05 | A | B |      <- PLTZF: pattern location [corrected in build from Ø0.60,
                                which allowed a 0.59° 1/rev encoder error]
    | Ø0.07 |               <- FRTZF: hole-to-hole (the only segment that spends the budget)
A = seating face   B = Ø61.88 outside cylinder
RFS — no (M) modifier: the bore must LOCATE the magnet, and MMC bonus tolerance
would grant extra position error exactly when the hole is already oversize.
```

ISO equivalent per ISO 1101 with ISO 5458:2018 `CZ`. Note ISO 5458 "does not cover the use of the pattern specifications when the least and maximum material requirement is applied", which independently forces the RFS choice. **Honest second half: Ø0.07 is a 2–3× overspecification of the printed process** (achievable FRTZF from the measured data is Ø0.14–0.22) and is only meetable by the machined route. Put it on the drawing anyway, with the basis noted, because an unstated budget gets quietly loosened.

### P3 — Only if P1's scan condemns the plate AND P2's quote is bad

Build the **K=2 head from two of the 12 BOM spare Ø2×2 discs** — zero new parts, deletes BOM item 6, and worth 1.74× — in a reprinted carriage with rails at |x| 5.6–6.2. Measure two things on the real rotor:

- `T(offset)` over the full 0–7.5 mm stroke against the §7 strength LUT. Predicted 16.92 mN·m at offset 0 (+2.5 % on the repo's 16.5), with the ~11 mN·m EC11 point at x ≈ 1.2 mm, still inside the ≤ 1.5 mm shoe window.
- **Slider thrust**, against MD-4's 0.93 N best-case delivery. Predicted 1.11 N worst case (+13 %). **This is the measurement that decides whether the multi-pole route is viable at all.**

Also check the DRV5032FA home field: K=2 at 15° straddles the sensor and the park field collapses from 60.8 to **4.21 mT** against a 3.5 mT BOP max — a 14× margin loss, and a problem any even-K head at 15° spacing has by construction. The K=3 at 7.5° alternating variant instead *closes* risk R35 (0.707 mT at click, below the 1.5 mT BOP min).

### P4 — Optional, only if the budget itself is worth moving ($80–150, 4–6 weeks)

The 2AFC panel test, to move the spec from the detection threshold (0.050 mm) toward the annoyance level (0.10–0.25 mm). **Note the earlier $1.60 estimate was mis-scoped by 50–100×** — it counted only 5 shims at $0.32 and omitted 240 N52 magnets (~$75) and ~40 h of labour.

Protocol: 5 shims with CAD-encoded tangential bore offsets at designed white scatter σ = 0 / 0.02 / 0.04 / 0.08 / 0.16 mm, **with the m=0 and m=24 gauge modes projected out** before scaling (subtract the mean; subtract `⟨x,s⟩/48 · s` with `s_i = (−1)^i`) — spending stimulus amplitude on a feel-neutral harmonic wastes it. Two-interval 2AFC, "which was rougher" (the source paper's own wording, which measured exactly this percept), 1 rev/s cued by a 60 bpm metronome, at full click with the shoe engaged. **100 trials per condition per subject** (power for p = 0.625 at α 0.05 one-tailed, 80 % power; p = 0.70 needs 37, p = 0.75 needs 23), 6 subjects, 500 trials each including a catch condition of two σ=0 parts against each other. **Acoustic shielding is mandatory and the original design omitted it** — the detent passage is audible and carries the same spacing information, so an unshielded test measures hearing: circumaural headphones with ~70 dB pink noise plus a curtain. Blind by having a third party assign letters and mount the shims. Randomise condition order by a 5×5 Latin square and interval order per trial. The test must be **differential against measured parts**, not absolute, since the print's own error is the floor.

The ladder is well chosen: σ = 0.02 mm produces a 0.62 N·mm 3σ peak perturbation, right at the 0.59–0.72 N·mm threshold. If 0.050 mm is right, σ = 0.02 is at or below threshold. If 0.035 mm is right, σ = 0.02 should be detected at ~75 %. The two hypotheses differ measurably at exactly the σ the ladder contains.

---

## 8. What this implies for the repo

### Model and code

| File | Change |
|---|---|
| `hardware/mechanical/dial_spinner.scad:158` | `POCKET_D = 2.10` → `2.03` with a comment that it is a **reamed** bore matched to the sorted lot, not a printed hole (or `2.35` if the bores stay printed, which only fixes assemblability). |
| `hardware/mechanical/dial_spinner.scad:169` | **[corrected in build]** Split `SHIM_RO` in two. One constant was serving as both the recess turned in the steel and the plate's own OD, which is exactly why §3 B's zero-clearance fit existed: it could not be anything else. Now `RECESS_RO = 31.0` (Ø62.00, unchanged, so the ring's mass and inertia do not move) and `SHIM_RO = 30.95` (Ø61.90 **turned**, 0.05 radial clearance). Note the web claim in the first draft was wrong in both directions: shrinking the OD *reduces* the outer web, to 0.935, while the bore shrinking to Ø2.03 takes the **inner** web to 0.985. |
| `hardware/mechanical/dial_spinner.scad:551-557` | Shim module prints **solid**; bores become a machining operation. |
| `hardware/mechanical/calcs.py:35-37, 102-107` | `POCKET_D` and shim mass follow; recompute the 1.37 g figure (and its density assumption — the current value implies 1.249 g/cm³, i.e. a glass-filled grade, which `docs/mechanical.md:838` also permits as unfilled MJF PA12 or 9600 resin). |
| `hardware/mechanical/models.py`, `drawgen.py` | The shim becomes the **sixth drawn part**. `docs/mechanical.md:825-826` already states the rule it now falls under — "no CNC vendor accepts an STL, and a solid cannot carry a fit, a thread, a knurl or a general tolerance." Add `drawings/magnet_shim.pdf` and `step/magnet_shim.step`. |
| `hardware/mechanical/tests/` | The "printable shim walls" invariant added in `cfa0a18` must change — the web is no longer a printed wall, and at Ø2.03 it improves to 0.985 mm. |

### Docs

- **`docs/mechanical.md` §5, the "Angular accuracy is the risk" paragraph (~313-317)** — rewrite. The 4.74° electrical comparison overstates the encoder consequence by 1.84× (the real figure is 2.57° electrical / 0.107° mechanical); the §14 3.5° XZX comparison is wrong on three counts (speed-dependent, firmware-corrected, common-mode); "48-entry LUT" is wrong three ways (64 entries, pole-averaged, and the step that could absorb per-magnet scatter is the optional 24×16 map — cite `docs/firmware.md:1196`'s ±0.25° unlocked figure instead); and "a laser-cut sheet shim holds ±0.05 mm" is **unsourced** (the only vendor figures found are 0.127–0.13 mm) and would fail the budget anyway. Replace with the 0.050 mm budget and its basis.
- **`docs/mechanical.md:319-320`** — the wall citation is wrong against JLC3DP's current size-indexed table. 0.8 and 1.2 mm are the 10×10 rows; a Ø62 footprint needs 1.0 mm (SLA) or 1.5 mm (MJF/SLS).
- **`docs/mechanical.md:376`** ("Measure your batch and set the pocket to max Ø + 0.03–0.05") — stale. Written for milled steel pockets, unorderable on a printed hole. Move it to the machined-bore row and add the self-centring gate `c ≤ 0.037 mm`.
- **`docs/mechanical.md:377`** (±0.03 flushness) — now has a derived basis (the 0.04 mm axial budget) and length-sorting becomes **mandatory**, not optional. **Note the sort direction is opposite to what the repo says:** `docs/assembly.md:589/594` prescribes h ≥ 2.03 mm, which was written for a 2.05 mm pocket; against a 2.00 +0.02/0 recess the sort must be **h ≤ 1.98** (reject h > 1.99) or every tall magnet bottoms metal-to-metal with zero adhesive and stands up to 0.05 mm proud.
- **`docs/mechanical.md` §6 Pockets row and the polarity jig (383-391)** — still written for pockets in the ring. Step 5's visual 48-cell viewing-film read should become an instrumented pre-cure read: viewing film shows pole *faces* and transition lines but does not indicate *which* pole is which, and on a DC-free alternating track the signature of a flip is a single merged region among 48 cells read by eye. The economics now favour it — a miss scraps a $0.32 shim, not a $52 ring.
- **`docs/mechanical.md` §13 item 7a** — resolve the material (§3 D) and re-quote with the machining operation.
- **`docs/mechanical.md` §15** — add prototype checks: (22) all 48 bores admit a magnet from the measured lot; (23) the shim seats fully with the magnets bottoming on steel; (24) measured per-magnet tangential scatter within spec.
- **`docs/assembly.md` §8 (~577-645)** — **entirely stale and this is the most urgent doc debt.** It still describes 48 pockets milled in the ring, masks registering on the ring's Ø54 ID and top face, a 2.20 mm deep pocket, an epoxy bed with the magnet standing 0.1–0.2 mm proud, and a clamp plate bottoming on the ring's top face. None of that describes a 1.95 mm through-hole shim whose magnets bottom on a steel recess floor; in particular the "stand proud then press flush" trick is now **impossible**, because the crown height is fixed by magnet height minus recess depth. Anyone following this section today builds the wrong part.
- **`docs/firmware.md`** — no change required. §4.6 step (f)'s `I = 1.30e-4` is already marked "adjust for the built rotor", and the recommendation does not change pole count, R_t, gap or sensor position.

### GitHub issues — yes, two

1. **"Printed magnet shim may not assemble: bore can refuse the magnet, OD can jam in the recess"** — the three §3 defects, each with its arithmetic, plus the P1 pin-gauge and OD checks. This is a go/no-go on a committed part and is not in the risk list.
2. **"Magnet angular placement: budget is 0.050 mm; bore must locate, not contain"** — the budget with its basis, the recommendation, the P2 quotes, and the stale `docs/assembly.md` §8.

### What of this is built, and what is not

**[corrected in build]** An earlier draft of this section reported, from `git ls-remote --heads origin`,
that `claude/machined-part-drawings` had never been pushed. It had: PR #8 merged as `dc96515` while the
research was running, and the branch was deleted on merge — which is what the empty listing meant.

Built, in the commit that carries this document:

* `BORE_D = 2.03` replaces `POCKET_D = 2.10`, and `MAG_D_SORT = 1.99` records the sorted bin the bore is
  specified against. `POCKET_H` is gone: a through bore has no depth.
* `RECESS_RO` and `SHIM_RO` split apart, Ø62.00 and Ø61.90 (Ø61.88 after the second review).
* The shim prints as `magnet_shim_blank` (a plain annulus) and becomes the **sixth** part with a STEP and
  a drawing, carrying the composite position callout and the sorted-lot instruction. (It also carried a mandrel note, withdrawn in the second review.)
* Six new tests. One of them — the ring-mass check against `calcs.py` §14 — caught the split above
  leaving `models.py` behind, which had quietly shrunk the B-rep recess by 0.05 mm.

Not built, and deliberately so: **P1 decides whether any of this was necessary.** Until three $0.32 shims
have been pin-gauged and scanned, the claim that a printed plate cannot hold the pattern rests on a vendor
envelope figure and one borrowed CMM dataset, not on a measurement of this part.
