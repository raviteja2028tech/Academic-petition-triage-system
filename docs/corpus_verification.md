# Corpus verification — VTU B.E./B.Tech. Regulations 2025

Verified on 2026-10-28 by extracting the text of `corpus/VTU B.Tech. Regulations 2025.pdf` with PyMuPDF and `pdftotext`, then reading the relevant pages. Quotations are copied from the extracted text. Page = PDF page = printed page number (checked on p18/p19: printed "- 18 -" / "- 19 -").

## 1. Document facts
* Title: *VTU Regulations Governing the UG Programmes B.E. and B.Tech. – 2025* (cover p1; running header on all pages).
* Scope, Preamble "Short Title, Application and Commencement" (p6): "(1.2) These Regulations shall apply to all the B.E./B.Tech. Programmes conducted at the Departments of Visvesvaraya Technological University, its Constituent Colleges, and autonomous and non-autonomous affiliated colleges." and "(1.4) These Regulations shall be applicable to the batch of students admitted from the academic year 2025-26 onwards and shall remain in force until revised or withdrawn by a formal notification issued by the University."
* Clause identifiers are printed like `25OB10.0` with sub-items `(1)`, `(2)`… or `(a)`, `(i)`.
* Not verified: that this is the latest/official version (see `corpus/SOURCES.md`).

## 2. Verified provisions

| # | Identifier as printed | Page | What it establishes | Key quotation |
|---|-----------------------|------|---------------------|---------------|
| V1 | 25OB10.0 (3) Attendance Requirement | 18 | Attendance is computed **per course** | "Every prescribed course shall be treated as a unit for the calculation of attendance." |
| V2 | 25OB10.0 (4) | 18 | **Base rule: minimum 85 % in each registered course** | "A student who cannot fulfil 100 % attendance shall be required to secure a minimum attendance of 85 % in each registered course." |
| V3 | 25OB10.0 (5) | 19 | **Condonation provision**: shortage up to a maximum of 10 % below 85 % may be condoned by the **Vice-Chancellor**, on recommendation of Dean/Principal/Chairperson/Programme Coordinator; grounds include **medical reasons**; valid documentary evidence required; course coordinator/instructor recommends and forwards via Principal etc. to Registrar (Evaluation) before the last working day of the semester | "If the attendance in a course, fall below 85 %, a shortage up to a maximum of 10 % may be condoned by the Vice-Chancellor, based on the specific recommendations of the Dean/ Principal of the college/ Chairperson/Programme Coordinator where the candidate is studying. This provision shall be utilised only on valid grounds, such as: (i) Medical reasons … All such cases shall be supported by valid documentary evidence." |
| V4 | 25OB10.0 (7) | 19 | Consequence of non-compliance: not permitted to appear for SEE of that course; grade **DX**; summer-semester re-registration | "A student who does not satisfy the attendance requirement … shall not be permitted to appear for the Semester End Examinations of those courses. The shortage of attendance … shall be indicated by the letter grade DX" |
| V5 | Table 25OB23.0.1 (25OB23.0) | 28 | DX = attendance **below 75 %** | "DX — Attendance below 75 % in a credit or non-credit courses. (Students shall repeat the course by re-registering for the same course during summer semester)." |
| V6 | 25OB8.2 (iv) | 17 | Attendance and CIE are SEE-eligibility conditions | "only those students who satisfy the attendance requirement (25OB 3.7) and CIE requirement (25OB 4.2) shall be eligible to appear for SEE of that course." |
| V7 | 25OB9.0 (c) | 18 | Related discretion: students with satisfactory attendance who miss SEE for valid reasons (health etc.) may be permitted a later exam subject to recommendation and University approval | "Permission to appear for the Semester End Examination (SEE) shall be granted at the discretion of the University, and the decision of the Vice-Chancellor in such matters shall be final and binding." |
| V8 | 25OB24.1 (a),(b) | 29 | Attendance is a vertical-progression requirement; DX students may re-enrol in summer | "Students who obtain grades such as DX (not satisfying the attendance requirement) … shall be permitted to re-enrol for such course(s) during the summer semester." |
| V9 | 25OB34.0 (2),(3) | 38 | University may issue directions and amend | "the University shall have the power to issue directions/ orders to address and removal of any difficulties arising in the implementation of these Regulations." |

## 3. Findings that affect the design

