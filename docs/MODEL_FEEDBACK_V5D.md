# V5d: full coverage, at least 70% of the body under hard plates

The user's verdict on V5c: **"Too much fabric."** This is a Juggernaut suit: the operator must have no exposed weak spots. Grom covered more than 70% of the body; V5c covers less than 50%. Specifically exposed now:
- the **groin**;
- the **whole back of the legs** (back of the thighs, back of the knees, calves);
- the **inner thighs**;
- the **inner arms** (inside of the upper arms and forearms);
- the buttocks;
- the sides of the torso under the arms.

**Keep:**
- the exoskeleton frame and the helmet, unchanged;
- the carrier, the belt, the backpack and the skinning;
- the plate style (Grom shapes, khaki plates plus the dark segmented thigh lames, clipped corners, chamfers);
- the gap/silhouette rules from V5c (5–12 mm gap, ≤20 mm overshoot of the limb silhouette);
- the budget: ≤ 80 000 tris LOD0, LOD1 about half. If needed, take triangles from the undersuit, which will be mostly hidden now. Flat colours, no baking, GPU render.

## 1. Coverage target (measured)
- **At least 70% of the undersuit surface area** (head, hands and feet excluded) must be covered by hard armor.
- **How to measure:** cast a ray from each undersuit vertex/face along its normal. If it hits a hard plate, frame housing, helmet or carrier within 40 mm, the point is covered.
- Report the coverage **per region and in total**:
  - torso front, torso back, torso sides;
  - shoulders, upper arm outer, upper arm inner, forearm outer, forearm inner;
  - groin, buttocks;
  - thigh front, thigh outer, thigh inner, thigh back;
  - knee front, knee back;
  - shin, calf.
- Only the **joint gaps** may stay as fabric, because the joints need to bend: the inner elbow fold, the back-of-knee fold, the armpit and the crotch seam. Make these gaps **narrow (≤ 60 mm)** and cover them with **overlapping segmented lames** where possible.

## 2. New and extended plates (Grom style)
- **Groin:** a hard codpiece plate under the belt plate, plus two small hinged lames on the inner upper thighs.
- **Buttocks/seat:** a two-piece hard rear plate hanging from the belt ring, segmented so the hips can bend.
- **Thighs:** the front lames plus the outer shell stay, and the coverage is extended:
  - a **rear thigh plate** (the hamstring area), a single-curved shell;
  - an **inner thigh plate** (narrower, clear of the crotch in a stride).
  - Together the thigh plates wrap about 300°, with small seams between them.
- **Knee:**
  - **rebuild the knee cap** like `grom_knee_shin.jpg`: a clean pointed shield, smooth chamfered faces (not lumpy facets), a dark inset and a top slot, about 120 × 140 mm and 30–40 mm deep;
  - add a **back-of-knee guard**: 2 small overlapping lames.
- **Shin and calf:**
  - **rebuild the shin greave so that it tapers toward the ankle.** Its bottom is narrower than its top, with no flare and no skirt shape, like `grom_leg_front34.jpg`;
  - add a **calf shell** on the back, so the greave and the calf shell enclose the lower leg (about 320°).
- **Boot:** a proper **instep cover** (a rigid clipped-corner plate on the boot top) plus a **heel guard**.
- **Arms:**
  - **upper arm:** add an **inner upper-arm plate**, so the upper arm is enclosed by the outer shell plus the inner plate (narrow seams);
  - **forearm:** the bracer wraps about 300°, with an inner forearm plate;
  - **elbow:** an elbow cop on the outside, and 1–2 small overlapping lames over the inner elbow fold;
  - gauntlet plates on the backs of the hands.
- **Torso sides:** side plates under the armpits, on the carrier's cummerbund area, so the flanks are not bare.

## 3. Posing
Larger coverage collides more in poses. Make joint lames overlap and slide (separate pieces, skinned so they ride on each other). Run the pose QA (walking, crouching, deep crouch, arms raised, arms forward) and report the remaining contacts. **Minor plate-on-plate contacts in the deep crouch are acceptable. Plates going deep into the body are not.**

## Deliverables
- Re-render `sheet.png`, `legs_front.png`, `legs.png`, `legs_back.png` and `pose.png`.
- Add `arms.png`: both arms from the inside/front.
- Add `coverage.png`: the undersuit with uncovered areas highlighted in red, front and back.
- `REPORT.md` with:
  - the coverage table per region and in total;
  - triangle counts;
  - the gap/silhouette numbers;
  - an honest done/not-done list against this file.
