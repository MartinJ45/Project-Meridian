# Evaluation report

Run 2026-11-24T17:06:33+00:00 · 25 cases × 2 repeat(s) · models answering: gemini-3.8-flash
Fresh knowledge base built from the committed dataset and extraction output; empty correction journal.

## Summary

| Metric | Value |
|---|---|
| Pass rate (all checks in a case) | 46/50 (92%) |
| Reproducibility (same pass/fail and same drawings opened across repeats) | 23/25 cases |
| Latency median / p90 / max | 4.6 s / 10.7 s / 43.8 s |
| Tokens per turn (median) | 8082 in / 234 out incl. thinking |
| Turns needing a fallback model | 0 |

## By category

| Category | Passed |
|---|---|
| bonus-graph | 2/2 |
| bonus-learning | 2/2 |
| bonus-suppliers | 3/4 |
| clean-vs-noisy | 6/6 |
| drawing-bom | 4/4 |
| drawing-fields | 2/2 |
| interfaces | 4/4 |
| materials | 4/4 |
| multi-turn | 2/2 |
| organization | 2/2 |
| supplier-cost | 2/4 |
| uncertainty | 9/10 |
| visual | 4/4 |

## Cases

### org-subsystems (organization) - PASS

> Which subsystems do the 30 drawings cover, and how many drawings are in each?

Opened: -; 3D: -; 10.3 s

<details><summary>Answer (first run)</summary>

According to the Drawing Index, the 30 drawings (D-001 through D-030) cover **6 subsystems** with the following distribution:

- **Z-axis**: 8 drawings (D-023 to D-030) [Drawing Index]
- **Box**: 5 drawings (D-001 to D-005) [Drawing Index]
- **Powder**: 5 drawings (D-006 to D-010) [Drawing Index]
- **Recoater**: 5 drawings (D-011 to D-015) [Drawing Index]
- **Optical**: 5 drawings (D-016 to D-020) [Drawing Index]
- **Gas Flow**: 2 drawings (D-021, D-022) [Drawing Index]

*(Note: In the BOM snapshot, the corresponding families are named Box, Powder, Recoater, Optics, Gas flow, and Build-plate [BOM Index]).*

</details>

### org-degraded (clean-vs-noisy) - PASS

> Which drawings are degraded scans?

Opened: D-001, D-003, D-009, D-011, D-020, D-022, D-023, D-030; 3D: -; 7.9 s

<details><summary>Answer (first run)</summary>

According to the drawing index, the following 8 drawings are classified as **DEGRADED scan**:

- **D-001** (Door x2, Box)
- **D-003** (Main Platform Loop2, Box)
- **D-009** (Powder Canister, Powder)
- **D-011** (Recoater Arm, Recoater)
- **D-020** (f-theta-Seal Ring, Optical)
- **D-022** (Inlet Box, Gas Flow)
- **D-023** (Build Cylinder v2, Z-axis)
- **D-030** (Z-axis Motor Plate, Z-axis)

</details>

### link-confirmed (drawing-bom) - PASS

> Which BOM row corresponds to the build plate drawing, and how sure is that link?

Opened: D-026; 3D: -; 10.7 s

<details><summary>Answer (first run)</summary>

The build plate drawing **D-026** ("Bygge Plade") corresponds to **BOM row 48** ("Build Plate") [BOM row 48, D-026 p1].

### Link Confidence
- **Status:** **CONFIRMED** [D-026 p1 BOM link].
- **Basis:** The drawing title block explicitly reads "Build Plate" matching the BOM item name, the file name is "ByggePlade", and both specify stainless steel (drawing: "AISI 316 Stainless Steel Sheet (SS)" [D-026 p1 title block]; BOM: "Stainless steel,Steel" [BOM row 48]).

### Consistency Notes
- **Material:** Agreement, though the drawing provides the specific grade ("AISI 316 Stainless Steel Sheet (SS)" [D-026 p1 title block]) while the BOM records "Stainless steel,Steel" [BOM row 48].
- **Quantity:** There is a conflict: the drawing note indicates `1-3 stk af hver` ("1-3") [D-026 p1 title block], whereas the BOM records an amount of `10` [BOM row 48].

</details>

### link-ambiguous (drawing-bom) - PASS

> Which BOM row does the powder bracket drawing D-008 correspond to?

Opened: D-008; 3D: -; 4.5 s

<details><summary>Answer (first run)</summary>