1. **Interval derived from V2+V3+V5 (derived, not printed as one rule):** below 85 % and down to 75 % is the condonable band; below 75 % is DX and outside the stated condonation maximum. Whether "10 %" means 10 percentage points (→ 75 %) or 10 % of 85 is not stated; Table 25OB23.0.1 (75 %) supports percentage points. **Needs staff/team confirmation.**
2. **No "committee" decides condonation.** The text reserves it to the **Vice-Chancellor** on recommendation through the Principal etc. to the Registrar (Evaluation). The assignment's `refer-to-committee` route therefore maps to "refer to the Vice-Chancellor via Registrar (Evaluation)". The system must never present "grant" as a final decision for the 75–85 % medical case; it can only recommend referral/condonation consideration. This is an interpretation to confirm.
3. **Broken cross-reference:** 25OB8.2(iv) cites "25OB 3.7" and "25OB 4.2" as the attendance and CIE requirements, but attendance is 25OB10.0 and the Contents page does not list a 25OB3.7. This inconsistency is usable in the "citation resolves to retrieved text" tests.
4. **Cross-reference gap that matches the assignment:** here the base rule (p18) and condonation (p19) are adjacent, but a query like "what is the attendance requirement" can still return V2 without V3. Retrieval must be tested for both.
5. **Extraction quirk:** p18 25OB9.0(c)(i) is laid out one word per line; the chunker normalises whitespace.
6. **Revaluation:** the contents (p4) lists "VTU Regulations governing Revaluation of Answer Scripts -2025 / 25RV01" and annexures for change of branch/college, but those bodies are not in the 41 pages. Re-evaluation petitions are **NOT VERIFIED in corpus** (they should escalate).
7. Internal-evaluation grievances appear only as a committee activity (25OB11.2.2 (vii), p22); grade-grievance policy is otherwise not verified.

## 4. Missing / NOT VERIFIED
* **Examination bye-laws** (assignment §3): not in the supplied file → `NOT VERIFIED`.
* Official source URL, retrieval date, licence → `NOT VERIFIED`.
* Medical-documentation specifics beyond "valid documentary evidence" → not specified for attendance.
* Exact meaning of the "10 %" shortage → needs confirmation (finding 1).
* Whether autonomous colleges' own rules differ → NOT VERIFIED (clause 1.2 says these regulations apply to them).

## 5. Status of the difficult case (assignment §4.1)

**`PARTIALLY_VERIFIED` — core passages found; the case is NOT marked as passed.**

* Both required passages are in the corpus: base rule V2 (25OB10.0(4), p18) and condonation V3 (25OB10.0(5), p19) with medical grounds named.
* The "examination bye-laws" half of the corpus is missing (`NOT VERIFIED`) → the assignment's corpus requirement is not fully satisfied; confirm with staff whether this document alone suffices.
* Candidate synthetic test values (to confirm at Evaluation 1): course attendance **80 %** (inside the 75–<85 band) with a medical certificate → base rule not met (V2); condonation V3 applies on medical grounds with documents; decision reserved to the Vice-Chancellor on recommendation → route `refer-to-committee` (human decision), citing 25OB10.0(4) and 25OB10.0(5). Controls: **72 %** → below the condonable band (V3+V5) → reject citing 25OB10.0(4)/(7) and Table 25OB23.0.1; **86 %** → rule satisfied.
* No agent exists yet (Phase 3), so the end-to-end case is untested. Retrieval-level availability of both passages is tested in Phase 2 (`docs/retrieval_design.md`).

Confidence: high for quotations and page numbers (read directly from the text); medium for the interpretations in §3.

## Status after Phases 4-8 (no change to verified facts)
No new corpus facts were verified in Phases 4-8, and the difficult case remains **PARTIALLY_VERIFIED**: the base rule (25OB10.0(4), p18) and condonation clause (25OB10.0(5), p19) are verified; the examination bye-laws, the official source URL, redistribution terms, the meaning of "10 %" (percentage points assumed) and the decision maker (Vice-Chancellor, mapped to `refer-to-committee`) are **not** resolved. The evaluation set restricts gold clauses to the four clauses verified here (`25OB10.0(4)`, `25OB10.0(5)`, `25OB10.0(7)`, `25OB23.0`) and flags the 14 scenarios that depend on the open interpretations as `interpretation_dependent`. Passing those scenarios is technical conformance, not regulatory correctness.
