read_db /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-236/sim/digital-electrical-repair/requests/.klt/place-and-route/trng_digital_route.odb
define_corners ff_100C_1v65 ff_100C_1v95 ff_n40C_1v56 ff_n40C_1v65 ff_n40C_1v76 ff_n40C_1v95 ss_100C_1v40 ss_100C_1v60 ss_n40C_1v28 ss_n40C_1v35 ss_n40C_1v40 ss_n40C_1v44 ss_n40C_1v60 ss_n40C_1v76 tt_025C_1v80 tt_100C_1v80
read_liberty -corner ff_100C_1v65 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ff_100C_1v65.lib
read_liberty -corner ff_100C_1v95 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ff_100C_1v95.lib
read_liberty -corner ff_n40C_1v56 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ff_n40C_1v56.lib
read_liberty -corner ff_n40C_1v65 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ff_n40C_1v65.lib
read_liberty -corner ff_n40C_1v76 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ff_n40C_1v76.lib
read_liberty -corner ff_n40C_1v95 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ff_n40C_1v95.lib
read_liberty -corner ss_100C_1v40 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_100C_1v40.lib
read_liberty -corner ss_100C_1v60 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_100C_1v60.lib
read_liberty -corner ss_n40C_1v28 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_n40C_1v28.lib
read_liberty -corner ss_n40C_1v35 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_n40C_1v35.lib
read_liberty -corner ss_n40C_1v40 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_n40C_1v40.lib
read_liberty -corner ss_n40C_1v44 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_n40C_1v44.lib
read_liberty -corner ss_n40C_1v60 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_n40C_1v60.lib
read_liberty -corner ss_n40C_1v76 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_n40C_1v76.lib
read_liberty -corner tt_025C_1v80 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_liberty -corner tt_100C_1v80 /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_100C_1v80.lib
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
