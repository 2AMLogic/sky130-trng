read_db /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_floorplan.odb
read_liberty /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
create_clock -name clk -period 20000.0 [get_ports clk]
set klt_clock_port [get_ports clk]
set klt_non_clock_inputs [lsearch -inline -all -not -exact [all_inputs] $klt_clock_port]
set_input_delay 4000.0 -clock clk $klt_non_clock_inputs
set_output_delay 4000.0 -clock clk [all_outputs]
place_pins -hor_layers met3 -ver_layers met2
set_wire_rc -layer met2
global_placement -density 0.6 -routability_driven -timing_driven -random_seed 20260905
estimate_parasitics -placement
repair_design
repair_timing
detailed_placement
report_worst_slack_metric -setup
report_tns_metric -setup
report_worst_slack_metric -hold
report_design_area_metrics
report_fmax_metric
report_power_metric
puts "===KLT_SETUP_VIOLATIONS_BEGIN==="
report_check_types -max_delay -violators -format end
puts "===KLT_SETUP_VIOLATIONS_END==="
puts "===KLT_HOLD_VIOLATIONS_BEGIN==="
report_check_types -min_delay -violators -format end
puts "===KLT_HOLD_VIOLATIONS_END==="
write_def /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital.place.def
write_db /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_place.odb
