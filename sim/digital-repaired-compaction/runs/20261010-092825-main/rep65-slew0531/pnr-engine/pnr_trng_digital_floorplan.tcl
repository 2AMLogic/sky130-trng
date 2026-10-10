read_liberty /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_lef /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /home/ubuntu/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef
read_verilog /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-251/sim/digital-synthesis/runs/20260910-001436-a4c3194/50khz-constrained-trng_digital_synth.v
link_design trng_digital
create_clock -name clk -period 20000.0 [get_ports clk]
set_max_transition 0.531 [current_design]
set klt_clock_port [get_ports clk]
set klt_non_clock_inputs [lsearch -inline -all -not -exact [all_inputs] $klt_clock_port]
set_input_delay 4000.0 -clock clk $klt_non_clock_inputs
set_output_delay 4000.0 -clock clk [all_outputs]
initialize_floorplan -utilization 65 -aspect_ratio 1.0 -core_space 5 -site unithd
make_tracks
tapcell -distance 14 -tapcell_master sky130_fd_sc_hd__tapvpwrvgnd_1
add_global_connection -net {VPWR} -inst_pattern {.*} -pin_pattern {^VDD$} -power
add_global_connection -net {VPWR} -inst_pattern {.*} -pin_pattern {^VDDPE$}
add_global_connection -net {VPWR} -inst_pattern {.*} -pin_pattern {^VDDCE$}
add_global_connection -net {VPWR} -inst_pattern {.*} -pin_pattern {VPWR}
add_global_connection -net {VPWR} -inst_pattern {.*} -pin_pattern {VPB}
add_global_connection -net {VGND} -inst_pattern {.*} -pin_pattern {^VSS$} -ground
add_global_connection -net {VGND} -inst_pattern {.*} -pin_pattern {^VSSE$}
add_global_connection -net {VGND} -inst_pattern {.*} -pin_pattern {VGND}
add_global_connection -net {VGND} -inst_pattern {.*} -pin_pattern {VNB}
global_connect
set_voltage_domain -name {CORE} -power {VPWR} -ground {VGND}
define_pdn_grid -name {grid} -voltage_domains {CORE} -pins {met5}
add_pdn_stripe -grid {grid} -layer {met1} -width {0.48} -pitch {5.44} -offset {0.0} -followpins
add_pdn_stripe -grid {grid} -layer {met4} -width {1.6} -pitch {27.14} -offset {13.57}
add_pdn_stripe -grid {grid} -layer {met5} -width {1.6} -pitch {27.2} -offset {13.6}
add_pdn_connect -grid {grid} -layers {met1 met4}
add_pdn_connect -grid {grid} -layers {met4 met5}
pdngen
report_worst_slack_metric -setup
report_tns_metric -setup
report_worst_slack_metric -hold
report_design_area_metrics
write_db /home/ubuntu/GitHub/sky130-trng/.loom/worktrees/issue-251/sim/digital-repaired-compaction/requests/.klt/place-and-route/trng_digital_floorplan.odb
