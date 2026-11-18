# Astra job: sonar science research and briefs (docs/SONAR-SCIENCE.md)

Lane: mac, `gpt-6.2-astra`, effort `high`. Read-only on everything except the output paths below.
Scratch: `/private/tmp/deepsignal/sonar-science/` only. Desk copy to read: `/private/tmp/deepsignal/desk-main/`
(already pulled to ee7622d or later; never edit desk-main itself). Write outputs under
`/private/tmp/deepsignal/sonar-science/out/` mirroring desk paths.

## Goal
Eugene (RVTEC ship tech, project owner) wants DeepSignal to extract much more science and QC value from the
ship's acoustic systems: Kongsberg EM multibeam (bathymetry, seafloor backscatter, water column), Kongsberg
SBP29 sub-bottom profiler, EK80/EA single-beam (broadband), and Teledyne RDI ADCP (UHDAS/VmDAS), using
genuinely novel math. His standing principle: use all available good data, within reason, to improve
outcomes: fuse sensors, cross-check them, weight each by its measured quality.

## Read first (do not duplicate)
- `docs/SHIP-SYSTEMS.md` (all of it, esp. sections 2, 3.1-3.6, 4, 5, 13). Already planned there: #139
  Kongsberg tap (summaries), #140 SV consistency, #141 depth consensus (simple % threshold), #142 time and
  motion alignment, #143 sonar health, #144 transmit awareness, #145 ADCP health, #147 SVP cast tracker.
  Your ideas must BUILD ON these (reuse their field names), not restate them.
- `briefs/p2/139-kongsberg-tap.md`, `140-sv-consistency.md`, `141-depth-consensus.md`, `145-adcp-health.md`.
- `briefs/TEMPLATE.md` and `briefs/p2/141-depth-consensus.md` as the brief format to copy.
- `research/2026-11-18-drift-detection-report.md` and `research/2026-11-18-reanalysis-program.md` if
  present (evidence graph, verdict states incl. AMBIGUOUS, ledger rules). Reuse those conventions.
- `docs/REFERENCE.md` (numbering and status vocabulary).

## Hard constraints
1. Listen-only (D-SHIP1). Never write to, configure, or trigger any sonar. Inputs are live UDP datagrams
   the operator already distributes, file tails of `.kmall`/`.all`/`.kmwcd`/`.raw`/SEG-Y/PD0/UHDAS
   output, or archived files. Say for each idea which input path it needs and whether it is live or
   post-processing.
2. Public formats only (KMALL and .all specs, EK80 .raw as read by pyEcholab/echopype, SEG-Y, PD0).
   Mark any field offset you are not sure of as "lead to verify".
3. Pure Python on Linux; numpy/scipy allowed if pinned (state it). No GPU required; a ship PC must run
   live modes. Heavy methods may be post-cruise or reanalysis-only; say which.
4. Never silently change data: outputs are new fields, scores, flags, or ledger corrections that a person
   approves (match the project's "score plus persistence plus plain explanation, never a delete").
5. Honesty: label every method ESTABLISHED (published and used), ADAPTED (published elsewhere, new to
   ship DAS), or NOVEL (your construction). For NOVEL, write the math precisely enough that a reviewer can
   check it: state model, priors, estimator, identifiability conditions, failure modes. Cite prior art as
   "lead to verify" with author/year; do not invent citations.

## Candidate areas (seed list; add, merge or drop with reasons)
- Water column: gas seep detection and flux proxy; plankton/fish scattering layers and diel migration;
  fused with EK80 broadband frequency response and ADCP backscatter (three frequencies, three geometries).
- Seafloor backscatter: angular-response based classification with physics priors (e.g. Jackson/APL-94
  type models), calibration drift between surveys, cross-frequency (EM124 vs EM712 vs EM2040).
- Refraction residual sound-speed inversion: infer the SV profile error from outer-beam curl and crossing
  swaths, before the tech notices "smiles/frowns"; tie to #140 and #147.
- Sub-bottom (SBP29 chirp): automatic layer tracking across pings, sediment impedance/attenuation
  inversion, ties to multibeam backscatter for seafloor type.
- Multi-sensor depth fusion: replace #141's threshold with a quality-weighted estimator over MB nadir,
  single-beams, ADCP bottom track, SBP first return, grid prior; per-sensor bias and noise learned online.
- Uncertainty quantification: per-sounding total propagated uncertainty from live measured inputs
  (motion, SV, timing from #142), calibrated against crosslines; conformal or Bayesian intervals.
- Anything else of high value: e.g. vessel self-noise/interference mapping from the sonars themselves,
  bubble-sweepdown detection (weather vs hull aeration) from dropouts, current shear from ADCP fused with
  water-column layer tilt, patch-test (roll/pitch/latency bias) estimation from ordinary survey lines.

## Output 1: `out/docs/SONAR-SCIENCE.md`
Plain, precise English, no em dashes, headings and tables, under ~45 KB.
1. One-paragraph answer with the top 3 picks and why.
2. Ranked table: rank, provisional id, name, systems, live or post, value techs/science/shore (1-5 each),
   effort S/M/L, novelty label, depends on (#139 etc.), status (BRIEFED or PROPOSED).
3. One section per idea: problem in a tech's words; method (math, with equations); data needed (exact
   datagrams/fields, rates, which ships have it); expected value to techs and to scientists (concrete);
   feasibility (compute, data access, risk); validation plan (public datasets, synthetic truth, metrics,
   pass threshold, what would falsify it); failure modes.
4. A "fusion backbone" section: one shared estimation framework (e.g. factor graph or state-space model)
   that several ideas plug into, so we build it once. Say what it costs and what it buys.
5. Public validation data leads (NCEI water-column archive, R2R, GMRT, known seep sites), each "lead to
   verify".
6. Open decisions for Eugene (non-blocking), each with a recommended default.

Use ids #162 to #173 in rank order (reserved by the build lead). #161 (sound-speed fusion) already exists on desk main: read its rows in docs/REFERENCE.md and docs/IDEAS.md and any brief for it, cross-reference it, and build the refraction-residual SV inversion on it rather than duplicating it.

Eugene asked for extremely novel math: most picks should be NOVEL constructions with derivations a reviewer can check, not reuses of published methods. Still label honestly.

## Output 2: briefs for the top 5
`out/briefs/p2/<id>-<slug>.md`, following the format of `briefs/p2/141-depth-consensus.md`: lane (cloud
Sol medium for pure scaffolding and tests; mac Astra for estimator code), risk tier, module, branch
`deepsignal/p2-<slug>`, depends on, goal, background facts, failing test first, synthetic-truth test
fixtures, acceptance commands, scope, trust boundaries, non-goals. Each brief must be buildable without
reading SONAR-SCIENCE.md.

## Report
List files written, the top 5 with one line each, every "lead to verify", and anything you were unsure of.
Do not download any sonar data to the Mac (Eugene: mind disk space); validation datasets are named, not
fetched. Do not push, commit to desk-main, or contact any network service other than read-only web lookups.
