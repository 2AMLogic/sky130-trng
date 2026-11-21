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

## Submission on 2026-11-21 UTC

The criterion above was committed at `b6d3867f` before submission. The coupled
deck SHA-256 was `b21d2a5ceea3dfa4466b9b3172c9ea415e0f056076180141909fc0a128c4747c`.
The saved request specifies `20p 100n` and nine measurements, including four
ring voltages at the 100 ns endpoint. Its plan also records the underlying
75-cycle stimulus length of 7,870 ns. The generator exposes the two internal
sampler nets as additional analog subcircuit pins. The gate model supplies the
logic rails and bridges and uses Liberty SHA-256
`8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135`.

Commands from the repository root, with an empty output directory for generation:

```bash
block="$PWD/sim/post-layout-whole-block"
run="$block/runs/20261121-coupled-probe"
python3 "$block/make-requests.py" "$run/requests" --set coupled-probe
req="$run/requests/coupled-probe/request.json"
klt sim "$req" --backend batch --dry-run -o "$run/out"
klt sim "$req" --backend batch -o "$run/out" --report-out "$run/report.json"
```

`klt 0.9.2.dev111+g978f7464fae1` validated exactly one unit. The first live
invocation (00:36:59–00:37:01) requested the provisioning-script path and exited
before assigning an ID. With `KLT_BATCH_PROVISION_SCRIPT` set to 2am's
`infra/aws/batch-fleet-provision.sh` and AWS CLI on PATH, the batch client
emitted the following receipt. Progress was captured from its default stderr
stream. [Submission log](../runs/20261121-coupled-probe/submit-stderr.log)
and [timestamps](../runs/20261121-coupled-probe/submit-timing.log).

| Probe outcome | Observed |
| --- | --- |
| Client job ID | `klt-sim-9ffb4c91eb0f` |
| Client elapsed | 2 s (00:38:48–00:38:50 UTC), exit 1 |
| Last step reached | First netlist upload. AWS CLI reported that the `batch-runner-submit` profile was unavailable. |
| Simulated time reached | No worker launched. No simulator wall time or transient samples. |
| Measured s per simulated ns | Unavailable |
| Digital responses | 0 compared, 0 matched. No report or waveforms were produced. |

**Feasibility is undetermined.** The failed upload supplies no runtime bound.
The full program still needs a qualifying probe on a host with the fleet
submit profile. The grid keeps its historical 21,600 s worker and 6,600 s poll
settings pending that evidence. There is no measured figure to report against
the upstream whole-job ceiling. The nominal experiment carries no
characterization credit.
