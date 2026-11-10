// DT-Upscale bilinear blend for one colour channel, for a scale of 2 or 3. Bit-exact with "bilinear" in
// sw/dtgc/upscale.py: blend across on both rows, then down, keeping all the bits until the final rounding.
// The weights are few and fixed, so shifts and adds do the multiplying, with no DSP block.
// Weight codes: scale 2 uses 1 = 64 and 3 = 192. Scale 3 uses 0 = 0, 1 = 85 and 2 = 170.
// Result comes out LATENCY clocks after its inputs.
`timescale 1ns / 1ps

module upscale_filter #(
    parameter SCALE = 2
) (
    input  wire       clk,
    input  wire [1:0] weight_x,
    input  wire [1:0] weight_y,
    input  wire [7:0] top_left,
    input  wire [7:0] top_right,
    input  wire [7:0] bottom_left,
    input  wire [7:0] bottom_right,
    output reg  [7:0] out
);

    // First half of a multiply: 3x for scale 2, 5x for scale 3. Second half: shift to the final weight.
    function signed [19:0] first_step(input signed [17:0] x);
        first_step = (SCALE == 2) ? x + (x <<< 1) : x + (x <<< 2);
    endfunction

    function signed [27:0] second_step(input signed [19:0] stepped, input signed [17:0] x, input [1:0] weight);
        reg signed [27:0] wide_step;
        reg signed [27:0] wide_x;
        begin
            wide_step = stepped;
            wide_x = x;
            if (SCALE == 2)
                second_step = (weight == 2'd3) ? wide_step <<< 6 : wide_x <<< 6;   // 192x, or 64x
            else if (weight == 2'd0)
                second_step = 28'sd0;
            else if (weight == 2'd1)
                second_step = wide_step + (wide_step <<< 4);                       // 85x
            else
                second_step = (wide_step + (wide_step <<< 4)) <<< 1;               // 170x
        end
    endfunction

    // Weights and the left-hand pixels travel along with the data.
    reg [1:0] wx1, wx2, wy1, wy2, wy3, wy4, wy5, wy6;
    reg [7:0] tl1, tl2, tl3, bl1, bl2, bl3;

    // 1: differences across each row
    reg signed [8:0] top_gap1, bottom_gap1;
    // 2, 3: multiply them by the across weight
    reg signed [8:0]  top_gap2, bottom_gap2;
    reg signed [19:0] top_step2, bottom_step2;
    reg signed [27:0] top_part3, bottom_part3;
    // 4: blended rows, in 1/256ths
    reg signed [17:0] top4, bottom4;
    // 5: difference between the rows
    reg signed [17:0] top5, gap5;
    // 6, 7: multiply it by the down weight
    reg signed [17:0] top6, gap6, top7;
    reg signed [19:0] step6;
    reg signed [27:0] part7;
    // 8: the final blend and rounding, then one more register for the output's own place

    wire signed [27:0] total = (top7 <<< 8) + part7 + 28'sd32768;

    always @(posedge clk) begin
        wx1 <= weight_x;
        wx2 <= wx1;
        wy1 <= weight_y;
        wy2 <= wy1;
        wy3 <= wy2;
        wy4 <= wy3;
        wy5 <= wy4;
        wy6 <= wy5;
        tl1 <= top_left;
        tl2 <= tl1;
        tl3 <= tl2;
        bl1 <= bottom_left;
        bl2 <= bl1;
        bl3 <= bl2;

        top_gap1    <= {1'b0, top_right} - {1'b0, top_left};
        bottom_gap1 <= {1'b0, bottom_right} - {1'b0, bottom_left};

        top_gap2     <= top_gap1;
        bottom_gap2  <= bottom_gap1;
        top_step2    <= first_step(top_gap1);
        bottom_step2 <= first_step(bottom_gap1);

        top_part3    <= second_step(top_step2, top_gap2, wx2);
        bottom_part3 <= second_step(bottom_step2, bottom_gap2, wx2);

        top4    <= $signed({2'b00, tl3, 8'd0}) + top_part3[17:0];
        bottom4 <= $signed({2'b00, bl3, 8'd0}) + bottom_part3[17:0];

        top5 <= top4;
        gap5 <= bottom4 - top4;

        top6  <= top5;
        gap6  <= gap5;
        step6 <= first_step(gap5);

        top7  <= top6;
        part7 <= second_step(step6, gap6, wy6);

        out <= total[23:16];
    end

endmodule
