// Sends part of a picture back to the PC, one DATA packet per row: two bytes of row number, then its pixels.
// This is what makes the USB-output version possible, and it also lets the PC check a picture with no monitor.
// Reads up to 8 words at a time, sends them, and reads more. Behaviour must stay the same as sw/dtgc/emulator.py.
`timescale 1ns / 1ps

module frame_reader (
    input  wire        clk,
    input  wire        rst,

    input  wire        start,       // pulse, only while busy is low. The area must not be empty.
    input  wire [7:0]  seq,
    input  wire [1:0]  bank,
    input  wire [9:0]  x_start,
    input  wire [9:0]  x_end,       // one past the last pixel
    input  wire [9:0]  y_start,
    input  wire [9:0]  y_end,       // one past the last row
    output wire        busy,
    output reg         done,        // pulse: everything has been sent

    output reg         rr_valid,
    input  wire        rr_ready,
    output wire [1:0]  rr_bank,
    output wire [10:0] rr_row,
    output wire [7:0]  rr_col,
    output wire [3:0]  rr_len,
    input  wire        rr_done,
    input  wire [31:0] rr_data,

    output wire        tx_valid,
    output reg  [7:0]  tx_data,
    input  wire        tx_ready
);

    `include "rtl/crc.vh"

    localparam T_DATA = 8'h82;
    localparam S_IDLE = 3'd0, S_HEADER = 3'd1, S_FETCH = 3'd2, S_WAIT = 3'd3, S_PIXEL = 3'd4, S_CRC_LOW = 3'd5, S_CRC_HIGH = 3'd6;

    reg [2:0]  state;
    reg [3:0]  index;        // which byte of the part before the pixels
    reg [7:0]  seq_reg;
    reg [1:0]  bank_reg;
    reg [9:0]  x_first, x_stop, y_stop;
    reg [9:0]  cur_x, cur_y;
    reg [7:0]  header_crc;
    reg [15:0] body_crc;

    // The words just read, placed by the low bits of their column, so 8 in a row can never collide.
    reg [31:0] words [0:7];
    reg [3:0]  words_left;
    reg [7:0]  store_col;

    wire [10:0] length = {1'b0, x_stop} - {1'b0, x_first} + 11'd2;
    wire [7:0]  col_now = cur_x[9:2];
    wire [8:0]  col_stop = {1'b0, x_stop[9:2]} + (x_stop[1:0] != 2'd0);   // one past the last column needed
    wire [8:0]  cols_to_end = col_stop - {1'b0, col_now};
    assign rr_len = (cols_to_end > 9'd8) ? 4'd8 : cols_to_end[3:0];
    assign rr_bank = bank_reg;
    assign rr_row = {1'b0, cur_y};
    assign rr_col = col_now;

    wire [31:0] word_now = words[cur_x[4:2]];
    wire        last_pixel = cur_x + 1'b1 == x_stop;
    // The next pixel is in a word not yet read when the column changes and the burst has run out.
    reg  [8:0]  fetched_end;
    wire        out_of_words = {1'b0, cur_x[9:2]} + 1'b1 == fetched_end && cur_x[1:0] == 2'd3;

    assign busy = state != S_IDLE;
    assign tx_valid = state == S_HEADER || state == S_PIXEL || state == S_CRC_LOW || state == S_CRC_HIGH;

    always @* begin
        tx_data = 8'h00;
        case (state)
            S_HEADER: case (index)
                4'd0:    tx_data = 8'hD7;
                4'd1:    tx_data = 8'd1;
                4'd2:    tx_data = T_DATA;
                4'd3:    tx_data = seq_reg;
                4'd4:    tx_data = length[7:0];
                4'd5:    tx_data = {5'd0, length[10:8]};
                4'd6:    tx_data = header_crc;
                4'd7:    tx_data = cur_y[7:0];
                default: tx_data = {6'd0, cur_y[9:8]};
            endcase
            S_PIXEL: case (cur_x[1:0])
                2'd0:    tx_data = word_now[7:0];
                2'd1:    tx_data = word_now[15:8];
                2'd2:    tx_data = word_now[23:16];
                default: tx_data = word_now[31:24];
            endcase
            S_CRC_LOW:  tx_data = body_crc[7:0];
            S_CRC_HIGH: tx_data = body_crc[15:8];
            default:    tx_data = 8'h00;
        endcase
    end

    always @(posedge clk) begin
        done <= 1'b0;
        if (rr_done) begin
            words[store_col[2:0]] <= rr_data;
            store_col  <= store_col + 1'b1;
            words_left <= words_left - 1'b1;
        end

        if (rst) begin
            state    <= S_IDLE;
            rr_valid <= 1'b0;
        end else case (state)
            S_IDLE: if (start) begin
                seq_reg    <= seq;
                bank_reg   <= bank;
                x_first    <= x_start;
                x_stop     <= x_end;
                y_stop     <= y_end;
                cur_x      <= x_start;
                cur_y      <= y_start;
                index      <= 4'd0;
                header_crc <= 8'h00;
                body_crc   <= 16'hFFFF;
                state      <= S_HEADER;
            end

            S_HEADER: if (tx_ready) begin
                index <= index + 1'b1;
                if (index >= 4'd1 && index <= 4'd5) header_crc <= crc8_next(header_crc, tx_data);
                if (index >= 4'd1) body_crc <= crc16_next(body_crc, tx_data);
                if (index == 4'd8) state <= S_FETCH;
            end

            S_FETCH: begin
                rr_valid    <= 1'b1;
                store_col   <= col_now;
                words_left  <= rr_len;
                fetched_end <= {1'b0, col_now} + rr_len;
                state       <= S_WAIT;
            end

            S_WAIT: begin
                if (rr_valid && rr_ready) rr_valid <= 1'b0;
                if (rr_done && words_left == 4'd1) state <= S_PIXEL;
            end

            S_PIXEL: if (tx_ready) begin
                body_crc <= crc16_next(body_crc, tx_data);
                cur_x    <= cur_x + 1'b1;
                if (last_pixel) state <= S_CRC_LOW;
                else if (out_of_words) state <= S_FETCH;
            end

            S_CRC_LOW: if (tx_ready) state <= S_CRC_HIGH;

            S_CRC_HIGH: if (tx_ready) begin
                if (cur_y + 1'b1 == y_stop) begin
                    done  <= 1'b1;
                    state <= S_IDLE;
                end else begin
                    cur_y      <= cur_y + 1'b1;
                    cur_x      <= x_first;
                    index      <= 4'd0;
                    header_crc <= 8'h00;
                    body_crc   <= 16'hFFFF;
                    state      <= S_HEADER;
                end
            end

            default: state <= S_IDLE;
        endcase
    end

endmodule
