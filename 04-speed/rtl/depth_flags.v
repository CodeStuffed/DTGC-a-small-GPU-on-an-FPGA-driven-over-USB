// One word per picture row, with one bit per depth tile in that row. A set bit means "this tile holds the clear value",
// whatever the SDRAM says, which is what lets a depth clear take one clock per row instead of a write for every word.
// Block RAM, with a read and a write on each clock. A read takes one clock.
`timescale 1ns / 1ps

module depth_flags #(
    parameter TILES = 22,
    parameter ROWS = 512
) (
    input  wire             clk,
    input  wire [9:0]       read_row,
    output reg  [TILES-1:0] read_flags,
    input  wire             write,
    input  wire [9:0]       write_row,
    input  wire [TILES-1:0] write_flags
);

    reg [TILES-1:0] rows [0:ROWS-1];

    always @(posedge clk) begin
        if (write) rows[write_row] <= write_flags;
        read_flags <= rows[read_row];
    end

endmodule
