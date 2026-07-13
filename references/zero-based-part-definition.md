# Zero-based plastic-part definition

## Classify the evidence level

- `REAL-PART`: user-provided drawing/model, task book, measurement, or enterprise data defines the part.
- `EDU-CONCEPT`: the title is the only input and the part is an original teaching design.

For `EDU-CONCEPT`, label all drawings “教学设计用途；未经外部验证不得用于生产.” Do not imply that dimensions were measured from an existing product.

Use maturity levels:

- `L0`: title only;
- `L1`: concept part;
- `L2`: user-approved course-design baseline;
- `L3`: CAD and calculations verified;
- `L4`: CAE executed and reproducible;
- `L5`: prototype, tryout, or enterprise validation.

A title-only undergraduate project normally ends at L3 or L4.

## Resolve the title

Extract:

1. product and exact plastic-part boundary;
2. function, user, environment, and service loads;
3. mating parts and assembly interfaces;
4. appearance surfaces and hidden surfaces;
5. regulatory or safety-sensitive use;
6. expected deliverables and course complexity.

If the title could mean a complete product or only an enclosure/panel/component, present 2–3 boundaries and recommend one before defining dimensions.

## Create the concept packet

Develop 2–3 original, moldable concepts. For each, provide:

- functional sketch description and envelope;
- datum and molding direction;
- nominal wall strategy, draft, fillets, ribs, bosses, holes, clips, inserts, and undercuts;
- assembly concept and expected visible surfaces;
- candidate material families and the properties still needing exact-grade evidence;
- likely mold complexity, side actions, ejection, cooling, and risk;
- course-design value and expected drawings/calculations.

Recommend one using a transparent decision table. Do not select a complex side-action merely to add thesis content.

## Separate sources, decisions, and assumptions

Use these origin types:

| Code | Meaning | Permitted wording |
|---|---|---|
| `USR` | User or formal task requirement | “任务要求……” |
| `SRC` | Verified external source | “资料/标准指出……” with a citation |
| `DEC` | Chosen design variable | “综合比较，本设计选取……” |
| `ASM` | Missing real-world fact provisionally assumed | “为完成课程设计，暂设……” |
| `CALC` | Derived result | “由式……计算得……” |
| `CAD` | Value read from an actual NX model | “由NX模型质量属性读取……” |
| `SIM` | Value from an executed Moldflow case | “在算例……条件下求解得……” |
| `OBS` | Measurement or formal test | Use only with the raw record |

A source may provide a range; choosing a value inside the range remains a `DEC`. Do not write the chosen value as if the source mandated it.

## Govern assumptions

Classify criticality:

- `K1`: wording or presentation only;
- `K2`: affects one local calculation or feature;
- `K3`: affects material, cavity count, machine, mold base, runner, cooling, side action, safety, or multiple downstream outputs.

Every K3 assumption must be disclosed at G1 and addressed by user approval, stronger evidence, a bounded sensitivity analysis, or an explicit limitation.

Do not replace these with an unsupported assumption:

- exact material properties or safety rating;
- mandatory product dimensions or regulatory limits;
- manufacturer machine and mold-base specifications;
- software-derived measurements or solver outputs.

## Check moldability before freezing

Review uniform wall thickness, realistic transitions, draft, radii, ribs and bosses, sink risk, weld lines, air traps, parting-line visibility, undercuts, ejection surfaces, gate access, cooling access, and feasible machining. Revise the concept before G1 rather than compensating with prose later.

## Escalate safety-sensitive topics

For electrical, flame-retardant, food-contact, medical, child-use, pressure, or load-bearing parts:

- search applicable current standards before freezing the concept;
- verify a specific material grade and supplier data;
- distinguish “designed against a constraint” from certified compliance;
- disclose missing test, certification, and production evidence prominently.
