// Pipelined fixed-point shader: one pixel in and one pixel out per clock, 5 clocks later. Bit-exact with sw/dtgc/shade.py.
//
//   light = ambient + max(0, normal . light_dir) + noise, limited to 0 .. 1
//   lit   = base colour x light
//   out   = dst + (lit - dst) x alpha
//
// Number formats. Q4.12 means 4 whole bits and 12 fraction bits, so 4096 is 1.0. Q8.8 works the same way, so 256 is 1.0.
//   normal and light_dir: signed Q4.12. ambient: Q8.8. alpha: 0 to 256, where 256 is fully opaque.
//   noise_amount: 0 to 255, in 1/256ths of the +-128 noise. Colours are plain 8 bits.
//
// The noise is a hash of the pixel position, with no state, so a pixel always gets the same value.
// The multiplications are plain Verilog: Yosys chooses the DSP blocks, and no vendor primitive is needed.
//
// This module is not yet connected to gpu_core.v. The picture there is 8 bits per pixel through a palette, and reading the
// destination for blending would cost a memory read per pixel. See docs/architecture-1080p30.md.
`timescale 1ns / 1ps

module shade_pipe (
    input  wire               clk,
    input  wire               in_valid,
    input  wire signed [15:0] normal_x,
    input  wire signed [15:0] normal_y,
    input  wire signed [15:0] normal_z,
    input  wire signed [15:0] light_x,
    input  wire signed [15:0] light_y,
    input  wire signed [15:0] light_z,
    input  wire        [8:0]  ambient,
    input  wire        [7:0]  noise_amount,
    input  wire        [7:0]  pixel_x,
    input  wire        [7:0]  pixel_y,
    input  wire        [23:0] base,
    input  wire        [23:0] dst,
    input  wire        [8:0]  alpha,
    output reg                out_valid,
    output reg         [23:0] out
);

    // 16-bit xorshift of the position
    wire [15:0] hash0 = {pixel_x, pixel_y};
    wire [15:0] hash1 = hash0 ^ (hash0 << 7);
    wire [15:0] hash2 = hash1 ^ (hash1 >> 9);
    wire [15:0] hash3 = hash2 ^ (hash2 << 8);

    // What travels along with the data.
    reg  [4:1]  valid;
    reg  [8:0]  ambient1, ambient2;
    reg  [23:0] base1, base2, base3, dst1, dst2, dst3, lit4, dst4;
    reg  [8:0]  alpha1, alpha2, alpha3, alpha4;
    reg  [7:0]  amount1;

    // 1: each part of the dot product, and the noise
    reg signed [31:0] part_x, part_y, part_z;
    reg signed [8:0]  noise1;
    // 2: the dot product, in Q8.24, and the scaled noise
    reg signed [33:0] dot2;
    reg signed [17:0] noise2;
    // 3: the light, in Q8.8
    wire signed [17:0] diffuse = dot2[33] ? 18'sd0 : dot2[33:16];
    wire signed [19:0] light_sum = $signed({11'd0, ambient2}) + diffuse + (noise2 >>> 8);
    reg  [8:0]  light3;

    // Rounded base x light, which is never over 255: 255 x 256 + 128 keeps the top byte at 255.
    function [7:0] lit_channel(input [7:0] colour, input [8:0] light);
        reg [16:0] product;
        begin
            product = colour * light + 17'd128;
            lit_channel = product[15:8];
        end
    endfunction

    // Rounded dst + (src - dst) x alpha, which stays between src and dst.
    function [7:0] blend_channel(input [7:0] src, input [7:0] old, input [8:0] amount);
        reg signed [9:0]  difference;
        reg signed [19:0] product;
        reg signed [19:0] moved;
        reg signed [19:0] result;
        begin
            difference = {2'b00, src} - {2'b00, old};
            product = difference * $signed({1'b0, amount}) + 20'sd128;
            moved = product >>> 8;
            result = moved + $signed({12'd0, old});
            blend_channel = result[7:0];
        end
    endfunction

    always @(posedge clk) begin
        valid <= {valid[3:1], in_valid};
        ambient1 <= ambient;
        ambient2 <= ambient1;
        base1 <= base;
        base2 <= base1;
        base3 <= base2;
        dst1 <= dst;
        dst2 <= dst1;
        dst3 <= dst2;
        dst4 <= dst3;
        alpha1 <= alpha;
        alpha2 <= alpha1;
        alpha3 <= alpha2;
        alpha4 <= alpha3;
        amount1 <= noise_amount;

        part_x <= normal_x * light_x;
        part_y <= normal_y * light_y;
        part_z <= normal_z * light_z;
        noise1 <= $signed({1'b0, hash3[15:8]}) - 9'sd128;

        dot2   <= part_x + part_y + part_z;
        noise2 <= noise1 * $signed({1'b0, amount1});

        light3 <= light_sum < 0 ? 9'd0 : light_sum > 20'sd256 ? 9'd256 : light_sum[8:0];

        lit4 <= {lit_channel(base3[23:16], light3), lit_channel(base3[15:8], light3), lit_channel(base3[7:0], light3)};

        out_valid <= valid[4];
        out <= {blend_channel(lit4[23:16], dst4[23:16], alpha4), blend_channel(lit4[15:8], dst4[15:8], alpha4),
                blend_channel(lit4[7:0], dst4[7:0], alpha4)};
    end

endmodule
