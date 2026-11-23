# V5b: new references for the exoskeleton and the plate layout (they override parts of MODEL_FEEDBACK_V5.md)

The user found two Sketchfab models. **They are references only.** We do not have the files, and we must not copy their geometry or branding. Claude captured views from the Sketchfab viewer. They are attached and also in `docs/feedback/refs_sketchfab/`.

Everything in `MODEL_FEEDBACK_V5.md` still applies (helmet, 80k budget, no baking, GPU render, deliverables), except sections 2 (leg plates) and 3 (exoskeleton), which this file replaces.

The overall look stays **ref3**: black suit, khaki plates with clipped corners, black carrier, yellow lines. These new references only define **the exoskeleton's construction** and **where the plates go**.

## A. Exoskeleton: build it like "Heavy Soldier Exoskeleton" (`hs_exo_*.jpg`)
The user's words: "your frames are thin sticks; this one is a solid assault exo". The user wants this exoskeleton's design as close as possible (our own geometry, not a copy of the file). What makes it solid:
- **Box-section segments, not bars.**
  - The thigh and shin segments are **chunky rectangular housings**, about 5–7 cm wide and 4–5 cm deep, with **inset panels, screws, edge bevels and small vents**.
  - Each segment is made of 2–3 stacked boxes/plates, not one stick.
  - They run down the **outside** of the leg and wrap slightly to the front.
- **Big round actuator housings at the joints.** Hip (largest, about 10–12 cm), knee (about 8–9 cm, the dominant feature on the side of the knee), ankle (about 6 cm). Each has a cap with a ring of screws.
- **The thigh segment** sits **over** a large rectangular outer thigh plate, so the frame and the plate read as one module (see `hs_exo_side_left.jpg`, `hs_exo_side_right.jpg`).
- **The shin segment** has a large panel on the outer shin, and an armored ankle housing that ends in a **thick foot platform under the boot**: a load plate with a ribbed edge, wider than the boot, like a sole extension (`hs_exo_back.jpg`, `hs_exo_side_left.jpg`).
- **Hoses.**
  - Thick black cables and **colored hydraulic hoses that form loops between segments** (on the reference they are orange; **for us they are yellow, as in ref3**).
  - The loops stand off the frame and run into fittings on the actuators.
  - Hoses also loop around the ankles and from the belt to the hips.
- **Back and shoulders.**
  - A **back frame** with box-shaped **shoulder actuator housings** standing above both shoulders.
  - A central motor/fan unit on the back, under the backpack.
  - A heavy **belt/hip ring** with box modules and a battery pack (we keep our backpack, our cells and the yellow triangle).
- **Arms.**
  - Shoulder housing on top.
  - A box segment down the outside of the upper arm, an elbow actuator, a box segment on the forearm.
  - A **wrist housing with a window**.
  - Hose loops at the elbow.
- **Overall it is solid and dense.** It is clearly the heaviest-looking part of the silhouette. It reads from 20 m away.

## B. Plate layout: copy the layout of "Grom Combat Armor" (`grom_*.jpg`)
Take **only the placement, coverage and segmentation** of the plates. Ignore the Halo-like helmet, the green colour and the body shapes. The plates themselves stay ref3-style: khaki, clipped corners, 12–20 mm thick, chamfered. Layout to reproduce:

**Legs** (this is the main fix; the user said the legs of both entries are a disaster):

| Piece | Description |
|---|---|
| **Thigh shell** | One large plate that **wraps the front and the outside of the thigh** (about 180–200°), from the hip crease to just above the knee. It has an inset panel with vents/slots on the outside. The inner thigh stays undersuit. |
| **Separate knee cap** | Over the knee, overlapping the thigh shell's lower edge. |
| **Shin greave** | One large plate that **wraps the front and both sides of the shin**, from under the knee to the ankle, wider at the top. It has a small vent detail at the top. |
| **Boot armor** | An ankle cuff plate plus a toe/instep cover on top of the boot. |
| **Hip/waist** | A belt ring with side tassets over the upper outer thigh, and a groin plate. |

**Arms:**
- a large two-layer pauldron;
- an upper-arm shell on the outside;
- a **forearm bracer** wrapping the top and the outside of the forearm, from the elbow to the wrist;
- an elbow cap.

**Rules for the plate–frame combination:**
- On the outer side of each leg, the **exoskeleton segment lies over the outer thigh and shin plates**.
- Plates and frame must not intersect. The frame mounts onto the plates with brackets.

## C. Process
- Continue from your current files in `art/v5-astra/`. Do not restart from zero.
- Keep the work you did on the helmet if it already matches `crop_helmet.png`.
- Self-review, as before:
  - place `sheet.png` and `legs.png` / `legs_front.png` next to `grom_front.jpg`, `grom_side34.jpg` (plate layout) and `hs_exo_side_left.jpg`, `hs_exo_front.jpg` (frame);
  - list in `REPORT.md` what matches and what does not.
