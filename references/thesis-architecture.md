# Thesis architecture and evidence placement

Use the school template when supplied. Otherwise use a neutral academic layout and mark school-specific front matter as missing rather than inventing an institution, author, student number, supervisor, or date.

## Baseline outline

### Front matter

- cover and required declarations;
- Chinese abstract and keywords;
- English abstract and keywords;
- table of contents;
- optional lists of figures, tables, and symbols.

### 1 Introduction

1.1 Engineering background and significance  
1.2 Domestic and international research status  
1.3 Design objectives, constraints, and technical indicators  
1.4 Main work and technical route

Use literature and a technical-route figure here. Do not introduce final design results prematurely.

### 2 Process analysis of the plastic part and material

2.1 Function, use environment, and assembly boundary  
2.2 Geometry, molding direction, and undercuts  
2.3 Dimensions, tolerances, surface quality, wall, ribs, bosses, holes, radii, and draft  
2.4 Material alternatives and exact-grade selection  
2.5 Material properties, drying, shrinkage, and processing window  
2.6 CAD volume, mass, projected area, and production basis  
2.7 Moldability findings and finalized part baseline

Place the part 3D view, dimensioned 2D drawing, quality table, material comparison, and actual CAD property evidence near the analysis that uses them.

### 3 Overall mold scheme, gating, forming, and venting

3.1 Constraints and scheme comparison  
3.2 Cavity count and production-capacity calculation  
3.3 Cavity layout and runner balance  
3.4 Molding direction and parting surface  
3.5 Preliminary injection-machine selection  
3.6 Sprue, runner, gate, cold-slug well, puller, and venting  
3.7 Preliminary flow validation and chapter decision

Place a decision table before the selected layout. Put each runner/gate drawing immediately after its calculation and explain the consequence after the figure.

### 4 Molding parts and conditional side action

4.1 Integral versus inserted core/cavity scheme  
4.2 Plastic dimension to molding-dimension mapping  
4.3 Shrinkage and manufacturing tolerance calculation  
4.4 Cavity wall, bottom, and small-core strength/stiffness  
4.5 Side parting or core-pulling only when justified  
4.6 Materials, heat treatment, and surface treatment  
4.7 Core/cavity engineering drawings

If no undercut exists, document that result; do not invent an extraction mechanism.

### 5 Ejection, guidance, return, and temperature control

5.1 Demolding resistance and ejection scheme  
5.2 Ejector layout and component strength  
5.3 Return, travel limit, guidance, and precision location  
5.4 Cycle and heat balance  
5.5 Coolant flow, channel diameter, velocity, Reynolds number, pressure loss, and heat-transfer area  
5.6 Water-path layout, sealing, machinability, and uniformity

Show the ejection layout after the force and contact-surface analysis. Show the cooling layout only after flow/diameter/velocity closure and compare the required length with the modeled path.

### 6 Mold base, assembly, and final machine matching

6.1 Standard and mold-base selection  
6.2 Plates, support, fasteners, and standard components  
6.3 Assembly and opening sequence  
6.4 BOM and drawing set  
6.5 Shot capacity/volume, pressure, clamp force, mold thickness, tie-bar spacing, platen, nozzle, locating ring, opening stroke, ejection stroke/force, and mounting checks  
6.6 Manufacturing, assembly, maintenance, and safety

Place the assembly section and BOM before the final machine check so the actual overall dimensions drive validation.

### 7 Moldflow verification and optimization

Include only executed cases. Report geometry/material/mesh/settings before results. Analyze filling, pressure, temperature, weld lines, air traps, shear, cooling, shrinkage, and warpage only when the selected analysis sequence supports them. Compare schemes with non-study variables held constant.

### End matter

- conclusions;
- references;
- acknowledgements;
- appendices: calculation book, assembly and part drawings, BOM, process card, study manifests.

Write abstracts and conclusions last. Conclusions may summarize only results already established in the body. Do not invent acknowledgement recipients.

## Placement matrix rule

Assign every object a stable ID and record:

`object_id, object_type, caption, section_id, first_mention, insertion_position, purpose, source_or_artifact, file, Word bookmark/field, status`.

Use this paragraph pattern:

1. Introduce why the object is needed.
2. Present the figure, table, or equation nearby.
3. Interpret it and state its effect on the next design decision.

Reject orphaned figures, tables, formulas, drawings, and citations.
