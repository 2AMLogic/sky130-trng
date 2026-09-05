// -----------------------------------------------------------------------
// tb_trng_digital -- file-driven co-simulation testbench.
//
// Reads one stimulus line per clock cycle and writes one observation line
// per clock cycle. It contains no expected values of its own: the reference
// is digital/model/digital_top.py, and the comparison happens in
// sim/digital-rtl-equivalence/harness/rtl-cosim.py. That split is deliberate
// -- a testbench that carries its own golden vectors can only ever confirm
// what its author believed, whereas this one is a transcriber.
//
// Timing contract (matches the model's cycle contract exactly):
//   * clk has a posedge at t = 5, 15, 25, ... and a negedge at 10, 20, ...
//   * at each negedge the testbench FIRST records the outputs -- which are
//     the start-of-cycle values, since the previous posedge -- and THEN
//     drives the inputs for the cycle whose posedge is next.
//   * so observation line N and stimulus line N describe the same cycle,
//     just as `obs = observe(); update(stim)` does in the model.
//
//   iverilog -g2005 -o build/tb digital/rtl/trng_digital.v digital/tb/tb_trng_digital.v
//   vvp build/tb +stim=<path> +obs=<path>
// -----------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module tb_trng_digital;

    reg         clk = 1'b0;
    reg         rst_n = 1'b0;
    reg         raw_bit = 1'b0;
    reg         raw_valid = 1'b0;
    reg  [3:0]  bus_addr = 4'd0;
    reg         bus_we = 1'b0;
    reg         bus_re = 1'b0;
    reg  [31:0] bus_wdata = 32'd0;
    reg         out_ready = 1'b0;

    wire [31:0] bus_rdata;
    wire [31:0] out_data;
    wire        out_valid, alarm, gated, startup_done;

    trng_digital dut (
        .clk(clk), .rst_n(rst_n),
        .raw_bit(raw_bit), .raw_valid(raw_valid),
        .bus_addr(bus_addr), .bus_we(bus_we), .bus_re(bus_re),
        .bus_wdata(bus_wdata), .bus_rdata(bus_rdata),
        .out_data(out_data), .out_valid(out_valid), .out_ready(out_ready),
        .alarm(alarm), .gated(gated), .startup_done(startup_done)
    );

    always #5 clk = ~clk;

    integer fin, fout, code, cycles;
    reg [1023:0] stim_path, obs_path;
    integer v_raw_bit, v_raw_valid, v_addr, v_we, v_re, v_ready;
    reg [31:0] v_wdata;

    initial begin
        if (!$value$plusargs("stim=%s", stim_path)) begin
            $display("FATAL: +stim=<path> required");
            $finish;
        end
        if (!$value$plusargs("obs=%s", obs_path)) begin
            $display("FATAL: +obs=<path> required");
            $finish;
        end
        fin = $fopen(stim_path, "r");
        fout = $fopen(obs_path, "w");
        if (fin == 0 || fout == 0) begin
            $display("FATAL: could not open stimulus/observation file");
            $finish;
        end

        cycles = 0;
        rst_n = 1'b0;
        @(negedge clk);          // the posedge at t=5 applied the async reset
        rst_n = 1'b1;

        forever begin
            code = $fscanf(fin, "%d %d %d %d %d %h %d\n",
                           v_raw_bit, v_raw_valid, v_addr, v_we, v_re,
                           v_wdata, v_ready);
            if (code != 7) begin
                $fclose(fin);
                $fclose(fout);
                $display("tb_trng_digital: %0d cycles transcribed", cycles);
                $finish;
            end

            // 1. record the outputs visible DURING this cycle
            $fdisplay(fout, "%08x %0d %08x %0d %0d %0d",
                      bus_rdata, out_valid, out_data, alarm, gated,
                      startup_done);

            // 2. drive the inputs this cycle's posedge will act on
            raw_bit   = v_raw_bit[0];
            raw_valid = v_raw_valid[0];
            bus_addr  = v_addr[3:0];
            bus_we    = v_we[0];
            bus_re    = v_re[0];
            bus_wdata = v_wdata;
            out_ready = v_ready[0];

            cycles = cycles + 1;
            @(negedge clk);
        end
    end

endmodule

`default_nettype wire
