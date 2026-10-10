read_db /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_place.odb
read_liberty /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
create_clock -name clk -period 20000.0 [get_ports clk]
set_max_transition 0.531 [current_design]
set_max_capacitance 0.034 [current_design]
set klt_clock_port [get_ports clk]
set klt_non_clock_inputs [lsearch -inline -all -not -exact [all_inputs] $klt_clock_port]
set_input_delay 4000.0 -clock clk $klt_non_clock_inputs
set_output_delay 4000.0 -clock clk [all_outputs]
set_wire_rc -layer met2
estimate_parasitics -placement
set _klt_cts_seq_sinks [llength [all_registers -clock [get_clocks {clk}]]]
if {$_klt_cts_seq_sinks > 0} {
clock_tree_synthesis -root_buf sky130_fd_sc_hd__buf_4 -buf_list sky130_fd_sc_hd__buf_4 -sink_clustering_enable -obstruction_aware
estimate_parasitics -placement
repair_timing -hold
} else {
puts "klt place-and-route: clock clk has no sequential (registered) fanout -- skipping clock_tree_synthesis (see issue #1506)"
}
detailed_placement
write_def /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital.cts.def
report_worst_slack_metric -setup
report_tns_metric -setup
report_worst_slack_metric -hold
report_design_area_metrics
report_fmax_metric
report_power_metric
report_clock_skew_metric -setup
puts "===KLT_SETUP_VIOLATIONS_BEGIN==="
report_check_types -max_delay -violators -format end
puts "===KLT_SETUP_VIOLATIONS_END==="
puts "===KLT_HOLD_VIOLATIONS_BEGIN==="
report_check_types -min_delay -violators -format end
puts "===KLT_HOLD_VIOLATIONS_END==="
write_db /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_cts.odb
