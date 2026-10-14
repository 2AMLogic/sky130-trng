read_db /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-251/sim/digital-repaired-compaction/requests/.klt/place-and-route/trng_digital_route.odb
define_corners ss_n40C_1v44
read_liberty -corner ss_n40C_1v44 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_n40C_1v44.lib
create_clock -name clk -period 20000.0 [get_ports clk]
set klt_clock_port [get_ports clk]
set klt_non_clock_inputs [lsearch -inline -all -not -exact [all_inputs] $klt_clock_port]
set_input_delay 4000.0 -clock clk $klt_non_clock_inputs
set_output_delay 4000.0 -clock clk [all_outputs]
set_wire_rc -layer met2
estimate_parasitics -global_routing
puts "===KLT_MAX_TRANSITION_LIBRARY_VIOLATIONS_BEGIN==="
report_check_types -max_slew -violators
puts "===KLT_MAX_TRANSITION_LIBRARY_VIOLATIONS_END==="
puts "===KLT_MAX_CAPACITANCE_LIBRARY_VIOLATIONS_BEGIN==="
report_check_types -max_capacitance -violators
puts "===KLT_MAX_CAPACITANCE_LIBRARY_VIOLATIONS_END==="
set_max_transition 0.531 [current_design]
report_worst_slack_metric -setup
report_worst_slack_metric -hold
report_tns_metric -setup
report_tns_metric -hold
puts "===KLT_MAX_TRANSITION_VIOLATIONS_BEGIN==="
report_check_types -max_slew -violators
puts "===KLT_MAX_TRANSITION_VIOLATIONS_END==="
puts "===KLT_MAX_CAPACITANCE_VIOLATIONS_BEGIN==="
report_check_types -max_capacitance -violators
puts "===KLT_MAX_CAPACITANCE_VIOLATIONS_END==="
