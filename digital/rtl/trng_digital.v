// -----------------------------------------------------------------------
// trng_digital -- sky130-trng digital section
//
// Health tests (SP 800-90B RCT + APT + start-up), a non-vetted CRC-32 LFSR
// conditioner (K = 8), and the two-path register / streaming interface.
//
// Normative behaviour is digital/model/digital_top.py; this module is an
// implementation of it, and sim/digital-rtl-equivalence/ is the record that
// the two agree cycle for cycle. If they disagree, the model is right and
// this file is wrong -- the model is what the decision record
// spec/decision-records/DR-0004-sky130-digital-section-architecture.md
// describes.
//
// Clock domain: the 50 kHz sample clock (design/README.md's `clk`,
// DR-0003's operating point). The register bus is deliberately in the same
// domain -- a proper CDC to a host bus clock is named as out of scope in
// DR-0004 § "Consequences".
//
// Style note: the whole block is one clocked always block using BLOCKING
// assignments, on purpose. The model's cycle contract is explicitly ordered
// (sample -> gate -> bus write -> bus read -> stream pop), and blocking
// assignments in a single always block are the Verilog construct whose
// semantics are that same order. No other always block writes these
// registers, so there is no intra-block race; outputs are continuous
// assigns and the testbench samples them at the negedge.
// -----------------------------------------------------------------------

