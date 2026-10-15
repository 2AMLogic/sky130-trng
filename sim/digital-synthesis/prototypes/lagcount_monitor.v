// STUDY PROTOTYPE -- DR-0015 / issue #301. Not part of trng_digital, not adopted.
//
// Bounded lag-k match-count monitor: LAGS parallel match counters over a WIN-
// comparison window, sticky alarm when any lag's count reaches CUTOFF at the
// window end. Normative behaviour: digital/model/lagcount.py (LagCountMonitor).
// Exists only so the monitor's area can be synthesised against sky130_fd_sc_hd
// (sim/digital-synthesis/harness/synthesize-lagcount-prototype.py); it is not
// wired into digital/rtl/trng_digital.v and no register-map plumbing exists.
//
// 50 kHz sample-clock domain, one `en` strobe per raw sample (en = 1 every
// cycle models the block's sample clock). WIN must be a power of two,
// 2**WIN_BITS. CUTOFF is the derived C_L (not a free constant).
module lagcount_monitor #(
    parameter LAGS     = 32,
    parameter WIN_BITS = 12,
    parameter CUTOFF   = 2670
) (
    input  wire clk,
    input  wire rst_n,
    input  wire en,
    input  wire din,
    output reg  alarm
);
    localparam WIN = (1 << WIN_BITS);
    localparam CW  = WIN_BITS + 1;       // counts 0..WIN
    localparam FW  = $clog2(LAGS + 1);   // warm-up counter, 0..LAGS

    reg [LAGS-1:0]     hist;             // hist[j-1] = x[i-j]
    reg [FW-1:0]       fill;
    reg [WIN_BITS-1:0] idx;
    reg [CW-1:0]       cnt [0:LAGS-1];

    wire warm   = (fill == LAGS);
    wire last   = (idx == WIN - 1);
    wire [LAGS-1:0] match = ~(hist ^ {LAGS{din}});

    reg [LAGS-1:0] over;
    integer j;
    always @* begin
        for (j = 0; j < LAGS; j = j + 1)
            over[j] = ((cnt[j] + {{(CW-1){1'b0}}, match[j]}) >= CUTOFF);
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            hist  <= {LAGS{1'b0}};
            fill  <= {FW{1'b0}};
            idx   <= {WIN_BITS{1'b0}};
            alarm <= 1'b0;
            for (j = 0; j < LAGS; j = j + 1) cnt[j] <= {CW{1'b0}};
        end else if (en) begin
            hist <= {hist[LAGS-2:0], din};
            if (!warm) begin
                fill <= fill + 1'b1;
            end else begin
                if (last) begin
                    if (|over) alarm <= 1'b1;
                    idx <= {WIN_BITS{1'b0}};
                    for (j = 0; j < LAGS; j = j + 1) cnt[j] <= {CW{1'b0}};
                end else begin
                    idx <= idx + 1'b1;
                    for (j = 0; j < LAGS; j = j + 1)
                        cnt[j] <= cnt[j] + {{(CW-1){1'b0}}, match[j]};
                end
            end
        end
    end
endmodule
