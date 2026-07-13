# Siemens NX / UG workflow

Treat “UG” as Siemens NX. Probe the installed release, components, license, and automation path at project time; do not assume that an executable proves a usable modeling, drafting, Mold Wizard, or NX Open license.

## Detect capabilities

Check environment variables and installation records first:

- `UGII_BASE_DIR`, `UGII_ROOT_DIR`, `UGII_USER_DIR`;
- `UGS_LICENSE_SERVER`, `SPLM_LICENSE_SERVER`;
- Windows uninstall records and start-menu shortcuts.

Search plausible versioned roots for:

- `NXBIN\ugraf.exe` or `UGII\ugraf.exe`;
- `NXBIN\run_journal.exe` or `UGII\run_journal.exe`;
- `UGOPEN`;
- `NXBIN\managed\NXOpen.dll`, `NXOpen.UF.dll`, or legacy `UGII\managed` equivalents.

Record these separately: `nx_gui`, core modeling, drafting, Mold Wizard, NX Open Python, NX Open .NET, interactive journal, candidate batch journal, and license status. Set license status to `unknown` until a minimal feature test succeeds.

NX Open supports multiple languages, including Python and .NET, but authoring and runtime modules can require separate capabilities. Use the libraries shipped with the detected NX release; do not install an unrelated `NXOpen` package into ordinary system Python. See the [Siemens NX add-on/module overview](https://blogs.sw.siemens.com/wp-content/uploads/sites/2/2020/11/NX-Add-on-Module-Brochure.pdf?pid=0013000000HYMiIAAX&spi=4044175&stc=esdi100022).

## Choose an adapter mode

1. **NX Open Python executed** — preferred when the detected NX runtime and license pass a probe.
2. **NX Open C# executed** — use only with the current installation's `NXOpen.dll` and `NXOpen.UF.dll`.
3. **Interactive journal/manual NX** — use when automation cannot cover a Mold Wizard or drafting action reliably.
4. **Prepared unexecuted** — generate a versioned model plan and NX Open source, but label all native/model results unexecuted.

On the configured local Windows machine, execute Python journals only through `scripts/nx_stage_run.py`. It exposes the physical project through a temporary ASCII drive, calls Siemens `UGII\ugiicmd.bat`, captures project-local evidence, and removes the mapping. Register successful diagnostic evidence through `scripts/nx_register_validation.py`; registration proves only the bounded capability scope and never promotes a production CAD artifact. Read [local-nx-portable.md](local-nx-portable.md) for the exact contract.

Journal recording helps discover APIs but can contain transient object IDs or UI-dependent actions. Refactor recordings into stable expressions, named features, and deterministic searches before reuse. Do not assume every Mold Wizard UI function has a stable public API.

## Drive NX from the neutral design model

Map stable parameter IDs to NX expressions and preserve units. Use a consistent coordinate system, opening direction, datums, parting definition, and revision. Build in this order:

1. parameterized plastic part;
2. moldability revisions and approved part baseline;
3. shrinkage application and molding inserts;
4. core/cavity split and parting surfaces;
5. cavity layout, runner, gate, cold-slug, and venting geometry;
6. ejection, side actions, cooling, mold base, and assembly;
7. interference checks, opening sequence, BOM, and drawings.

Read actual volume, surface area, center of gravity, bounding box, and mass from the opened model. Document the projected-area method and direction. Never relabel an analytical estimate as an NX measurement.

## Produce interoperable evidence

For an executed and verified model retain, as applicable:

- native `.prt` files;
- Parasolid `.x_t`/`.x_b`;
- STEP, preferably AP242 when supported;
- optional JT for review;
- PDF and DWG/DXF drawings;
- PNG previews with artifact ID and revision;
- journal/source, execution log, measured-property JSON, and file hashes.

Verify that each native file reopens, has no failed/stale feature, resolves assembly references, and matches the expected body count, units, bounding box, volume, and area. Compare neutral exports against the native model.

If NX is unavailable, deliver only the parameter table, feature/model plan, NX Open source, manual step plan, and neutral geometry created by a genuinely available tool. Mark status `prepared_unexecuted`; do not create fake NX screenshots or rename another format to `.prt`.
