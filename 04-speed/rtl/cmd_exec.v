// Command executor: applies checked packets to the hidden buffer and the palette, keeps the sequence
// number, and replies to every packet. Behaviour must stay the same as sw/dtgc/emulator.py.
`timescale 1ns / 1ps

module cmd_exec #(
    parameter WIDTH = 340,
    parameter HEIGHT = 340,
    parameter LINE_WORDS = 85
) (
    input  wire        clk,
    input  wire        rst,

    input  wire        pkt_valid,
    input  wire        pkt_crc_ok,
    input  wire [7:0]  pkt_type,
    input  wire [7:0]  pkt_seq,
    input  wire [10:0] pkt_len,
    output reg         pkt_ack,
    output reg  [9:0]  buf_addr,
    input  wire [7:0]  buf_q,

    input  wire        front,
    output reg         swap_req,
    input  wire        swap_done,

    output reg         wr_valid,
    input  wire        wr_ready,
    output wire [1:0]  wr_bank,
    output reg  [10:0] wr_row,
    output reg  [7:0]  wr_col,
    output reg  [31:0] wr_data,
    output reg  [3:0]  wr_be,

    output reg         pal_we,
    output reg  [7:0]  pal_addr,
    output reg  [23:0] pal_data,

    output reg         reply_start,
    output reg  [7:0]  reply_type,
    output reg  [7:0]  reply_arg0,
    output reg  [7:0]  reply_arg1,
    input  wire        reply_busy,

    output reg         raster_start,
    output reg  [1:0]  raster_op,
    output wire [15:0] raster_value,
    input  wire        raster_done,
    input  wire        raster_bad_value,

    output reg         store_we,
    output reg  [7:0]  store_slot,
    output reg  [2:0]  store_byte,
    output reg  [7:0]  store_data,
    output wire        raster_from_store,
    output wire [7:0]  list_mode,
    output wire [23:0] list_slots,
    output wire [23:0] list_color,

    output reg         read_start,
    output wire [1:0]  read_bank,
    output wire [9:0]  read_x_start,
    output wire [9:0]  read_x_end,
    output wire [9:0]  read_y_start,
    output wire [9:0]  read_y_end,
    input  wire        read_done
);

    localparam T_HELLO = 8'h01, T_PING = 8'h02;
    localparam T_CLEAR = 8'h10, T_SPAN = 8'h11, T_RECT = 8'h12, T_PALETTE = 8'h13, T_SWAP = 8'h14;
    localparam T_TILE = 8'h15, T_RLE = 8'h16;
    localparam T_TRIANGLE = 8'h17, T_TEX_SPAN = 8'h18, T_CLEAR_DEPTH = 8'h19, T_DEPTH_RECT = 8'h1A;
    localparam T_READ_RECT = 8'h1B, T_VERTICES = 8'h1C, T_TRIANGLE_LIST = 8'h1D;
    localparam T_ACK = 8'h80, T_NACK = 8'h81;

    localparam STATUS_OK = 8'd0, STATUS_UNKNOWN = 8'd1, STATUS_BAD_LENGTH = 8'd2, STATUS_BAD_VALUE = 8'd3;
    localparam BANK_DEPTH = 2'd2, BANK_TEXTURE = 2'd3;
    localparam TWO_DEPTH_ROWS = WIDTH > 512;  // depth for a wide picture row takes two SDRAM rows
    localparam NACK_CRC = 8'd1, NACK_SEQ = 8'd2;

    localparam S_IDLE = 5'd0, S_ARG_WAIT = 5'd1, S_ARG_TAKE = 5'd2, S_START = 5'd3;
    localparam S_CLEAR = 5'd4, S_CLEAR_WAIT = 5'd5;
    localparam S_SPAN_WAIT = 5'd6, S_SPAN_TAKE = 5'd7, S_SPAN_WRITE = 5'd8;
    localparam S_RECT = 5'd9, S_RECT_WAIT = 5'd10;
    localparam S_PAL_WAIT = 5'd11, S_PAL_TAKE = 5'd12;
    localparam S_SWAP_WAIT = 5'd13;
    localparam S_REPLY = 5'd14, S_REPLY_WAIT = 5'd15, S_REPLY_OK = 5'd16;
    localparam S_TILE_WAIT = 5'd17, S_TILE_TAKE = 5'd18;
    localparam S_RUN_WAIT = 5'd19, S_RUN_TAKE = 5'd20, S_VALUE_WAIT = 5'd21, S_VALUE_TAKE = 5'd22;
    localparam S_PIXEL = 5'd23, S_PIXEL_WRITE = 5'd24, S_PIXEL_NEXT = 5'd25;
    localparam S_RASTER_WAIT = 5'd26, S_TEX_WAIT = 5'd27, S_TEX_TAKE = 5'd28, S_TEX_WRITE = 5'd29;
    localparam S_DEPTH_RESOLVE = 5'd30, S_DEPTH_RESOLVE_WAIT = 5'd31;
    localparam S_READ_START = 6'd32, S_READ_WAIT = 6'd33;
    localparam S_VERT_WAIT = 6'd34, S_VERT_TAKE = 6'd35, S_VERT_NEXT = 6'd39;
    localparam S_LIST_WAIT = 6'd36, S_LIST_TAKE = 6'd37, S_LIST_RASTER = 6'd38;

    reg [5:0]  state;
    reg [7:0]  expected;
    reg [7:0]  ack_status;

    reg [3:0]  arg_index, arg_count;
    reg [7:0]  arg [0:9];
    wire [15:0] arg_x = {arg[1], arg[0]};
    wire [15:0] arg_y = {arg[3], arg[2]};
    wire [15:0] arg_w = {arg[5], arg[4]};
    wire [15:0] arg_h = {arg[7], arg[6]};
    wire [16:0] rect_x_end = {1'b0, arg_x} + arg_w;
    wire [16:0] rect_y_end = {1'b0, arg_y} + arg_h;

    reg [16:0] cur_x, x_end;
    reg [16:0] cur_y, y_end;
    reg [10:0] pay_pos;
    reg [2:0]  rect_step;
    reg [8:0]  pal_index;
    reg [1:0]  pal_part;
    reg [7:0]  pal_r, pal_g;
    reg [7:0]  pixel;
    reg [7:0]  run_left;

    // TILE and RLE: an area filled left to right, row by row, with no clipping of the area itself.
    wire row_ends  = cur_x + 1'b1 == rect_x_end;
    wire area_full = row_ends && cur_y + 1'b1 == rect_y_end;

    // Palette payload: one start index, then whole red-green-blue triples.
    // The length is 1 more than a multiple of 3. 16 is 1 more than a multiple of 3 as well, so the remainders of
    // 4-bit pieces simply add up, which is far shallower logic than dividing the whole number.
    wire [1:0] length_part0 = pkt_len[3:0] % 4'd3;
    wire [1:0] length_part1 = pkt_len[7:4] % 4'd3;
    wire [1:0] length_part2 = {1'b0, pkt_len[10:8]} % 4'd3;
    wire [3:0] length_parts = length_part0 + length_part1 + length_part2;
    wire palette_length_ok = length_parts == 4'd1 || length_parts == 4'd4;

    wire [16:0] rect_next_x = cur_x + rect_step;

    // READ_RECT's last byte picks the buffer: 0 is the one on screen, 1 the hidden one.
    assign raster_value = {arg[1], arg[0]};

    // VERTICES and TRIANGLE_LIST: 2 bytes, then a whole number of 6-byte entries. Their count is the second byte.
    wire [10:0] list_length = 11'd2 + {1'b0, arg[1], 2'b00} + {2'b00, arg[1], 1'b0};
    wire [8:0]  vertex_end  = {1'b0, arg[0]} + arg[1];

    assign raster_from_store = pkt_type == T_TRIANGLE_LIST;
    assign list_mode  = arg[0];
    assign list_slots = {arg[4], arg[3], arg[2]};
    assign list_color = {arg[7], arg[6], arg[5]};

    assign read_bank    = arg[8][0] ? {1'b0, ~front} : {1'b0, front};
    assign read_x_start = cur_x[9:0];
    assign read_x_end   = x_end[9:0];
    assign read_y_start = cur_y[9:0];
    assign read_y_end   = y_end[9:0];

    reg [1:0] target;  // which memory a write goes to: 0 means the hidden picture buffer
    assign wr_bank = (target == 2'd0) ? {1'b0, ~front} : target;

    function [31:0] repeat_byte(input [7:0] value);
        repeat_byte = {value, value, value, value};
    endfunction

    function [3:0] byte_enable(input [1:0] lane);
        byte_enable = 4'b0001 << lane;
    endfunction

    function length_ok(input [7:0] kind, input [10:0] len);
        case (kind)
            T_CLEAR: length_ok = len == 11'd1;
            T_SPAN:  length_ok = len >= 11'd4;
            T_RECT:  length_ok = len == 11'd9;
            T_SWAP:  length_ok = len == 11'd0;
            T_TILE:  length_ok = len >= 11'd8;
            T_RLE:   length_ok = len >= 11'd8 && !len[0];
            T_TRIANGLE:    length_ok = len == 11'd37;
            T_TEX_SPAN:    length_ok = len >= 11'd3;
            T_CLEAR_DEPTH: length_ok = len == 11'd2;
            T_DEPTH_RECT:  length_ok = len == 11'd10;
            T_READ_RECT:   length_ok = len == 11'd9;
            T_VERTICES, T_TRIANGLE_LIST: length_ok = len >= 11'd2;
            default: length_ok = 1'b1;
        endcase
    endfunction

    function known_type(input [7:0] kind);
        known_type = kind == T_PING || kind == T_CLEAR || kind == T_SPAN || kind == T_RECT
                     || kind == T_PALETTE || kind == T_SWAP || kind == T_TILE || kind == T_RLE
                     || kind == T_TRIANGLE || kind == T_TEX_SPAN || kind == T_CLEAR_DEPTH
                     || kind == T_DEPTH_RECT || kind == T_READ_RECT
                     || kind == T_VERTICES || kind == T_TRIANGLE_LIST;
    endfunction

    function [3:0] args_for(input [7:0] kind);
        case (kind)
            T_CLEAR:   args_for = 4'd1;
            T_SPAN:    args_for = 4'd4;
            T_RECT:    args_for = 4'd9;
            T_PALETTE: args_for = 4'd1;
            T_TILE:    args_for = 4'd8;
            T_RLE:     args_for = 4'd8;
            T_TEX_SPAN:    args_for = 4'd3;
            T_CLEAR_DEPTH: args_for = 4'd2;
            T_DEPTH_RECT:  args_for = 4'd10;
            T_READ_RECT:   args_for = 4'd9;
            T_VERTICES, T_TRIANGLE_LIST: args_for = 4'd2;
            default:   args_for = 4'd0;
        endcase
    endfunction

    // Sends a reply and finishes the packet.
    task finish(input [7:0] kind, input [7:0] a0, input [7:0] a1);
        begin
            reply_type <= kind;
            reply_arg0 <= a0;
            reply_arg1 <= a1;
            state      <= S_REPLY;
        end
    endtask

    // One write of a filled rectangle: a whole word where the rectangle covers it, otherwise one pixel.
    task rect_write(input [16:0] x, input [16:0] y);
        begin
            cur_x    <= x;
            cur_y    <= y;
            wr_row   <= y[10:0];
            wr_valid <= 1'b1;
            if (target == BANK_DEPTH) begin
                if (TWO_DEPTH_ROWS) wr_row <= {y[9:0], x[9]};
                wr_col  <= x[8:1];
                wr_data <= {arg[9], arg[8], arg[9], arg[8]};
                if (!x[0] && x + 17'd2 <= x_end) begin
                    wr_be     <= 4'b1111;
                    rect_step <= 3'd2;
                end else begin
                    wr_be     <= x[0] ? 4'b1100 : 4'b0011;
                    rect_step <= 3'd1;
                end
            end else begin
                wr_col  <= x[9:2];
                wr_data <= repeat_byte(arg[8]);
                if (x[1:0] == 2'd0 && x + 17'd4 <= x_end) begin
                    wr_be     <= 4'b1111;
                    rect_step <= 3'd4;
                end else begin
                    wr_be     <= byte_enable(x[1:0]);
                    rect_step <= 3'd1;
                end
            end
        end
    endtask

    always @(posedge clk) begin
        pkt_ack     <= 1'b0;
        swap_req    <= 1'b0;
        pal_we      <= 1'b0;
        reply_start <= 1'b0;
        raster_start <= 1'b0;
        read_start  <= 1'b0;
        store_we    <= 1'b0;

        if (rst) begin
            state    <= S_IDLE;
            expected <= 8'd0;
            wr_valid <= 1'b0;
            target   <= 2'd0;
        end else case (state)
            S_IDLE: if (pkt_valid && !pkt_ack) begin
                ack_status <= STATUS_OK;
                target     <= 2'd0;
                if (!pkt_crc_ok) begin
                    finish(T_NACK, expected, NACK_CRC);
                end else if (pkt_type == T_HELLO) begin
                    expected <= pkt_seq + 1'b1;
                    finish(T_ACK, pkt_seq, STATUS_OK);
                end else if (pkt_seq == expected - 1'b1) begin
                    finish(T_ACK, pkt_seq, STATUS_OK);  // a repeat of one already done: do not redo it
                end else if (pkt_seq != expected) begin
                    finish(T_NACK, expected, NACK_SEQ);
                end else begin
                    expected <= expected + 1'b1;
                    if (!known_type(pkt_type)) begin
                        finish(T_ACK, pkt_seq, STATUS_UNKNOWN);
                    end else if (!length_ok(pkt_type, pkt_len)) begin
                        finish(T_ACK, pkt_seq, STATUS_BAD_LENGTH);
                    end else if (pkt_type == T_PALETTE && !palette_length_ok) begin
                        finish(T_ACK, pkt_seq, STATUS_BAD_LENGTH);
                    end else begin
                        arg_index <= 4'd0;
                        arg_count <= args_for(pkt_type);
                        buf_addr  <= 10'd0;
                        state     <= (args_for(pkt_type) == 0) ? S_START : S_ARG_WAIT;
                    end
                end
            end

            // The payload RAM has one clock of delay, so each byte takes two states.
            S_ARG_WAIT: state <= S_ARG_TAKE;
            S_ARG_TAKE: begin
                arg[arg_index] <= buf_q;
                arg_index      <= arg_index + 1'b1;
                buf_addr       <= buf_addr + 1'b1;
                state          <= (arg_index + 1'b1 == arg_count) ? S_START : S_ARG_WAIT;
            end

            S_START: case (pkt_type)
                T_CLEAR: begin
                    wr_row  <= 11'd0;
                    wr_col  <= 8'd0;
                    wr_data <= repeat_byte(arg[0]);
                    wr_be   <= 4'b1111;
                    state   <= S_CLEAR;
                end
                T_SPAN: begin
                    cur_x    <= {1'b0, arg_x};
                    cur_y    <= {1'b0, arg_y};
                    pay_pos  <= 11'd4;
                    buf_addr <= 10'd4;
                    state    <= (pkt_len == 11'd4) ? S_REPLY_OK : S_SPAN_WAIT;
                end
                T_READ_RECT: begin
                    cur_x <= {1'b0, arg_x};
                    cur_y <= {1'b0, arg_y};
                    x_end <= (rect_x_end > WIDTH) ? WIDTH : rect_x_end;
                    y_end <= (rect_y_end > HEIGHT) ? HEIGHT : rect_y_end;
                    if (arg[8] > 8'd1) begin
                        ack_status <= STATUS_BAD_VALUE;
                        state      <= S_REPLY_OK;
                    end else begin
                        state <= (arg_x >= WIDTH || arg_y >= HEIGHT || arg_w == 0 || arg_h == 0)
                                 ? S_REPLY_OK : S_READ_START;
                    end
                end
                T_RECT, T_DEPTH_RECT: begin
                    if (pkt_type == T_DEPTH_RECT) target <= BANK_DEPTH;
                    cur_x <= {1'b0, arg_x};
                    cur_y <= {1'b0, arg_y};
                    x_end <= (rect_x_end > WIDTH) ? WIDTH : rect_x_end;
                    y_end <= (rect_y_end > HEIGHT) ? HEIGHT : rect_y_end;
                    state <= (arg_x >= WIDTH || arg_y >= HEIGHT || arg_w == 0 || arg_h == 0)
                             ? S_REPLY_OK : (pkt_type == T_DEPTH_RECT) ? S_DEPTH_RESOLVE : S_RECT;
                end
                T_PALETTE: begin
                    pal_index <= {1'b0, arg[0]};
                    pal_part  <= 2'd0;
                    pay_pos   <= 11'd1;
                    buf_addr  <= 10'd1;
                    state     <= (pkt_len == 11'd1) ? S_REPLY_OK : S_PAL_WAIT;
                end
                T_SWAP: begin
                    swap_req <= 1'b1;
                    state    <= S_SWAP_WAIT;
                end
                T_TILE, T_RLE: begin
                    cur_x    <= {1'b0, arg_x};
                    cur_y    <= {1'b0, arg_y};
                    pay_pos  <= 11'd8;
                    buf_addr <= 10'd8;
                    if (arg_w == 0 || arg_h == 0 || pkt_len == 11'd8) state <= S_REPLY_OK;
                    else state <= (pkt_type == T_TILE) ? S_TILE_WAIT : S_RUN_WAIT;
                end
                T_TRIANGLE: begin
                    raster_op    <= 2'd0;
                    raster_start <= 1'b1;
                    state        <= S_RASTER_WAIT;
                end
                T_TEX_SPAN: begin
                    // Texture memory is 2048 rows of 256 bytes. Past the end of a row is skipped.
                    target   <= BANK_TEXTURE;
                    cur_x    <= {9'd0, arg[2]};
                    pay_pos  <= 11'd3;
                    buf_addr <= 10'd3;
                    state    <= (pkt_len == 11'd3 || {arg[1], arg[0]} >= 16'd2048) ? S_REPLY_OK : S_TEX_WAIT;
                end
                T_CLEAR_DEPTH: begin
                    raster_op    <= 2'd1;
                    raster_start <= 1'b1;
                    state        <= S_RASTER_WAIT;
                end
                T_VERTICES: begin
                    store_slot <= arg[0];
                    store_byte <= 3'd0;
                    pay_pos    <= 11'd2;
                    if (pkt_len != list_length) begin
                        ack_status <= STATUS_BAD_LENGTH;
                        state      <= S_REPLY_OK;
                    end else if (vertex_end > 9'd256) begin
                        ack_status <= STATUS_BAD_VALUE;
                        state      <= S_REPLY_OK;
                    end else begin
                        state <= (arg[1] == 8'd0) ? S_REPLY_OK : S_VERT_WAIT;
                    end
                end
                T_TRIANGLE_LIST: begin
                    arg_index <= 4'd2;
                    pay_pos   <= 11'd2;
                    if (pkt_len != list_length) begin
                        ack_status <= STATUS_BAD_LENGTH;
                        state      <= S_REPLY_OK;
                    end else begin
                        state <= (arg[1] == 8'd0) ? S_REPLY_OK : S_LIST_WAIT;
                    end
                end
                default: state <= S_REPLY_OK;  // PING
            endcase

            // The reply to the packet before this one may still be going out, and rows must not cut into it.
            S_READ_START: if (!reply_busy) begin
                read_start <= 1'b1;
                state      <= S_READ_WAIT;
            end
            S_READ_WAIT: if (read_done) state <= S_REPLY_OK;

            // DEPTH_RECT changes part of a tile, so tiles still marked as cleared must reach memory first.
            S_DEPTH_RESOLVE: begin
                raster_op    <= 2'd2;
                raster_start <= 1'b1;
                state        <= S_DEPTH_RESOLVE_WAIT;
            end
            S_DEPTH_RESOLVE_WAIT: if (raster_done) state <= S_RECT;

            S_VERT_WAIT: state <= S_VERT_TAKE;
            S_VERT_TAKE: begin
                store_we   <= 1'b1;
                store_data <= buf_q;
                pay_pos    <= pay_pos + 1'b1;
                buf_addr   <= buf_addr + 1'b1;
                state      <= (pay_pos + 1'b1 == pkt_len) ? S_REPLY_OK : S_VERT_NEXT;
            end
            S_VERT_NEXT: begin
                if (store_byte == 3'd5) begin
                    store_byte <= 3'd0;
                    store_slot <= store_slot + 1'b1;
                end else begin
                    store_byte <= store_byte + 1'b1;
                end
                state <= S_VERT_TAKE;
            end

            // Each record is 6 bytes. An invalid triangle is skipped, the rest are drawn, and the reply says so.
            S_LIST_WAIT: state <= S_LIST_TAKE;
            S_LIST_TAKE: begin
                arg[arg_index] <= buf_q;
                arg_index      <= arg_index + 1'b1;
                pay_pos        <= pay_pos + 1'b1;
                buf_addr       <= buf_addr + 1'b1;
                if (arg_index == 4'd7) begin
                    raster_op    <= 2'd0;
                    raster_start <= 1'b1;
                    state        <= S_LIST_RASTER;
                end else begin
                    state <= S_LIST_WAIT;
                end
            end
            S_LIST_RASTER: if (raster_done) begin
                if (raster_bad_value) ack_status <= STATUS_BAD_VALUE;
                arg_index <= 4'd2;
                state     <= (pay_pos == pkt_len) ? S_REPLY_OK : S_LIST_WAIT;
            end

            S_RASTER_WAIT: if (raster_done) begin
                ack_status <= raster_bad_value ? STATUS_BAD_VALUE : STATUS_OK;
                state      <= S_REPLY_OK;
            end

            S_TEX_WAIT: state <= S_TEX_TAKE;
            S_TEX_TAKE: begin
                wr_row   <= {arg[1][2:0], arg[0]};
                wr_col   <= {2'b00, cur_x[7:2]};
                wr_data  <= repeat_byte(buf_q);
                wr_be    <= byte_enable(cur_x[1:0]);
                wr_valid <= 1'b1;
                state    <= S_TEX_WRITE;
            end
            S_TEX_WRITE: if (wr_ready) begin
                wr_valid <= 1'b0;
                cur_x    <= cur_x + 1'b1;
                pay_pos  <= pay_pos + 1'b1;
                buf_addr <= buf_addr + 1'b1;
                state    <= (pay_pos + 1'b1 == pkt_len || cur_x[7:0] == 8'd255) ? S_REPLY_OK : S_TEX_WAIT;
            end

            S_CLEAR: begin
                wr_valid <= 1'b1;
                state    <= S_CLEAR_WAIT;
            end
            S_CLEAR_WAIT: if (wr_ready) begin
                if (wr_col == LINE_WORDS - 1) begin
                    wr_col <= 8'd0;
                    if (wr_row == HEIGHT - 1) begin
                        wr_valid <= 1'b0;
                        state    <= S_REPLY_OK;
                    end else begin
                        wr_row <= wr_row + 1'b1;
                    end
                end else begin
                    wr_col <= wr_col + 1'b1;
                end
            end

            S_SPAN_WAIT: state <= S_SPAN_TAKE;
            S_SPAN_TAKE: begin
                // Pixels off the picture are skipped; a span does not wrap to the next line.
                if (cur_x < WIDTH && cur_y < HEIGHT) begin
                    wr_row   <= cur_y[10:0];
                    wr_col   <= cur_x[9:2];
                    wr_data  <= repeat_byte(buf_q);
                    wr_be    <= byte_enable(cur_x[1:0]);
                    wr_valid <= 1'b1;
                    state    <= S_SPAN_WRITE;
                end else begin
                    cur_x    <= cur_x + 1'b1;
                    pay_pos  <= pay_pos + 1'b1;
                    buf_addr <= buf_addr + 1'b1;
                    state    <= (pay_pos + 1'b1 == pkt_len) ? S_REPLY_OK : S_SPAN_WAIT;
                end
            end
            S_SPAN_WRITE: if (wr_ready) begin
                wr_valid <= 1'b0;
                cur_x    <= cur_x + 1'b1;
                pay_pos  <= pay_pos + 1'b1;
                buf_addr <= buf_addr + 1'b1;
                state    <= (pay_pos + 1'b1 == pkt_len) ? S_REPLY_OK : S_SPAN_WAIT;
            end

            S_RECT: begin
                rect_write(cur_x, cur_y);
                state <= S_RECT_WAIT;
            end
            S_RECT_WAIT: if (wr_ready) begin
                if (rect_next_x < x_end) begin
                    rect_write(rect_next_x, cur_y);
                end else if (cur_y + 1'b1 == y_end) begin
                    wr_valid <= 1'b0;
                    state    <= S_REPLY_OK;
                end else begin
                    rect_write({1'b0, arg_x}, cur_y + 1'b1);
                end
            end

            // Palette entries past 255 are ignored.
            S_PAL_WAIT: state <= S_PAL_TAKE;
            S_PAL_TAKE: begin
                pay_pos  <= pay_pos + 1'b1;
                buf_addr <= buf_addr + 1'b1;
                pal_part <= (pal_part == 2'd2) ? 2'd0 : pal_part + 1'b1;
                if (pal_part == 2'd0) pal_r <= buf_q;
                if (pal_part == 2'd1) pal_g <= buf_q;
                if (pal_part == 2'd2) begin
                    pal_we    <= !pal_index[8];
                    pal_addr  <= pal_index[7:0];
                    pal_data  <= {pal_r, pal_g, buf_q};
                    pal_index <= pal_index[8] ? pal_index : pal_index + 1'b1;
                end
                state <= (pay_pos + 1'b1 == pkt_len) ? S_REPLY_OK : S_PAL_WAIT;
            end

            S_SWAP_WAIT: if (swap_done) state <= S_REPLY_OK;

            S_TILE_WAIT: state <= S_TILE_TAKE;
            S_TILE_TAKE: begin
                pixel    <= buf_q;
                run_left <= 8'd0;
                pay_pos  <= pay_pos + 1'b1;
                buf_addr <= buf_addr + 1'b1;
                state    <= S_PIXEL;
            end

            // A run is two bytes: its length minus one, then its colour.
            S_RUN_WAIT: state <= S_RUN_TAKE;
            S_RUN_TAKE: begin
                run_left <= buf_q;
                pay_pos  <= pay_pos + 1'b1;
                buf_addr <= buf_addr + 1'b1;
                state    <= S_VALUE_WAIT;
            end
            S_VALUE_WAIT: state <= S_VALUE_TAKE;
            S_VALUE_TAKE: begin
                pixel    <= buf_q;
                pay_pos  <= pay_pos + 1'b1;
                buf_addr <= buf_addr + 1'b1;
                state    <= S_PIXEL;
            end

            // Pixels off the picture are skipped, and still use up their place in the area.
            S_PIXEL: begin
                if (cur_x < WIDTH && cur_y < HEIGHT) begin
                    wr_row   <= cur_y[10:0];
                    wr_col   <= cur_x[9:2];
                    wr_data  <= repeat_byte(pixel);
                    wr_be    <= byte_enable(cur_x[1:0]);
                    wr_valid <= 1'b1;
                    state    <= S_PIXEL_WRITE;
                end else begin
                    state    <= S_PIXEL_NEXT;
                end
            end
            S_PIXEL_WRITE: if (wr_ready) begin
                wr_valid <= 1'b0;
                state    <= S_PIXEL_NEXT;
            end
            S_PIXEL_NEXT: begin
                if (row_ends) begin
                    cur_x <= {1'b0, arg_x};
                    cur_y <= cur_y + 1'b1;
                end else begin
                    cur_x <= cur_x + 1'b1;
                end
                if (area_full) begin
                    state <= S_REPLY_OK;
                end else if (run_left != 8'd0) begin
                    run_left <= run_left - 1'b1;
                    state    <= S_PIXEL;
                end else if (pay_pos == pkt_len) begin
                    state <= S_REPLY_OK;
                end else begin
                    state <= (pkt_type == T_TILE) ? S_TILE_WAIT : S_RUN_WAIT;
                end
            end

            S_REPLY_OK: finish(T_ACK, pkt_seq, ack_status);

            S_REPLY: if (!reply_busy) begin
                reply_start <= 1'b1;
                pkt_ack     <= 1'b1;
                state       <= S_REPLY_WAIT;
            end

            // One clock for reply_tx to go busy and the parser to drop pkt_valid.
            S_REPLY_WAIT: state <= S_IDLE;

            default: state <= S_IDLE;
        endcase
    end

endmodule