`default_nettype none

module trng_digital #(
    parameter integer C_RCT      = 81,    // RCT cutoff   (H = 0.5, alpha = 2^-40)
    parameter integer C_APT      = 824,   // APT cutoff   (H = 0.5, alpha = 2^-40)
    parameter integer W_APT      = 1024,  // APT window, samples
    parameter integer STARTUP    = 1024,  // start-up test length, samples
    parameter integer COND_BITS  = 256,   // raw bits per conditioned word (K = 8)
    parameter [31:0]  CRC_POLY   = 32'h04C11DB7,
    parameter [31:0]  CRC_INIT   = 32'hFFFFFFFF,
    parameter [31:0]  ID_VALUE   = 32'h54524E47  // "TRNG"
) (
    input  wire        clk,        // 50 kHz sample clock
    input  wire        rst_n,      // asynchronous, active low

    // raw tap, from trng_top (design/xschem/trng_top.sch)
    input  wire        raw_bit,
    input  wire        raw_valid,

    // register bus (word-addressed, same clock domain)
    input  wire [3:0]  bus_addr,
    input  wire        bus_we,
    input  wire        bus_re,
    input  wire [31:0] bus_wdata,
    output wire [31:0] bus_rdata,

    // streaming port, mode-selected by CTRL.OUT_MODE
    output wire [31:0] out_data,
    output wire        out_valid,
    input  wire        out_ready,

    // status pins (also visible in STATUS/ALARM)
    output wire        alarm,
    output wire        gated,
    output wire        startup_done
);

    // -- register-map word addresses --------------------------------------
    localparam [3:0] A_CTRL          = 4'h0;
    localparam [3:0] A_STATUS        = 4'h1;
    localparam [3:0] A_RAW_DATA      = 4'h2;
    localparam [3:0] A_DATA          = 4'h3;
    localparam [3:0] A_ALARM         = 4'h4;
    localparam [3:0] A_HT_RCT        = 4'h5;
    localparam [3:0] A_HT_APT        = 4'h6;
    localparam [3:0] A_HT_APT_WIN    = 4'h7;
    localparam [3:0] A_HT_STARTUP    = 4'h8;
    localparam [3:0] A_HT_COND_BLOCK = 4'h9;
    localparam [3:0] A_ID            = 4'hA;

    // -- state ------------------------------------------------------------
    reg [2:0]  ctrl;              // [0] EN, [1] OUT_MODE, [2] SOFT_RST (self-clearing)

    reg        rct_ref, rct_armed;
    reg [15:0] rct_count;
    reg        apt_ref;
    reg [15:0] apt_index, apt_matches;
    reg [15:0] startup_count;
    reg        startup_done_r;
    reg        al_rct, al_apt, al_startup;

    reg [31:0] crc_state;
    reg [15:0] cond_count;

    reg [31:0] raw_sr;
    reg [5:0]  raw_count;

    reg [31:0] raw_mem [0:3];
    reg [2:0]  raw_level;
    reg [31:0] cond_mem [0:3];
    reg [2:0]  cond_level;

    reg [31:0] bus_rdata_r;
    reg        raw_ovf, cond_ovf, raw_tap_valid;

    // scratch (procedural only)
    reg        bit_in, rct_fail, apt_fail, raised, gated_before;
    reg        fb;
    reg [31:0] rd_value;
    reg [1:0]  popped;            // 0 none, 1 raw, 2 cond
    reg [2:0]  new_ctrl;
    reg        sel_valid;
    integer    i;

    // -- combinational outputs --------------------------------------------
    wire alarm_w        = al_rct | al_apt | al_startup;
    wire gated_w        = alarm_w | ~startup_done_r;
    wire sel_cond       = ctrl[1];
    wire sel_valid_w    = sel_cond ? (cond_level != 3'd0) : (raw_level != 3'd0);

    assign bus_rdata    = bus_rdata_r;
    assign out_valid    = sel_valid_w;
    assign out_data     = sel_valid_w ? (sel_cond ? cond_mem[0] : raw_mem[0])
                                      : 32'd0;
    assign alarm        = alarm_w;
    assign gated        = gated_w;
    assign startup_done = startup_done_r;

    // -- CRC-32 next state (non-reflected, MSB-first) ----------------------
    function [31:0] crc_next;
        input [31:0] s;
        input        b;
        begin
            crc_next = ({s[30:0], 1'b0}) ^ ((s[31] ^ b) ? CRC_POLY : 32'h0);
        end
    endfunction

    // -- STATUS assembly ---------------------------------------------------
    function [31:0] status_word;
        input dummy;
        begin
            status_word = 32'h0;
            status_word[0]     = startup_done_r;
            status_word[1]     = (al_rct | al_apt | al_startup) | ~startup_done_r;
            status_word[2]     = raw_tap_valid;
            status_word[3]     = (raw_level != 3'd0);
            status_word[4]     = (cond_level != 3'd0);
            status_word[5]     = (al_rct | al_apt | al_startup);
            status_word[11:8]  = {1'b0, raw_level};
            status_word[15:12] = {1'b0, cond_level};
            status_word[16]    = raw_ovf;
            status_word[17]    = cond_ovf;
        end
    endfunction

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ctrl           = 3'b000;
            rct_ref        = 1'b0;
            rct_armed      = 1'b0;
            rct_count      = 16'd0;
            apt_ref        = 1'b0;
            apt_index      = 16'd0;
            apt_matches    = 16'd0;
            startup_count  = 16'd0;
            startup_done_r = 1'b0;
            al_rct         = 1'b0;
            al_apt         = 1'b0;
            al_startup     = 1'b0;
            crc_state      = CRC_INIT;
            cond_count     = 16'd0;
            raw_sr         = 32'd0;
            raw_count      = 6'd0;
            raw_level      = 3'd0;
            cond_level     = 3'd0;
            bus_rdata_r    = 32'd0;
            raw_ovf        = 1'b0;
            cond_ovf       = 1'b0;
            raw_tap_valid  = 1'b0;
            for (i = 0; i < 4; i = i + 1) begin
                raw_mem[i]  = 32'd0;
                cond_mem[i] = 32'd0;
            end
        end else begin
            // ---------------------------------------------------------------
            // 2/3. sample the raw tap, run the health tests, gate on failure
            // ---------------------------------------------------------------
            raw_tap_valid = raw_valid;
            rct_fail = 1'b0;
            apt_fail = 1'b0;
            raised   = 1'b0;

            if (ctrl[0] && raw_valid) begin
                bit_in       = raw_bit;
                gated_before = alarm_w | ~startup_done_r;

                // -- RCT (SP 800-90B 4.4.1)
                if (!rct_armed || (bit_in != rct_ref)) begin
                    rct_ref   = bit_in;
                    rct_armed = 1'b1;
                    rct_count = 16'd1;
                end else begin
                    rct_count = rct_count + 16'd1;
                end
                rct_fail = (rct_count >= C_RCT);

                // -- APT (SP 800-90B 4.4.2)
                if (apt_index == 16'd0) begin
                    apt_ref     = bit_in;
                    apt_matches = 16'd1;
                end else if (bit_in == apt_ref) begin
                    apt_matches = apt_matches + 16'd1;
                end
                apt_index = apt_index + 16'd1;
                if (apt_index == W_APT) begin
                    apt_fail    = (apt_matches >= C_APT);
                    apt_index   = 16'd0;
                    apt_matches = 16'd0;
                end

                if (rct_fail) al_rct = 1'b1;
                if (apt_fail) al_apt = 1'b1;
                raised = rct_fail | apt_fail;

                // -- start-up test (SP 800-90B 4.3)
                if (!startup_done_r) begin
                    if (raised) begin
                        al_startup    = 1'b1;
                        startup_count = 16'd0;
                        rct_armed     = 1'b0;
                        rct_count     = 16'd0;
                        apt_index     = 16'd0;
                        apt_matches   = 16'd0;
                    end else begin
                        startup_count = startup_count + 16'd1;
                        if (startup_count >= STARTUP)
                            startup_done_r = 1'b1;
                    end
                end else if (raised) begin
                    startup_done_r = 1'b0;
                    startup_count  = 16'd0;
                    rct_armed      = 1'b0;
                    rct_count      = 16'd0;
                    apt_index      = 16'd0;
                    apt_matches    = 16'd0;
                end

                // -- raw packer: LSB-first, 32 bits per word
                raw_sr[raw_count] = bit_in;
                raw_count = raw_count + 6'd1;
                if (raw_count == 6'd32) begin
                    if (raw_level == 3'd4) begin
                        raw_ovf = 1'b1;
                    end else begin
                        raw_mem[raw_level] = raw_sr;
                        raw_level = raw_level + 3'd1;
                    end
                    raw_sr    = 32'd0;
                    raw_count = 6'd0;
                end

                // -- conditioner: absorbs only while the path is ungated
                if (!gated_before) begin
                    crc_state  = crc_next(crc_state, bit_in);
                    cond_count = cond_count + 16'd1;
                    if (cond_count == COND_BITS) begin
                        if (cond_level == 3'd4) begin
                            cond_ovf = 1'b1;
                        end else begin
                            cond_mem[cond_level] = crc_state;
                            cond_level = cond_level + 3'd1;
                        end
                        crc_state  = CRC_INIT;
                        cond_count = 16'd0;
                    end
                end

                // -- gate: flush the CONDITIONED path only; raw is untouched
                if (raised) begin
                    crc_state  = CRC_INIT;
                    cond_count = 16'd0;
                    cond_level = 3'd0;
                end
            end

            // ---------------------------------------------------------------
            // 4. bus write
            // ---------------------------------------------------------------
            if (bus_we) begin
                case (bus_addr)
                    A_CTRL: begin
                        new_ctrl = bus_wdata[2:0];
                        if ((new_ctrl[1] ^ ctrl[1])) begin
                            // OUT_MODE switch flushes conditioner AND both FIFOs
                            crc_state  = CRC_INIT;
                            cond_count = 16'd0;
                            cond_level = 3'd0;
                            raw_level  = 3'd0;
                            raw_sr     = 32'd0;
                            raw_count  = 6'd0;
                        end
                        if (new_ctrl[2]) begin
                            // SOFT_RST: datapath + health tests; EN/OUT_MODE survive
                            rct_ref        = 1'b0;
                            rct_armed      = 1'b0;
                            rct_count      = 16'd0;
                            apt_ref        = 1'b0;
                            apt_index      = 16'd0;
                            apt_matches    = 16'd0;
                            startup_count  = 16'd0;
                            startup_done_r = 1'b0;
                            al_rct         = 1'b0;
                            al_apt         = 1'b0;
                            al_startup     = 1'b0;
                            crc_state      = CRC_INIT;
                            cond_count     = 16'd0;
                            raw_sr         = 32'd0;
                            raw_count      = 6'd0;
                            raw_level      = 3'd0;
                            cond_level     = 3'd0;
                            bus_rdata_r    = 32'd0;
                            raw_ovf        = 1'b0;
                            cond_ovf       = 1'b0;
                            raw_tap_valid  = 1'b0;
                            ctrl           = {1'b0, new_ctrl[1:0]};
                        end else begin
                            ctrl = new_ctrl;
                        end
                    end
                    A_ALARM: begin
                        if (bus_wdata[0]) al_rct     = 1'b0;
                        if (bus_wdata[1]) al_apt     = 1'b0;
                        if (bus_wdata[2]) al_startup = 1'b0;
                    end
                    default: ;
                endcase
            end

            // ---------------------------------------------------------------
            // 5. bus read (registered; pops the data FIFOs)
            // ---------------------------------------------------------------
            popped = 2'd0;
            if (bus_re) begin
                rd_value = 32'd0;
                case (bus_addr)
                    A_CTRL:          rd_value = {29'd0, ctrl};
                    A_STATUS:        rd_value = status_word(1'b0);
                    A_RAW_DATA: begin
                        // Raw access is ALWAYS available -- never gated.
                        if (raw_level != 3'd0) begin
                            rd_value = raw_mem[0];
                            popped   = 2'd1;
                        end
                    end
                    A_DATA: begin
                        if (!(al_rct | al_apt | al_startup) && startup_done_r
                            && (cond_level != 3'd0)) begin
                            rd_value = cond_mem[0];
                            popped   = 2'd2;
                        end
                    end
                    A_ALARM:         rd_value = {29'd0, al_startup, al_apt, al_rct};
                    A_HT_RCT:        rd_value = C_RCT;
                    A_HT_APT:        rd_value = C_APT;
                    A_HT_APT_WIN:    rd_value = W_APT;
                    A_HT_STARTUP:    rd_value = STARTUP;
                    A_HT_COND_BLOCK: rd_value = COND_BITS;
                    A_ID:            rd_value = ID_VALUE;
                    default:         rd_value = 32'd0;
                endcase
                bus_rdata_r = rd_value;
                if (popped == 2'd1) begin
                    for (i = 0; i < 3; i = i + 1) raw_mem[i] = raw_mem[i+1];
                    raw_level = raw_level - 3'd1;
                end else if (popped == 2'd2) begin
                    for (i = 0; i < 3; i = i + 1) cond_mem[i] = cond_mem[i+1];
                    cond_level = cond_level - 3'd1;
                end
            end

            // ---------------------------------------------------------------
            // 6. stream pop (a register read of the same FIFO wins)
            // ---------------------------------------------------------------
            sel_valid = ctrl[1] ? (cond_level != 3'd0) : (raw_level != 3'd0);
            if (out_ready && sel_valid) begin
                if (ctrl[1]) begin
                    if (popped != 2'd2) begin
                        for (i = 0; i < 3; i = i + 1) cond_mem[i] = cond_mem[i+1];
                        cond_level = cond_level - 3'd1;
                    end
                end else begin
                    if (popped != 2'd1) begin
                        for (i = 0; i < 3; i = i + 1) raw_mem[i] = raw_mem[i+1];
                        raw_level = raw_level - 3'd1;
                    end
                end
            end
        end
    end

endmodule

`default_nettype wire
