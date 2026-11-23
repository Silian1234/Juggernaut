# V5 feedback: you won the competition, now fix it

The user compared both entries with `ref3`. Your model won: **the plates sit on the body and do not float.** But the user said it is still bad, in particular:
- **the helmet is a disaster**;
- **the plates are stuck on at random** ("натыканы на отъебись");
- **the exoskeleton is not one piece**;
- **the legs are terrible**.

The arms are acceptable.

**Fix it in your existing `art/v5-astra/` model.** Keep everything that already works: the arms, the carrier, the pouches, the backpack, the skinning.

## Stage rules (new)
- **No texture baking.** The user wants to judge the **model** only. Use plain flat-colour materials: black fabric, khaki plates, dark-grey metal frame, black visor, yellow lines. No normal or albedo maps. Delete or bypass the cloth/finish map passes.
- **Render on the GPU**: Cycles with OptiX, CUDA as a fallback. Set the device explicitly and check in the log that the GPU was used. Do not render on the CPU.
- Same render set as before, overwritten in `renders/`: `sheet.png`, `helmet.png`, `legs.png`, `pose.png`. **Add `legs_front.png`**: both legs, front view, from the hips down.
- **New triangle budget: ≤ 80 000 triangles LOD0 for everything worn** (was 30k), and **LOD1 ≈ 40 000**. Because nothing is baked, real detail must be geometry: chamfers, bolts and screws, buckles, webbing and MOLLE straps, pouch flaps, frame link plates with holes, hinge housings, hose fittings. Spend the budget on the reading of form, not on dense flat areas. Report the counts per part.
- Work only in `art/v5-astra/`. No bundles, no game, no git.

## Close-up references (attached, also in `docs/feedback/refs_gpt/`)
- `crop_front.png`: the front view of ref3, large.
- `crop_helmet.png`: the helmet.
- `crop_leg_side.png`: the leg frame and the leg plates, side view.
- `crop_frame.png`: the exoskeleton frame on its own.
- `crop_plates.png`: the plate set laid out.
- `crop_side.png`: the side view.

## 1. Helmet: rebuild it to match `crop_helmet.png`
The current helmet does not read as the reference. Required parts:
- A **high-cut ballistic shell** (FAST/Caiman proportions), dark grey/black, sized to the head, not a bowling ball.
- **Khaki applique plates on the shell:** a band that follows the brim around the front and sides, and plates crossing the top. They are separate pieces with visible thickness and screws.
- **Side ARC rails** along the shell sides, with small rail accessories, and an **NVG shroud** at the front top. The thermal module mounts on the shroud (`mod_nvg`).
- **Side ear covers / side armor:** a big black plate over each ear, mounted on the rail.
- **Mandible:** a black jaw guard that goes from the ear covers around the chin, made of segmented hard pieces on arms. It must clearly cover the chin and the mouth.
- **Visor:** a dark, wrap-around visor **under the shell brim**, covering the eyes and the nose down to the mandible. It must follow the shell contour: no flat plate standing in front of the face, no motorbike bubble.
- A black balaclava/gaiter and the high carrier collar under it.

When it is done, the face must be fully closed: shell, visor and mandible with no gaps. From 3/4 it must read like `crop_helmet.png`.

## 2. Leg plates: a deliberate layout like `crop_front.png` / `crop_leg_side.png`
Right now the plates are small and scattered. Use this layout on **both legs, symmetric**:

| Piece | Description |
|---|---|
| **Front thigh plate** | A large khaki rectangle with clipped corners, mounted in a black **thigh rig** (a strapped sleeve, with two horizontal straps and buckles). It covers the front of the thigh from about 10 cm below the belt to about 8 cm above the knee, and about 1/3 of the thigh circumference. |
| **Outer thigh plate** | A tall khaki rectangle on the outside of the thigh, next to the frame. It overlaps the front plate's edge. |
| **Knee armor** | A **big, thick, 3D knee cop**: dark, octagonal, 3–4 cm deep, like a box with chamfered faces, on a black knee pad. It is the most prominent piece on the leg. |
| **Shin guard** | A large khaki plate on the front of the shin, from just under the knee to mid-shin. It is wider at the top, with clipped corners, held by a strap under the knee and a strap at the bottom. Below it is a short second khaki plate on the lower shin above the boot, and the black sleeve. |
| **Boots** | Chunky black military boots with a thick sole. |

General plate rules:
- Plates are **flat or single-curved panels with real thickness (12–20 mm), chamfered edges and clipped corners**. They are aligned to the limb axis and centred on the front or outside of the limb.
- **Same shape language, same size logic, symmetric left/right.**
- Every plate is **visibly held** by straps or a sleeve.
- No random small tiles, no faceted rock-like lumps (your shoulder plates look faceted now; smooth them into clean chamfered panels).
- **Silhouette:** the legs look strong and armored, but they are still legs. No tubes and no barrels.

## 3. Exoskeleton: one continuous frame, like `crop_frame.png` / `crop_leg_side.png`
The frame must be **one connected mechanism**, not separate bits:
- **Back:** a frame on the spine that carries the power pack and a **hip belt ring** around the waist.
- **Legs:** from the hip-belt ring, a **hip actuator** (a round hinge housing) on the side of the hip, then a **thigh segment** (a chain of 2–3 bolted link plates) down the outside of the thigh, then a **knee hinge** (a big round housing on the side of the knee), then the **shin segment** (link plates), then an **ankle hinge**, then a **stirrup/foot plate** under the boot. Every joint is a visible hinge between two link plates. There are no gaps between segments.
- **Cuffs:** strap cuffs tie the frame to the thigh and the shin.
- **Hydraulics:** yellow lines run along the segments between the hinges, with fittings at the hinges.
- **Arms:** a shoulder actuator on the back frame, then an upper-arm segment, then an elbow hinge, then a forearm segment ending in a wrist cuff. Again, all connected.
- The frame must be **clearly visible from the front and the side**, as in the reference. It is a key part of the look.

## Self-review before finishing
- Put `sheet.png`, `legs_front.png` and `helmet.png` next to `crop_front.png`, `crop_leg_side.png` and `crop_helmet.png`.
- Check every bullet above.
- In `REPORT.md`, list each bullet with "done" or "not done" and the reason. Also list the triangle counts.

