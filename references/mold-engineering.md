# Mold engineering rules

## Preserve the dependency order

Use this order and do not force later choices backward into earlier calculations:

1. approved part geometry, material grade, quality target, and production basis;
2. actual or explicitly estimated volume, mass, projected area, wall, and undercuts;
3. cavity count, layout, parting, and preliminary machine;
4. runner, gate, cold-slug well, venting, and material utilization;
5. molding dimensions, inserts, and strength/stiffness;
6. ejection and side action;
7. cycle, heat balance, coolant flow, water path, and pressure loss;
8. mold base, assembly, BOM, and final machine match;
9. optional CAE optimization and revision.

## Source every formula and value

For each calculation store:

- formula ID, original source, exact locator, and applicability;
- symbols, units, input parameter IDs, and values;
- substitution and result;
- rounding rule, allowable value, margin, and pass/fail;
- dimensional check and independent recomputation;
- affected drawing and manuscript sections.

Do not hard-code a universal shrinkage, cavity pressure, safety factor, friction coefficient, heat value, allowable stress, process temperature, or machine parameter. Verify the exact material grade, machine model, standard, handbook edition, or other applicable source.

## Mandatory calculation coverage

Adapt to the design but normally cover:

- part volume, mass, projected area, and material utilization;
- cavity count from production, cycle, quality, layout, and economics;
- shot volume or mass with runner and reserve, without mixing `cm³` and `g`;
- preliminary and final clamp force with a consistent projected area, pressure basis, and factor;
- sprue, runner, gate, cold-slug, puller, and venting dimensions;
- plastic-to-molding dimension mapping with shrinkage and manufacturing tolerances;
- cavity wall/bottom and small-core strength/stiffness where applicable;
- side-core travel and locking force where applicable;
- demolding force for the correct contact area and total cavity count;
- heat load including part and cold-runner mass when the runner cools in the mold;
- coolant flow, diameter, velocity, Reynolds number, heat-transfer area, pressure loss, and actual modeled path length;
- injection pressure, shot capacity, clamp force, mold thickness, platen and tie-bar clearance, nozzle and locating ring, opening/ejection stroke and force, and mounting.

## Hard consistency rules

- Maintain one confirmed value per parameter ID. Reuse it everywhere.
- Keep preliminary estimates distinct from CAD-measured values and supersede them explicitly.
- Never compare unlike quantities, such as machine shot volume with plastic mass, without a documented conversion and density basis.
- Require all terms in an addition or comparison to have compatible dimensions.
- Report intervals as intervals; for example, `40 + 150 + (5–10)` is `195–200`, not only `195`.
- Use realistic significant figures; CAD precision does not make uncertain source inputs exact.
- Record the total/single-cavity basis for area, mass, pressure, and force.
- Close coupled calculations. A selected channel diameter and volume flow must reproduce the velocity used in heat transfer.
- Tie calculated dimensions to the actual NX model and drawing revision.

## Lessons encoded from the reference thesis

The sample structure is useful, but the skill must catch these error classes:

- a sprue diameter changing from 5 mm to 4 mm downstream;
- runner projected area changing between clamp-force checks;
- shot volume in `cm³` compared directly with `g`;
- machine mold-thickness limits changing between a table and prose;
- a flat two-plate parting scheme later called multiple-parting;
- core/cavity called both integral and inserted;
- coolant flow, diameter, velocity, and area failing to close;
- friction counted twice in demolding force;
- a table cited by the wrong number;
- generic material names used instead of an exact grade and data sheet;
- nonstandard component materials selected without catalog, hardness, wear, and cost evidence.

Treat any analogous conflict as a blocker, not an editing detail.
