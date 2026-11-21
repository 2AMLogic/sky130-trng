# Nominal coupled whole-block rate experiment (#596)

## Criterion fixed before fleet submission

The unit ceiling is 3,480 s. Reserve 480 s for overhead and variation. The
coupled circuit must run at or below **3,000 s / 7,870 ns = 0.38119 s/ns**.
First run 100 ns on the batch fleet. A completed probe within that budget
qualifies the full 75-cycle program for submission. It ends before the first
clock edge at 320 ns and supplies no digital comparison. For either unit, use
the worker's elapsed simulation time and the simulated time actually reached.
A refusal before simulation yields no rate.

A feasible result also requires the full 7,870 ns and digital responses that
agree with normative replay, including the program's expected valid strobes.
Record functional agreement separately from speed. Only that full result can
size the matrix in #307.

Level: mixed-level (analog transistor / digital gate-level), connectivity-only extract (no R/C).
At tt / 27 °C / 1.8 V, #595 is open. Use the recorded gate model's
`tt_025C_1v80` Liberty deck and its declared per-input `input_load` for this
timing experiment. O5d, O7, O8 and #18 AC3 remain UNMET.