The drawing link for **D-008** (*Powder Bracket*) is currently marked as **PROBABLE** (a matter of judgment) rather than confirmed, linking to two possible BOM rows:

- **BOM row 91**: *Powder handling mount bracket* [BOM row 91]
- **BOM row 93**: *Powder stepper bracket* [BOM row 93]

### Reason for Ambiguity
The title block of D-008 gives the title "Powder Bracket" and notes "2-3mm non-magnetic stainless. / 6x M5 weld nuts" [D-008 p1]. Both candidates are custom stainless steel parts in the Powder subsystem [BOM row 91, BOM row 93]. Because the drawing title does not match either specific BOM name, the sheet does not disambiguate between them.

*(Note: BOM row 93 is also linked as a probable match to drawing D-010 [D-010]).*

</details>

### link-none (uncertainty) - PASS

> Which BOM row is the Z-axis bottom plate drawing?

Opened: D-029; 3D: -; 2.9 s

<details><summary>Answer (first run)</summary>

The Z-axis bottom plate drawing (D-029) does not link to any BOM row (link status: NONE) [D-029 p1].

No row in the BOM describes or names a Z-axis bottom plate. While row 49 is listed as "Motor plate" [BOM row 49], that row belongs to drawing D-030 (Z-axis Motor Plate) [D-030 p1].

</details>

### iface-out (interfaces) - PASS

> What does the Left Side Box interface with?

Opened: D-002; 3D: -; 3.6 s

<details><summary>Answer (first run)</summary>

According to the BOM, the **Left Side Box** (BOM row 10) interfaces with the following parts [BOM row 10]:

- **Print Platform** [BOM row 13]
- **Top Side** [BOM row 14]
- **Front Side Box** [BOM row 15]
- **Back Box** [BOM row 12]

Note: Drawing D-002 (Left Wall) has a probable link to BOM row 10 based on sheet notes, but physical interfaces are recorded in the BOM's "Interface with" column rather than detailed as explicit interface metadata on drawing sheet D-002 [D-002 p1, BOM row 10].

</details>

### iface-in (interfaces) - PASS

> Which parts list the Front Door as an interface?

Opened: D-001; 3D: -; 3.7 s

<details><summary>Answer (first run)</summary>

According to the BOM's 'Interface with' records, the **Front Door** (BOM row 11) is listed as an interface by three parts [BOM row 11]:

- **Front Side Box** [BOM row 15]
- **Front door hinge** [BOM row 21]
- **Front door latch** [BOM row 22]

*(Note: Conversely, BOM row 11 records its own outbound interface with the **Front Side Box** [BOM row 11]).*

</details>

### mat-shared (materials) - PASS

> Which drawings specify EN-AW 5005?

Opened: D-012, D-013, D-014, D-024, D-025, D-028; 3D: D-012, D-025; 4.7 s

<details><summary>Answer (first run)</summary>

According to the drawing index, the following 6 drawings specify **3.3315 (EN-AW 5005)** in their title blocks:

- **D-012** (Recoater Mount Block) [D-012]
- **D-013** (Recoater Plate) [D-013]
- **D-014** (Recoater Stage Plate) [D-014]
- **D-024** (Bygge Base) [D-024]
- **D-025** (Bygge Base Ring Version2) [D-025]
- **D-028** (Varme Element Plade) [D-028]

*(Note: Where linked to the BOM, the BOM lists the material more generally as "Aluminium" for rows 31, 32, 47, and 51, while D-013 and D-025 currently have no linked BOM rows).* [BOM row 31, 32, 47, 51; D-012, D-013, D-014, D-024, D-025, D-028]

</details>

### mat-compare (materials) - PASS

> What material is the cylinder clamp ring, according to its drawing and the BOM?

Opened: D-027; 3D: D-027; 3.3 s

<details><summary>Answer (first run)</summary>

According to the evidence for the cylinder clamp ring (confirmed link between drawing D-027 and BOM row 50):

- **BOM row 50** records the broad material class: **Aluminium** [BOM row 50].
- **Drawing D-027** specifies the exact alloy and temper: **6063-T6** [D-027 p1].

Additionally, the title block note on drawing D-027 permits: *"Brug gerne EN AW-6000, AW-2000 / eller AW-7000 serie aluminium"* (acceptable to use EN AW-6000, AW-2000, or AW-7000 series aluminium) [D-027 p1].

The two sources agree on the general material family, with the drawing providing greater specificity.

</details>

### supplier-cost (supplier-cost) - FAIL

