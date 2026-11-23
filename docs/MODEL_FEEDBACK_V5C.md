# V5c: fix only the leg plates, the toe covers and the shoulder plates

> **UPDATE (overrides the shape rules below where they differ): the user wants the Grom armor plates copied as they are, 1:1 in shape.** Do not invent plate shapes any more. Earlier we told you to take only the layout from Grom. That was a mistake on our side. Now **reproduce the shape, segmentation, edges, insets and vents of each Grom leg and shoulder plate as faithfully as you can by eye**. Keep only our own colours (khaki plates, black/grey undersuit) and fit them to our EFT body. Model the geometry yourself; the file is not downloadable.
>
> Close-ups to copy from (attached, also in `docs/feedback/refs_sketchfab/`):
>
> | File | What it shows |
> |---|---|
> | `grom_leg_front34.jpg` | The whole leg, front 3/4: the dark segmented thigh plate with three horizontal lames and small clips, the knee cap, the shin greave with the vent slots and the boot cuff. |
> | `grom_knee_shin.jpg` | The knee cap shape (a pointed shield with a dark inset and a top slot) and how the greave wraps the shin. |
> | `grom_thigh_outer_panel.jpg` | The outer thigh plate: a big curved shell with a recessed inset panel and three rectangular pads. |
> | `grom_thigh_outer_back.jpg`, `grom_knee_back.jpg` | The back of the knee and the thigh: the greave's back edge and the calf. |
> | `grom_shoulder.jpg` | The shoulder: a tall rounded-rectangle pauldron with a chamfered rim and an inset face, a second lame below it, and the upper-arm plate. |
> | `grom_front.jpg`, `grom_side34.jpg`, `grom_back34.jpg` | Overall placement. |
>
> Note that Grom's front thigh is a **dark segmented plate (3 lames)** and its outer thigh is a **separate big shell with an inset**. Reproduce both. The size, gap and silhouette rules below still apply to how they sit on our body.

Claude reviewed your V5b result (`renders/sheet.png`, `renders/legs_front.png`, `renders/legs.png`).

**Do not touch, these are now good:**
- **The exoskeleton frame:** box segments, actuators, foot platform, hose loops. Good, keep it exactly.
- **The helmet:** close to `crop_helmet.png`. Keep it exactly.
- The carrier, belt, backpack, arm frame and skinning.

**Fix only the plates below.** Same rules as before: the budget is ≤ 80 000 tris LOD0 (you can take triangles from the plates you replace), LOD1 about half, flat colours, no baking, GPU render.

## Problems seen in `legs_front.png` / `legs.png` / `sheet.png`
1. **Thigh plates:** big flat trapezoids, **wider than the leg itself**. From the front they stick out past the thigh silhouette and read as khaki shorts or flaps, not armor.
2. **Shin greaves:** they **flare outward at the bottom like buckets**, have **ragged/zig-zag bottom edges**, and from the side they stand away from the shin.
3. **Toe/instep covers:** they look like **crumpled blobs**, broken geometry.
4. **Shoulder plates:** thick rounded khaki tubes; they do not read as plates.
5. The back of the legs is bare. Grom has calf coverage (optional, see below).

## Exact requirements
- **Silhouette rule:** in the front and side views, no leg plate may extend more than **20 mm** beyond the undersuit silhouette of the limb it sits on. Plates follow the leg. They do not make it wider.
- **Gap rule:** the gap between each plate's inner surface and the undersuit is **5–12 mm** over the whole plate. Measure it and report the min/max per plate.
- **Thigh plate:**
  - one shell, **concentric with the thigh** (single curvature around the thigh axis);
  - covers the front and the outside (about 180°);
  - width in the front view about **85% of the thigh width**, tapering toward the knee;
  - the top edge follows the hip crease, angled up and outward;
  - the inner edge stays at least 30 mm away from the crotch;
  - clean clipped corners, 15 mm thickness with a chamfer, one inset panel with vents on the outside under the frame;
  - the frame segment mounts on top of the outer part with brackets.
- **Knee cap:**
  - bigger than now: about **120 × 140 mm**, 30–40 mm deep;
  - faceted, with clipped corners;
  - overlaps the bottom of the thigh plate and the top of the greave.
- **Shin greave:**
  - **tapers toward the ankle** (narrower at the bottom), concentric with the shin, no flare;
  - covers the front and both sides (about 220°);
  - the top edge is a shallow point/arch under the knee cap;
  - a **clean straight bottom edge** about 40 mm above the ankle cuff;
  - 15 mm thick, chamfered, small vent detail near the top.
- **Calf plate (optional, if it fits the budget and clears the frame):** a narrower plate on the back of the calf, as in `grom_back34.jpg`.
- **Ankle cuff + instep cover:** rebuild as clean rigid plates.
  - The ankle cuff is a band plate around the front and sides of the ankle.
  - The instep cover is one clipped-corner plate on top of the boot that follows the boot's top surface with a 3–8 mm gap.
  - No crumpled or non-manifold geometry.
- **Shoulder plates:**
  - like the shoulders in `crop_front.png`: **two layered, slightly curved panels** (an upper cap plus a lower lame);
  - each 15–20 mm thick, chamfered, clipped corners;
  - follow the deltoid and do not stick out more than 35 mm from the sleeve;
  - no thick rounded tubes.
- **Symmetric** left/right. Same plate language everywhere: flat or single-curved panels, chamfer, clipped corners, screws.

## Deliverables
- Re-render `sheet.png`, `legs_front.png`, `legs.png` and `pose.png`.
- Also render `legs_back.png`.
- `REPORT.md`:
  - the gap min/max per plate;
  - the silhouette overshoot per plate in mm;
  - triangle counts;
  - an honest done/not-done list against this file.
