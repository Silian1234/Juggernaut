# Amendment 1 to JUGGERNAUT_TZ.md (from the user; it overrides the original where they differ)

Your previous run was interrupted on purpose to send you these changes. Keep the work you already did, then continue with the task with the following changes.

1. **Equipment rule, no switch.** While the Juggernaut suit is worn, armored body armor and armored/ballistic rigs are always blocked. Remove the F12 toggle for this rule.

2. **Only the Juggernaut helmet.** While the suit is worn, the Headwear slot accepts only the Juggernaut helmet. Every other headwear item is blocked, armored or not, including caps and hats. Face cover and eyewear stay blocked by the helmet, as in the TZ.

3. **One power cell = 5 minutes.**
   - A cell holds exactly one 5-minute charge. The drain interval is configurable, default 5 min.
   - The player is meant to carry a stack of cells from the stash and fill the inventory with them.
   - When the cell in the suit runs out, the suit automatically takes the next charged cell from the player's own inventory: pockets, rig, backpack, secure container. The new cell goes into the power slot. The spent cell is left in the inventory where the new one was taken from. If that is not possible, it is dropped into the first free space; if there is no space, it is destroyed.
   - The swap must be a real inventory operation that the game and the server save. Use the game's own inventory controller move/swap operations, so the raid-end profile is consistent. Never edit the profile by hand.
   - If no charged cell is left in the inventory, the set becomes discharged, with the full debuffs from the TZ.
   - F12 setting **"Auto-swap cells"**, default ON. When it is OFF, the player swaps cells manually.
   - A notification "Power cell replaced (N left)" appears on each auto-swap. The low-power warning becomes "last cell".
   - Spent cells can be sold.
   - Ragman sells cells cheaply and in bulk: LL2, about 8,000 RUB each, with no low buy limit.

Update `docs/JUGGERNAUT_TZ.md` itself with these changes, so that it stays the single source of truth. Then carry on.