> Who supplied the laser source, what was its recorded cost, and can I still buy it at that price?

Opened: -; 3D: -; 3.3 s

Failed checks (first run): mentions MFSC-300W | 300W | 300 W

<details><summary>Answer (first run)</summary>

According to the pinned BOM snapshot:

- **Supplier:** Max Photonics [BOM row 84]
- **Recorded Cost:** 45,000.00 DKK (unit and total) [BOM row 84]

Regarding whether you can still buy it at that price: the cost and supplier values reflect a pinned historical BOM snapshot, not live availability or current pricing. You would need to check directly with the supplier or run a new search to confirm current pricing.

</details>

### supplier-order (supplier-cost) - PASS

> What is the supplier order number for the silicone gun?

Opened: -; 3D: -; 7.2 s

<details><summary>Answer (first run)</summary>

According to the pinned BOM snapshot, the supplier order number for the **Silicone gun** is **174-791** from supplier **RS components** [BOM row 2].

</details>

### noisy-empty (clean-vs-noisy) - PASS

> What weight does the door drawing D-001 give?

Opened: D-001; 3D: -; 3.1 s

<details><summary>Answer (first run)</summary>

The drawing **D-001** does not provide a weight. The **WEIGHT [g]** box is present on the sheet's title block, but it is explicitly **empty** [D-001 p1 title block].

</details>

### noisy-partial (clean-vs-noisy) - PASS

> What material does the Z-axis motor plate drawing's title block give?

Opened: D-030; 3D: -; 4.4 s

<details><summary>Answer (first run)</summary>

On drawing **D-030** (Z-axis Motor Plate):

- The dedicated **MATERIAL** box in the title block is present but **EMPTY on the sheet** [D-030 p1 title block].
- However, the **NOTE** field in the title block states: `NOTE: Z-axis MotorPlate Aluminium` (reading noted as partial legibility with slight discrepancy between passes: `Z-axis MotorPlate Aluminium`) [D-030 p1 title block].

For comparison, the probably linked BOM entry records **Aluminium** [BOM row 49].

</details>

### conflict-list (uncertainty) - PASS

> Where do the drawings and the BOM disagree?

Opened: D-003, D-018, D-021, D-022, D-026; 3D: -; 5.1 s

<details><summary>Answer (first run)</summary>

Based on the machine-wide drawing vs. BOM consistency review, the following disagreements and mismatches are recorded:

### 1. Quantity Conflicts
- **Galvo Mount Side x2 / Galvo box bracket**:
  - Drawing: states **2** [D-018 title / note]
  - BOM: records amount **1** [BOM row 81]
- **Build Plate (Bygge Plade)**:
  - Drawing: states **1-3** [D-026 title / note]
  - BOM: records amount **10** [BOM row 48]

### 2. Material Recorded on Drawing but Missing in BOM
- **Gas flow inlet geometry (Inlet Box)**:
  - Drawing: specifies *"Stainless / Free choice of thickness"* [D-022 p1 title block note]
  - BOM: no material recorded (empty) [BOM row 62]

### 3. Material Missing on Drawing but Recorded in BOM
- **Main Platform Loop2 / Print Platform**:
  - Drawing: material box is empty [D-003]
  - BOM: records **Aluminium** [BOM row 13]
- **Blower Outlet / Gas flow end duct**:
  - Drawing: material box is empty [D-021]
  - BOM: records **Polymer** [BOM row 61]

*(Note: There are also 12 checked pairs where the drawing specifies a more specific alloy/grade than the generic category listed in the BOM, such as "EN-AW 5005" vs "Aluminium").*

</details>

### conflict-qty (uncertainty) - PASS

> How many build plates does the BOM record, and does the drawing agree?

Opened: D-026; 3D: -; 3.4 s

<details><summary>Answer (first run)</summary>

The BOM records **10** build plates [BOM row 48].

The drawing does not agree:
- **Drawing D-026 note:** specifies "1-3 stk af hver" (1–3 pcs of each) [D-026 p1 title block].
- **BOM row 48 amount:** records 10 [BOM row 48].

This is flagged as a direct quantity conflict between the drawing and the BOM.

</details>

### ambiguous-dim (uncertainty) - PASS

> What is the thickness of the build base ring?

Opened: D-025; 3D: D-025; 3.4 s

<details><summary>Answer (first run)</summary>

