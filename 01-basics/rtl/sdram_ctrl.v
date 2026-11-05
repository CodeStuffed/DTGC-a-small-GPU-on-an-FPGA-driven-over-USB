// SDRAM controller for the 32-bit SDRAM inside the GW2AR-18 (11 row bits, 8 column bits, 4 banks).
// It does one job at a time: a line request (refreshes, then optionally a burst of reads) or a
// single word write or read. Line requests always win, so the video scan-out never waits long.
//
// Each bank keeps its last row open, because opening a row is what costs the time. A write to a row
// that is already open takes one clock instead of about eight. Refresh closes every row.
//
// The SDRAM clock is the inverted system clock, so commands launched on a rising system edge are
// sampled half a cycle later. With CAS latency 2, read data is sampled 2 system clocks after the
// command. Timing values below are conservative at 25.2 MHz (39.7 ns), but the exact chip's
// datasheet is not known: see docs/verify.md.
`timescale 1ns / 1ps

module sdram_ctrl #(
    parameter INIT_CYCLES = 10000,       // power-up wait: at least 200 us up to 50 MHz
    parameter INIT_REFRESHES = 8,
    parameter REFRESHES_PER_LINE = 3,    // 3 per 31.8 us line beats 4096 per 64 ms
    parameter LINE_WORDS = 85,           // 340 pixels / 4 per word
    parameter T_RP = 2,                  // cycles from PRECHARGE to the next command
    parameter T_RCD = 2,                 // cycles from ACTIVE to READ or WRITE
    parameter T_RC = 4,                  // cycles from REFRESH to the next command
    parameter T_MRD = 2,                 // cycles from MODE REGISTER SET to the next command
    parameter T_WR = 3                   // cycles from WRITE to PRECHARGE
) (
    input  wire        clk,
    input  wire        rst,              // synchronous, active high
    output reg         init_done,

    // Line port: a one-clock pulse on line_req. Reads LINE_WORDS words from column 0 if line_read.
    input  wire        line_req,
    input  wire        line_read,
    input  wire [1:0]  line_bank,
    input  wire [10:0] line_row,
    output reg         rd_valid,
    output reg  [31:0] rd_data,

    // Write port: a word is taken on any clock with wr_valid and wr_ready both high.
    input  wire        wr_valid,
    output wire        wr_ready,
    input  wire [1:0]  wr_bank,
    input  wire [10:0] wr_row,
    input  wire [7:0]  wr_col,
    input  wire [31:0] wr_data,
    input  wire [3:0]  wr_be,            // byte enables, high means write this byte

    // Read port: taken like a write. Reads rr_len words (1 to 8) from rr_col upward, and rr_done
    // pulses once for each, with the word on rd_data.
    input  wire        rr_valid,
    output wire        rr_ready,
    input  wire [1:0]  rr_bank,
    input  wire [10:0] rr_row,
    input  wire [7:0]  rr_col,
    input  wire [3:0]  rr_len,
    output reg         rr_done,

    // SDRAM pins
    output reg         sdram_cke,
    output wire        sdram_cs_n,
    output wire        sdram_ras_n,
    output wire        sdram_cas_n,
    output wire        sdram_we_n,
    output reg  [1:0]  sdram_ba,
    output reg  [10:0] sdram_addr,
    output reg  [3:0]  sdram_dqm,
    output reg  [31:0] sdram_dq_out,
    output reg         sdram_dq_oe,
    input  wire [31:0] sdram_dq_in
);

    // {cs_n, ras_n, cas_n, we_n}
    localparam CMD_NOP       = 4'b0111;
    localparam CMD_ACTIVE    = 4'b0011;
    localparam CMD_READ      = 4'b0101;
    localparam CMD_WRITE     = 4'b0100;
    localparam CMD_PRECHARGE = 4'b0010;
    localparam CMD_REFRESH   = 4'b0001;
    localparam CMD_MODE      = 4'b0000;

    // Burst length 1, sequential, CAS latency 2, normal writes.
    localparam [10:0] MODE_VALUE = 11'b000_0010_0000;

    localparam S_INIT_PRE     = 4'd0;
    localparam S_INIT_REFRESH = 4'd1;
    localparam S_INIT_MODE    = 4'd2;
    localparam S_IDLE         = 4'd3;
    localparam S_WRITE        = 4'd4;
    localparam S_PRECHARGE    = 4'd5;
    localparam S_REFRESH      = 4'd6;
    localparam S_ACTIVE_READ  = 4'd7;
    localparam S_READ         = 4'd8;
    localparam S_WORD_READ    = 4'd9;
    localparam S_CLOSE_ROW    = 4'd10;
    localparam S_OPEN_ROW     = 4'd11;

    // Clocks after a single-word READ before the next command, so read data has left the pins
    // before a write can drive them.
    localparam [12:0] READ_GAP = 13'd3;

    reg [3:0]  state;
    reg [13:0] wait_cnt;     // clocks of NOP left before the next command
    reg [3:0]  cmd;
    reg [3:0]  refresh_left;
    reg [7:0]  col;
    reg [1:0]  read_pipe;

    reg        line_pending;
    reg        pending_read;
    reg [1:0]  pending_bank;
    reg [10:0] pending_row;

    // Which row each bank has open, and clocks left before a just-written bank may be closed.
    reg [3:0]  open_valid;
    reg [10:0] open_row [0:3];
    reg [1:0]  recover;
    wire write_hit = open_valid[wr_bank] && open_row[wr_bank] == wr_row;
    wire read_hit  = open_valid[rr_bank] && open_row[rr_bank] == rr_row;

    // Held while a request that missed waits for its row to open.
    reg [1:0]  req_bank;
    reg [10:0] req_row;
    reg        req_read;
    reg [7:0]  write_col;
    reg [3:0]  words_left;
    reg [31:0] write_data;
    reg [3:0]  write_be;

    assign {sdram_cs_n, sdram_ras_n, sdram_cas_n, sdram_we_n} = cmd;

    assign wr_ready = init_done && state == S_IDLE && wait_cnt == 0 && !line_pending && !line_req;
    assign rr_ready = wr_ready && !wr_valid;

    // True while the read on its way through read_pipe is a single word, not part of a line.
    reg word_read;

    always @(posedge clk) begin
        cmd         <= CMD_NOP;
        sdram_dq_oe <= 1'b0;
        rd_valid    <= 1'b0;
        rr_done     <= 1'b0;
        read_pipe   <= {read_pipe[0], 1'b0};
        if (recover != 0) recover <= recover - 1'b1;

        // Registered read data: read_pipe[1] marks the clock the data is valid on the pins.
        if (read_pipe[1]) begin
            rd_valid <= !word_read;
            rr_done  <= word_read;
            rd_data  <= sdram_dq_in;
        end

        // Requests from before init finishes are dropped: nothing in memory needs reading yet.
        if (line_req && init_done) begin
            line_pending <= 1'b1;
            pending_read <= line_read;
            pending_bank <= line_bank;
            pending_row  <= line_row;
        end

        if (rst) begin
            state        <= S_INIT_PRE;
            wait_cnt     <= INIT_CYCLES;
            refresh_left <= INIT_REFRESHES;
            init_done    <= 1'b0;
            line_pending <= 1'b0;
            read_pipe    <= 2'b00;
            open_valid   <= 4'b0000;
            recover      <= 2'd0;
            sdram_cke    <= 1'b1;
            sdram_dqm    <= 4'b1111;
            sdram_ba     <= 2'b00;
            sdram_addr   <= 11'd0;
            sdram_dq_out <= 32'd0;
        end else if (wait_cnt != 0) begin
            wait_cnt <= wait_cnt - 1'b1;
        end else begin
            case (state)
                S_INIT_PRE: begin
                    cmd        <= CMD_PRECHARGE;
                    sdram_addr <= 11'b100_0000_0000;  // A10 high: all banks
                    wait_cnt   <= T_RP - 1;
                    state      <= S_INIT_REFRESH;
                end
                S_INIT_REFRESH: begin
                    cmd          <= CMD_REFRESH;
                    wait_cnt     <= T_RC - 1;
                    refresh_left <= refresh_left - 1'b1;
                    if (refresh_left == 1) state <= S_INIT_MODE;
                end
                S_INIT_MODE: begin
                    cmd        <= CMD_MODE;
                    sdram_ba   <= 2'b00;
                    sdram_addr <= MODE_VALUE;
                    sdram_dqm  <= 4'b0000;
                    wait_cnt   <= T_MRD - 1;
                    state      <= S_IDLE;
                    init_done  <= 1'b1;
                end
                S_IDLE: begin
                    if (line_pending) begin
                        if (open_valid == 4'b0000) begin
                            line_pending <= 1'b0;
                            refresh_left <= REFRESHES_PER_LINE;
                            state        <= S_REFRESH;
                        end else if (recover == 0) begin
                            cmd        <= CMD_PRECHARGE;
                            sdram_addr <= 11'b100_0000_0000;
                            open_valid <= 4'b0000;
                            wait_cnt   <= T_RP - 1;
                        end
                    end else if (wr_valid && wr_ready) begin
                        if (write_hit) begin
                            cmd          <= CMD_WRITE;
                            sdram_ba     <= wr_bank;
                            sdram_addr   <= {3'b000, wr_col};
                            sdram_dq_out <= wr_data;
                            sdram_dq_oe  <= 1'b1;
                            sdram_dqm    <= ~wr_be;
                            recover      <= T_WR - 1;
                        end else begin
                            req_bank   <= wr_bank;
                            req_row    <= wr_row;
                            req_read   <= 1'b0;
                            write_col  <= wr_col;
                            write_data <= wr_data;
                            write_be   <= wr_be;
                            state      <= open_valid[wr_bank] ? S_CLOSE_ROW : S_OPEN_ROW;
                        end
                    end else if (rr_valid && rr_ready) begin
                        if (read_hit) begin
                            cmd        <= CMD_READ;
                            sdram_ba   <= rr_bank;
                            sdram_addr <= {3'b000, rr_col};
                            sdram_dqm  <= 4'b0000;
                            read_pipe  <= {read_pipe[0], 1'b1};
                            word_read  <= 1'b1;
                            if (rr_len == 1) begin
                                wait_cnt <= READ_GAP;
                            end else begin
                                write_col  <= rr_col + 1'b1;
                                words_left <= rr_len - 1'b1;
                                state      <= S_WORD_READ;
                            end
                        end else begin
                            req_bank   <= rr_bank;
                            req_row    <= rr_row;
                            req_read   <= 1'b1;
                            write_col  <= rr_col;
                            words_left <= rr_len;
                            state     <= open_valid[rr_bank] ? S_CLOSE_ROW : S_OPEN_ROW;
                        end
                    end
                end
                S_CLOSE_ROW: if (recover == 0) begin
                    cmd        <= CMD_PRECHARGE;
                    sdram_ba   <= req_bank;
                    sdram_addr <= 11'b000_0000_0000;  // A10 low: this bank only
                    wait_cnt   <= T_RP - 1;
                    state      <= S_OPEN_ROW;
                end
                S_OPEN_ROW: begin
                    cmd                  <= CMD_ACTIVE;
                    sdram_ba             <= req_bank;
                    sdram_addr           <= req_row;
                    open_valid[req_bank] <= 1'b1;
                    open_row[req_bank]   <= req_row;
                    wait_cnt             <= T_RCD - 1;
                    state                <= req_read ? S_WORD_READ : S_WRITE;
                end
                S_WORD_READ: begin
                    cmd        <= CMD_READ;
                    sdram_addr <= {3'b000, write_col};
                    sdram_dqm  <= 4'b0000;
                    read_pipe  <= {read_pipe[0], 1'b1};
                    word_read  <= 1'b1;
                    write_col  <= write_col + 1'b1;
                    words_left <= words_left - 1'b1;
                    if (words_left == 1) begin
                        wait_cnt <= READ_GAP;
                        state    <= S_IDLE;
                    end
                end
                S_WRITE: begin
                    cmd          <= CMD_WRITE;
                    sdram_addr   <= {3'b000, write_col};
                    sdram_dq_out <= write_data;
                    sdram_dq_oe  <= 1'b1;
                    sdram_dqm    <= ~write_be;
                    recover      <= T_WR - 1;
                    state        <= S_IDLE;
                end
                S_PRECHARGE: begin
                    cmd        <= CMD_PRECHARGE;
                    sdram_addr <= 11'b100_0000_0000;
                    sdram_dqm  <= 4'b0000;
                    wait_cnt   <= T_RP - 1;
                    state      <= S_IDLE;
                end
                S_REFRESH: begin
                    cmd          <= CMD_REFRESH;
                    wait_cnt     <= T_RC - 1;
                    refresh_left <= refresh_left - 1'b1;
                    if (refresh_left == 1) state <= pending_read ? S_ACTIVE_READ : S_IDLE;
                end
                S_ACTIVE_READ: begin
                    cmd        <= CMD_ACTIVE;
                    sdram_ba   <= pending_bank;
                    sdram_addr <= pending_row;
                    sdram_dqm  <= 4'b0000;
                    col        <= 8'd0;
                    wait_cnt   <= T_RCD - 1;
                    state      <= S_READ;
                end
                S_READ: begin
                    cmd        <= CMD_READ;
                    sdram_addr <= {3'b000, col};
                    read_pipe  <= {read_pipe[0], 1'b1};
                    word_read  <= 1'b0;
                    col        <= col + 1'b1;
                    if (col == LINE_WORDS - 1) begin
                        wait_cnt <= 13'd1;
                        state    <= S_PRECHARGE;
                    end
                end
                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
