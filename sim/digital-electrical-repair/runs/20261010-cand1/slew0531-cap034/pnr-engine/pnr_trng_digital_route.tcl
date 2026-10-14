read_db /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_cts.odb
read_liberty /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
create_clock -name clk -period 20000.0 [get_ports clk]
set_max_transition 0.531 [current_design]
set_max_capacitance 0.034 [current_design]
set klt_clock_port [get_ports clk]
set klt_non_clock_inputs [lsearch -inline -all -not -exact [all_inputs] $klt_clock_port]
set_input_delay 4000.0 -clock clk $klt_non_clock_inputs
set_output_delay 4000.0 -clock clk [all_outputs]
set_routing_layers -signal met1-met5
global_route
file delete -force /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_route_pass_0_drc.rpt /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_route_pass_0_maze.log
utl::push_metrics_stage "route_pass:0__{}"
detailed_route -output_drc /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_route_pass_0_drc.rpt -output_maze /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_route_pass_0_maze.log -or_seed 20260905
utl::pop_metrics_stage
repair_antennas sky130_fd_sc_hd__diode_2
file delete -force /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_route_drc.rpt /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_route_maze.log
detailed_route -output_drc /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_route_drc.rpt -output_maze /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_route_maze.log -or_seed 20260905
puts "===KLT_ANTENNA_VIOLATIONS_BEGIN==="
check_antennas
puts "===KLT_ANTENNA_VIOLATIONS_END==="
filler_placement {sky130_fd_sc_hd__fill_1 sky130_fd_sc_hd__fill_2 sky130_fd_sc_hd__fill_4 sky130_fd_sc_hd__fill_8}
global_connect
estimate_parasitics -global_routing
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
write_def /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital.def
write_verilog /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital.v -remove_cells {sky130_fd_sc_hd__tapvpwrvgnd_1 sky130_fd_sc_hd__fill_1 sky130_fd_sc_hd__fill_2 sky130_fd_sc_hd__fill_4 sky130_fd_sc_hd__fill_8}
write_db /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_route.odb