According to the drawing for the build base ring (**D-025**, *Bygge Base Ring*), the thickness is recorded as **3,0** (with a step/feature dimension of **2,0**) [D-025 p1].

*Note on links:* Drawing D-025 has no confirmed link to any BOM row (reviewed decision: NONE) [D-025 BOM link]. The 3D model shown in the app is a reconstruction from 2D drawing evidence, not native CAD.

</details>

### unsupported (uncertainty) - FLAKY

> What is the machine's maximum build rate in cm3 per hour?

Opened: -; 3D: -; 3.3 s

<details><summary>Answer (first run)</summary>

The provided drawings and BOM evidence do not contain data on the machine's maximum build rate (or volumetric productivity in cm³/h). Neither the technical drawings nor the pinned BOM snapshot record this specification.

</details>

### open-3d-block (visual) - PASS

> Show me the recoater mount block.

Opened: D-012; 3D: D-012; 4.1 s

<details><summary>Answer (first run)</summary>

Opening drawing **D-012** for the **Recoater Mount Block** (with reconstructed 3D model available; note that 3D models are reconstructions from 2D drawing evidence, not native CAD).

### Summary
- **Subsystem / Drawing**: Recoater, D-012 [D-012 p1 title block]
- **Link Status**: CONFIRMED link to BOM row 32 [D-012 BOM link]
- **Design Intent**: "Threaded block that connect stage plate and arm" [BOM row 32]
- **Material**: Drawing specifies **3.3315 (EN-AW 5005)** [D-012 p1 title block], whereas the BOM records **Aluminium** [BOM row 32] (drawing is more specific).
- **Supplier**: DTU [BOM row 32]
- **Key Dimensions**: 120.0 mm height, 25.0 +0.1/-0.5 mm width, 15.0 ±1.0 mm thickness [D-012 p1]
- **Weight**: 117.3 g [D-012 p1 title block]

</details>

### open-danish (visual) - PASS

> Show me the heating element plate.

Opened: D-028; 3D: -; 7.1 s

<details><summary>Answer (first run)</summary>

### Heating Element Plate (D-028 / BOM Row 51)

The **Heating element plate** (*Varmeelement Plade*) is a custom Z-axis / Build-plate component linked with **CONFIRMED** status to drawing **D-028** [BOM row 51, D-028 p1]. Note that no 3D reconstruction model is available for this sheet [D-028].

#### Drawing Details (D-028)
- **Title**: Varmeelement Plade [D-028 p1 title block]
- **Material**: `3.3315 (EN-AW 5005)` [D-028 p1 title block]
- **Weight**: 1.2 g [D-028 p1 title block]
- **General Tolerance**: DIN ISO 2768-1 m [D-028 p1 title block]
- **Scale & Sheet**: Scale 5:1, A3, Sheet 1 OF 1 [D-028 p1 title block]
- **Date & Company**: 22/11/2021, DTU MPP [D-028 p1 title block]
- **Finish box**: Empty on the sheet [D-028 p1 title block]
- **Dimensions**: Thickness 3,0 / 2,0; center-to-center distance 19,0; overall height 11,0; corner radius R5,5 [D-028 p1]
- **Hole Callouts**:
  - `2 x ∅ 4,5 THRU ALL` [D-028 p1]
  - `∅ 8,0 ±0,15 THRU` [D-028 p1]

#### BOM Record (Row 51)
- **Supplier**: DTU [BOM row 51]
- **Quantity**: 3 (Sheet note also specifies "3 styk") [BOM row 51, D-028 p1 title block]
- **Status**: Design Done, Order Recieved, V&V Good [BOM row 51]
- **Total Cost**: 0.00 DKK [BOM row 51]

#### Drawing vs. BOM Consistency
- **Material**: AGREE (drawing is more specific). The drawing specifies `3.3315 (EN-AW 5005)` [D-028 p1 title block] while the BOM records `Aluminium` [BOM row 51].
- **Quantity**: AGREE. Both specify 3 parts [D-028 p1 title block, BOM row 51].
- **Interfaces**: None are recorded in the BOM for row 51.

</details>

### dims (drawing-fields) - PASS

> What are the main dimensions on the cylinder clamp ring drawing?

Opened: D-027; 3D: D-027; 5.2 s

<details><summary>Answer (first run)</summary>

According to the drawing for the Cylinder Spænd Ring (Build cylinder clamp ring) [D-027 p1, BOM row 50], the main recorded dimensions and features are:

- **Outer diameter:** ∅ 330,0 [D-027 p1]
- **Inner diameter:** ∅ 264,0 H8 (+0,081 / 0,000) [D-027 p1]
- **Thickness:** 15,0 [D-027 p1]
- **Bolt circle radius:** R148,5 [D-027 p1]
- **Angular spacing:** 60° and 120° [D-027 p1]

### Hole Callouts:
- **Counterbored holes:** 3 x ∅ 11,0 THRU ALL / ⌵ ∅ 24,4 X 90° / Obs. Ekstra undersænkning [D-027 p1]
- **Through holes:** 6 x ∅ 9,0 THRU ALL [D-027 p1]
- **Counterbores:** 3 x ⌴ ∅ 20,0 H7 (+0,021 / 0,000) ↧ 4,0 ±0,05 [D-027 p1]

*(Note: 3D models shown for this part are reconstructions from 2D drawing evidence, not native CAD.)*

</details>

### followup (multi-turn) - PASS

> Show me the build cylinder drawing.
> What material is it made of?

Opened: D-023; 3D: -; 3.4 s

<details><summary>Answer (first run)</summary>

The build cylinder is made of aluminium, with the drawing providing a more specific specification than the BOM:

- **Drawing specification**: The title block specifies the material as **EN AW-6082** [D-023 p1 title block]. A drawing note further clarifies that it is based on an "*EN AW-6082 T6 rør fra Alumeco*" (EN AW-6082 T6 tube) [D-023 p1 title block].
- **BOM record**: The BOM generically records the material as **Aluminium** [BOM row 46].

</details>

### graph-open (bonus-graph) - PASS

> Show the Left Side Box and its interfaces in the knowledge graph.

Opened: D-002; 3D: -; 5.4 s

<details><summary>Answer (first run)</summary>

### Left Side Box (BOM Row 10 / Drawing D-002)

- **Drawing Link:** Drawing [D-002 p1] ("Left Wall") has a **PROBABLE** link to BOM row 10 based on the note *"Left Wall, 2mm non-magnetic stainless"*.
- **Material:** Both agree on stainless steel—the BOM lists `Stainless steel` [BOM row 10] and drawing D-002 notes `2mm non-magnetic stainless` [D-002 p1 title block] (the title block MATERIAL box is empty).

### Recorded Interfaces [BOM row 10]
According to the BOM's "Interface with" column [BOM row 10], the **Left Side Box** interfaces with:
- **Back Box** [BOM row 12, Box]
- **Front Side Box** [BOM row 15, Box]
- **Print Platform** [BOM row 13, Box]
- **Top Side** [BOM row 14, Box]

*(Note: It is also reciprocally listed as an interface by Back Box [BOM row 12], Top Side [BOM row 14], and Front Side Box [BOM row 15].)*

</details>

### supplier-leads (bonus-suppliers) - PASS

> Who could manufacture the cylinder clamp ring, and who supplied it originally?

Opened: D-027; 3D: D-027; 5.5 s

<details><summary>Answer (first run)</summary>

### Original Supplier
- **BOM Record:** The pinned BOM snapshot records **DTU** as the supplier for the build cylinder clamp ring [BOM row 50]. The drawing title block also identifies the company as **DTU MPP** [D-027 p1 title block].

### Potential Manufacturers
The part requires precision turning/milling, drilling, counterboring, and countersinking of a Ø330.0 mm ring made from **6063-T6** aluminum [D-027 p1]. Note that a drawing note also allows using EN AW-6000, AW-2000, or AW-7000 series aluminum [D-027 p1 title block].

1. **Other BOM Suppliers (same material class):**
   - **DTU** (custom machining, recorded across 22 aluminum rows)
   - **Misumi** (standard components)
   - **RS components** (standard components)
   - **EuroVacuumProducts.com**

2. **Web-Search Leads (unverified leads, retrieved 2026-11-24; may be out of date):**
   - **Prototech ApS** (Odense, Denmark) – Machines 6063-grade aluminum with lathe swing capacity up to Ø650 mm for single-piece prototypes.
   - **MSSP Group (Maskinfabrikken Silkeborg Spåntagning A/S)** (Silkeborg, Denmark) – Turning capacity up to Ø500 mm for high-precision custom parts.
   - **Kvisgaards Maskinfabrik A/S** (Havdrup / Brøndby, Denmark) – High-precision aluminum machining starting from 1 unit.
   - **Ringsted Maskinfabrik ApS** (Ringsted, Denmark) – Custom aluminum subcontracting for single-unit runs with tight tolerances.

