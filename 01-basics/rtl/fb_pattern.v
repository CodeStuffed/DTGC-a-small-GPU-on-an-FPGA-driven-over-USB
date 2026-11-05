// Test picture generator: draws an animated pattern into the hidden buffer, asks for a swap, waits
// for it, then draws the next frame. It proves the whole memory path with no PC connected.
// Pixel value: (x XOR y) + frame, all 8 bits, stored 4 pixels to a word with pixel 0 in the low byte.
`timescale 1ns / 1ps

module fb_pattern #(
    parameter LINE_WORDS = 85,
    parameter HEIGHT = 340
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        mem_ready,
    input  wire        front,       // buffer on screen; we draw into the other one
    output reg         swap_req,
    input  wire        swap_done,

    output wire        wr_valid,
    input  wire        wr_ready,
    output wire [1:0]  wr_bank,
    output wire [10:0] wr_row,
    output wire [7:0]  wr_col,
    output wire [31:0] wr_data
);

    reg [7:0] col;
    reg [8:0] row;
    reg [7:0] frame;
    reg       drawing;
    reg       started;   // the first frame starts on its own; after that each swap starts the next

    assign wr_valid = drawing;
    assign wr_bank  = {1'b0, ~front};
    assign wr_row   = {2'b00, row};
    assign wr_col   = col;

    wire [7:0] x0 = {col[5:0], 2'b00};
    wire [7:0] y0 = row[7:0];
    wire [7:0] p0 = (x0 ^ y0) + frame;
    wire [7:0] p1 = ((x0 | 8'd1) ^ y0) + frame;
    wire [7:0] p2 = ((x0 | 8'd2) ^ y0) + frame;
    wire [7:0] p3 = ((x0 | 8'd3) ^ y0) + frame;
    assign wr_data = {p3, p2, p1, p0};

    always @(posedge clk) begin
        swap_req <= 1'b0;
        if (rst) begin
            col     <= 8'd0;
            row     <= 9'd0;
            frame   <= 8'd0;
            drawing <= 1'b0;
            started <= 1'b0;
        end else if (drawing) begin
            if (wr_ready) begin
                if (col == LINE_WORDS - 1) begin
                    col <= 8'd0;
                    if (row == HEIGHT - 1) begin
                        row      <= 9'd0;
                        drawing  <= 1'b0;
                        swap_req <= 1'b1;
                    end else begin
                        row <= row + 1'b1;
                    end
                end else begin
                    col <= col + 1'b1;
                end
            end
        end else if (swap_done) begin
            frame   <= frame + 1'b1;
            drawing <= 1'b1;
        end else if (mem_ready && !started) begin
            drawing <= 1'b1;
            started <= 1'b1;
        end
    end

endmodule
