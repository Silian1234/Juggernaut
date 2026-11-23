# Model feedback 2: v2 rejected as well, redesign the look (suit + helmet)

The user's verdict on v2 (`docs/feedback/rejected_v2.png`): **"a cross between a Teletubby and RoboCop."**

**Problems with v2:**
- **Bloated and puffy.** The quilted/padded base suit and the rounded, inflated plates make the body look like a soft toy.
- **Proportions are wrong.** The helmet is tiny compared to the swollen body.
- **Shapes are blobby.** They are generic and do not read as engineered armor.

The user attached an **inspiration reference**, `docs/feedback/reference_inspiration.png`: a sleek, dark, segmented power-armor suit.

**Rules for the reference:**
- It is **inspiration only**. The user explicitly does NOT like that armor as a design.
- Do not copy it.
- Take these qualities from it:
  1. **Anatomical, form-following armor.** Plates follow the body's muscles and limbs: pectoral and abdominal segments, deltoid pauldrons, forearm guards, segmented thighs/shins, knee and elbow caps.
  2. **No puffy padding.** Between plates use thin, tight under-layer material (ballistic fabric / flexible armor mesh), not quilted pillows.
  3. **Correct proportions.**
     - The helmet is sized to the body: a full, solid helmet a bit larger than a head.
     - The shoulders are broad.
     - The waist is narrower than the chest.
     - The legs are strong.
     - It reads as a powerful human figure, not a blob.
  4. **Clean hard-surface design.** Crisp chamfered edges, layered/overlapping plates, thin edge trims, panel lines, recessed seams and mechanical joints.
  5. **Dark palette with contrast trims.** Near-black / dark gunmetal plates with lighter worn metal edge trims.
  6. **Helmet with a strong visor shape.** For example, a narrow T- or Y-shaped dark visor slit. Make the shape our own.

**What NOT to take:**
- No sci-fi neon. At most 1–2 tiny dim status LEDs (for example the battery indicator on the back). EFT is a grounded military shooter.
- No glossy plastic toy look.

**What must stay Juggernaut:**
- **Super-heavy.** Express the weight through **thick plates** (25–40 mm visible edge thickness on the chest, back, pauldrons and thighs) and layered coverage, not through padding volume.
- **Full coverage.** Keep the v2 result: no clothing visible.
- **Back power pack.** Keep the integrated back power pack, made slimmer and engineered.
- **Exoskeleton.** Keep the servo/actuator elements at the hips, knees and elbows, integrated into the armor.
- **Finish.** Grounded military: worn paint, scratches, edge wear, grime. Realistic PBR, not glossy.

## Process
- Before building, write a short design sheet: concept renders, or a gptimage concept, of front/back/side and the helmet. Compare it against the reference and against these points, then build.
- Self-review the final previews **on the character, next to a vanilla EFT PMC for scale**. Ask yourself: does this look like a believable super-heavy military powered armor that fits Tarkov, with a well-proportioned helmet? If it looks puffy, toy-like or the helmet looks small, iterate.
- Keep all technical constraints from `MODEL_TZ.md` and `MODEL_FEEDBACK_1.md`:
  - same bundle names, prefab paths and structure;
  - same rig, mounts and LODs;
  - pose QA.
- Update the previews, icons, banner, `REPORT.md` and `BUNDLES.md`.
