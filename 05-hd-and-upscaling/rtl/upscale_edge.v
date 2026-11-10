// DT-Upscale edge-directed blend, for any whole scale from 2 to 12. Bit-exact with "edge" in sw/dtgc/upscale.py.
// Each square of 4 pixels is split into 2 triangles along whichever diagonal has the smaller change in brightness, and an
// output pixel blends the 3 corners of its triangle. Blending along an edge instead of across it keeps diagonals smooth.
//
// Positions come in as phases: how far across (phase_x) and down (phase_y) the square the output pixel sits, in units of
// 1 / (2 * SCALE). So each corner's weight is a whole number from 0 to 2 * SCALE, and the 4 weights sum to 2 * SCALE.
// The sum is divided by 2 * SCALE with a multiply by a rounded-up reciprocal and a shift, which is exact for every sum
// this blend can make up to SCALE 12 (checked for each scale in sw/tests/test_upscale.py).
// 8 clocks from inputs to output, as upscale_filter.v, so the two can swap without moving anything else.
// Pixels are {red, green, blue}.
`timescale 1ns / 1ps

module upscale_edge #(
    parameter SCALE = 2
) (
    input  wire        clk,
    input  wire [4:0]  phase_x,
    input  wire [4:0]  phase_y,
    input  wire [23:0] top_left,
    input  wire [23:0] top_right,
    input  wire [23:0] bottom_left,
    input  wire [23:0] bottom_right,
    output wire [23:0] out
);

    localparam [4:0] UNIT = 2 * SCALE;

    // A cheap brightness: (r + 2g + b) / 4, which needs only adders.
    function [7:0] luma(input [23:0] pixel);
        reg [9:0] sum;
        begin
            sum = pixel[23:16] + {pixel[15:8], 1'b0} + pixel[7:0];
            luma = sum[9:2];
        end
    endfunction

    function [7:0] gap(input [7:0] x, input [7:0] y);
        gap = (x > y) ? x - y : y - x;
    endfunction

    // The weights of the corners a (top left), b (top right), c (bottom left) and d (bottom right), 5 bits each.
    // These are the same 4 triangles as _edge() in upscale.py, written as one weight per corner.
    function [19:0] weights(input main_diagonal, input [4:0] u, input [4:0] v);
        reg [5:0] u_plus_v;
        begin
            u_plus_v = u + v;
            if (main_diagonal) begin
                if (u >= v) weights = {UNIT - u, u - v, 5'd0, v};          // a, b, d
                else        weights = {UNIT - v, 5'd0, v - u, u};          // a, c, d
            end else begin
                if (u_plus_v <= UNIT) weights = {UNIT - u - v, u, v, 5'd0};  // a, b, c
                else weights = {5'd0, UNIT - v, UNIT - u, u_plus_v[4:0] - UNIT};  // b, c, d
            end
        end
    endfunction

    // 1: brightness of the corners
    reg [7:0]  luma_a, luma_b, luma_c, luma_d;
    // 2: the change along each diagonal
    reg [7:0]  main_gap, other_gap;
    // 3: which triangle, as weights
    reg [19:0] picked;
    // The corners and the position travel along with the data.
    reg [23:0] a1, b1, c1, d1, a2, b2, c2, d2, a3, b3, c3, d3;
    reg [4:0]  u1, v1, u2, v2;

    always @(posedge clk) begin
        luma_a <= luma(top_left);
        luma_b <= luma(top_right);
        luma_c <= luma(bottom_left);
        luma_d <= luma(bottom_right);
        a1 <= top_left;
        b1 <= top_right;
        c1 <= bottom_left;
        d1 <= bottom_right;
        u1 <= phase_x;
        v1 <= phase_y;

        main_gap  <= gap(luma_a, luma_d);
        other_gap <= gap(luma_b, luma_c);
        a2 <= a1;
        b2 <= b1;
        c2 <= c1;
        d2 <= d1;
        u2 <= u1;
        v2 <= v1;

        picked <= weights(main_gap <= other_gap, u2, v2);
        a3 <= a2;
        b3 <= b2;
        c3 <= c2;
        d3 <= d2;
    end

    upscale_edge_channel #(.SCALE(SCALE)) red (
        .clk(clk), .picked(picked), .a(a3[23:16]), .b(b3[23:16]), .c(c3[23:16]), .d(d3[23:16]), .out(out[23:16])
    );
    upscale_edge_channel #(.SCALE(SCALE)) green (
        .clk(clk), .picked(picked), .a(a3[15:8]), .b(b3[15:8]), .c(c3[15:8]), .d(d3[15:8]), .out(out[15:8])
    );
    upscale_edge_channel #(.SCALE(SCALE)) blue (
        .clk(clk), .picked(picked), .a(a3[7:0]), .b(b3[7:0]), .c(c3[7:0]), .d(d3[7:0]), .out(out[7:0])
    );

endmodule

// The weighted sum for one colour channel, divided by 2 * SCALE with rounding. Output comes 5 clocks after the inputs.
module upscale_edge_channel #(
    parameter SCALE = 2
) (
    input  wire        clk,
    input  wire [19:0] picked,
    input  wire [7:0]  a,
    input  wire [7:0]  b,
    input  wire [7:0]  c,
    input  wire [7:0]  d,
    output reg  [7:0]  out
);

    localparam UNIT = 2 * SCALE;
    localparam SHIFT = 16;
    localparam [16:0] RECIPROCAL = ((1 << SHIFT) + UNIT - 1) / UNIT;   // rounded up

    // 1: each corner times its weight (8 x 5 bits, small enough for logic)
    reg [12:0] part_a, part_b, part_c, part_d;
    // 2: pairs added
    reg [13:0] sum_ab, sum_cd;
    // 3: all of it, plus half of 2 * SCALE so the division rounds
    reg [13:0] total;
    // 4: times the reciprocal
    reg [30:0] product;

    always @(posedge clk) begin
        part_a <= a * picked[19:15];
        part_b <= b * picked[14:10];
        part_c <= c * picked[9:5];
        part_d <= d * picked[4:0];

        sum_ab <= part_a + part_b;
        sum_cd <= part_c + part_d;

        total <= sum_ab + sum_cd + SCALE;

        product <= total * RECIPROCAL;
        out <= product[SHIFT+7:SHIFT];
    end

endmodule