</details>

### supplier-nosearch (bonus-suppliers) - FLAKY

> Who could make the recoater mount block for us?

Opened: D-012; 3D: D-012; 5.5 s

<details><summary>Answer (first run)</summary>

Based on the evidence for the **Recoater Mount Block** (drawing [D-012 p1], linked to [BOM row 32]):

### 1. Recorded Supplier (Pinned BOM Snapshot)
* **DTU** is recorded as the supplier [BOM row 32]. Note that the drawing title block also lists the company as **DTU MPP** [D-012 p1 title block].

### 2. Other BOM Suppliers of the Same Material Class (Aluminium)
If looking at other suppliers recorded in the BOM who supply aluminium parts:
* **Misumi** (e.g., standard pulleys, idlers, clamp plates) [BOM row 39, 40, 43]
* **RS components** (e.g., structural profiles and brackets) [BOM row 23, 24]
* **EuroVacuumProducts.com** [BOM row 64]

### 3. Web Search Leads
* No external web search has been run yet for this part. You can run one directly in the drawing's **Suppliers tab**.

*(Note: Drawing D-012 has a 3D reconstruction available in the viewer, which is reconstructed from 2D drawing evidence rather than native CAD. The drawing specifies the material as EN-AW 5005 [D-012 p1 title block], whereas the BOM records it more generally as Aluminium [BOM row 32].)*

</details>

### link-correct (bonus-learning) - PASS

> Drawing D-001 only shows the front door, not the back door. Please correct its BOM link to row 11.

Opened: D-001; 3D: -; 4.2 s

<details><summary>Answer (first run)</summary>

I have submitted a correction to update the BOM link for drawing D-001 from rows 11, 17 to row 11 only [D-001].

Note that this correction is pending human review in the Review tab, and answers or links will not change until it has been accepted.

### Current Recorded Status:
- **Drawing D-001**: Note states `'Door - x2 / 3mm aluminium'`, with reviewed status `probable: 11,17` [D-001 p1 title block].
- **BOM Row 11 (Front Door)**: Custom Aluminium part, amount 1, design intent includes a window [BOM row 11].
- **BOM Row 17 (Back Door)**: Custom Aluminium part, amount 1, design intent specifies no window [BOM row 17].

_Filed as correction #1 (pending review)._

</details>

## Correction before/after

Question: *How many Galvo box brackets does the BOM record for BOM row 81?*

**Before**

The BOM records an amount of **1** for BOM row 81 ("Galvo box bracket") [BOM row 81].

Note that there is a quantity conflict with the probably linked drawing D-018 ("Galvo Mount Side x2"), which specifies **2** pieces ("2 stk.") [D-018 p1 title block].

**Proposal in chat:** *The amount for BOM row 81 (Galvo box bracket) is wrong: drawing D-018 says x2, so it should be 2.*

The BOM records an amount of **1** for row 81 (Galvo box bracket) [BOM row 81], whereas drawing D-018 indicates **2** ('Galvo Mount Side x2', note: '2 stk. / Alu.') [D-018 p1 title block]. Note that the link between D-018 and BOM row 81 is currently classified as **PROBABLE** based on judgment (sheet title 'Galvo Mount Side x2' matching the Optical bracket row) [D-018 BOM link].

A correction has been submitted to update the amount of BOM row 81 to **2**. This correction is pending human review in the Review tab; answers will not change until it has been accepted.

_Filed as correction #3 (pending review)._

**Automated checks shown to the reviewer**

- ✓ subject exists: BOM row 81: Galvo box bracket
- ✓ changes something: new value differs from all active values
- ✓ independent sources: active values come from ['bom']
- ✓ drawing evidence: D-018 states 2 pieces -> consistent

**Reviewer accepted** correction #3.

**After**

The BOM actively records a quantity of **2** for BOM row 81 [correction 3].

* Originally, the BOM recorded an amount of 1 [BOM row 81], but this was superseded by accepted [correction 3], updating the amount to 2.
* This matches the probable drawing D-018 (*Galvo Mount Side x2*), which specifies a quantity of 2 ("2 stk.") [D-018 p1 title block].

**Outcome**

- correction filed: yes
- drawing check ran: yes
- answer changed: yes
- original kept: yes
- quantity conflict resolved: yes

Facts for BOM row 81 `amount` after acceptance:

- 1 [BOM row 81] superseded
- 2 [correction 3] active
