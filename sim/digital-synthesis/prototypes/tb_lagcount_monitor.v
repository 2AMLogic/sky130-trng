// Self-checking helper for DR-0015's prototype: feeds NBITS samples from
// +STIM=<file> (one 0/1 per line) and prints the 1-based sample index at which
// `alarm` first asserts (0 if never). The expected value comes from
// digital/model/lagcount.py; see sim/tests/test_health_detection_coverage.py.
`timescale 1ns/1ps
module tb_lagcount_monitor;
    parameter LAGS = 8, WIN_BITS = 6, CUTOFF = 40, NBITS = 1024;
    reg clk = 0, rst_n = 0, en = 0, din = 0;
    wire alarm;
    reg [0:0] mem [0:NBITS-1];
    integer i, first;
    reg [1023:0] stim;
    lagcount_monitor #(.LAGS(LAGS), .WIN_BITS(WIN_BITS), .CUTOFF(CUTOFF)) dut (
        .clk(clk), .rst_n(rst_n), .en(en), .din(din), .alarm(alarm));
    always #5 clk = ~clk;
    initial begin
        if (!$value$plusargs("STIM=%s", stim)) begin $display("no +STIM"); $finish; end
        $readmemb(stim, mem);
        first = 0;
        #12 rst_n = 1;
        for (i = 0; i < NBITS; i = i + 1) begin
            @(negedge clk);
            din = mem[i]; en = 1;
            @(posedge clk); #1;
            if (alarm && first == 0) first = i + 1;
        end
        $display("FIRST_ALARM %0d", first);
        $finish;
    end
endmodule
