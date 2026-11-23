// De-dither: smooths the GPU's dither pattern out of one pixel without blurring real edges.
// Bit-exact with dedither() in sw/dtgc/upscale.py.
//
// The GPU stores 8-bit colour, so a colour it cannot store is drawn as a fine pattern of two that it can. This takes a
// pixel and its 8 neighbours and gives their weighted average, with weights 1 2 1 / 2 4 2 / 1 2 1 (sum 16).
// A neighbour only counts if red, green and blue are all within one palette step of the pixel's own, which is as far
// apart as two colours of one dither pattern can be. Any other neighbour is across a real edge, and the pixel's own
// colour is used in its place, so the weights always sum to 16 and the division is a shift.
// Pixels are {red, green, blue}. 3 clocks from inputs to output.
`timescale 1ns / 1ps

module dedither #(
    parameter CLOSE_RG = 37,           // one step of the default palette: 255 / 7 rounded up
    parameter CLOSE_B = 85             // and 255 / 3
) (
    input  wire        clk,
    input  wire [23:0] up_left,
    input  wire [23:0] up,
    input  wire [23:0] up_right,
    input  wire [23:0] left,
    input  wire [23:0] centre,
    input  wire [23:0] right,
    input  wire [23:0] down_left,
    input  wire [23:0] down,
    input  wire [23:0] down_right,
    output reg  [23:0] out
);

    function [7:0] gap(input [7:0] x, input [7:0] y);
        gap = (x > y) ? x - y : y - x;
    endfunction

    // The neighbour if it is close to the pixel, else the pixel itself.
    function [23:0] counted(input [23:0] near, input [23:0] own);
        counted = (gap(near[23:16], own[23:16]) <= CLOSE_RG && gap(near[15:8], own[15:8]) <= CLOSE_RG &&
                   gap(near[7:0], own[7:0]) <= CLOSE_B) ? near : own;
    endfunction

    // 1: each neighbour, or the pixel in its place
    reg [23:0] corner_a, corner_b, corner_c, corner_d, side_a, side_b, side_c, side_d, middle;
    // 2: the 4 corners added, the 4 sides added, per colour
    reg [9:0]  corners_r, corners_g, corners_b, sides_r, sides_g, sides_b;
    reg [23:0] middle_2;
    // 3: corners + 2 * sides + 4 * middle + 8, at most 16 * 255 + 8, then the top 8 of 12 bits
    wire [11:0] total_r = corners_r + {sides_r, 1'b0} + {middle_2[23:16], 2'b00} + 4'd8;
    wire [11:0] total_g = corners_g + {sides_g, 1'b0} + {middle_2[15:8], 2'b00} + 4'd8;
    wire [11:0] total_b = corners_b + {sides_b, 1'b0} + {middle_2[7:0], 2'b00} + 4'd8;

    always @(posedge clk) begin
        corner_a <= counted(up_left, centre);
        corner_b <= counted(up_right, centre);
        corner_c <= counted(down_left, centre);
        corner_d <= counted(down_right, centre);
        side_a   <= counted(up, centre);
        side_b   <= counted(left, centre);
        side_c   <= counted(right, centre);
        side_d   <= counted(down, centre);
        middle   <= centre;

        corners_r <= corner_a[23:16] + corner_b[23:16] + corner_c[23:16] + corner_d[23:16];
        corners_g <= corner_a[15:8] + corner_b[15:8] + corner_c[15:8] + corner_d[15:8];
        corners_b <= corner_a[7:0] + corner_b[7:0] + corner_c[7:0] + corner_d[7:0];
        sides_r   <= side_a[23:16] + side_b[23:16] + side_c[23:16] + side_d[23:16];
        sides_g   <= side_a[15:8] + side_b[15:8] + side_c[15:8] + side_d[15:8];
        sides_b   <= side_a[7:0] + side_b[7:0] + side_c[7:0] + side_d[7:0];
        middle_2  <= middle;

        out <= {total_r[11:4], total_g[11:4], total_b[11:4]};
    end

endmodule
