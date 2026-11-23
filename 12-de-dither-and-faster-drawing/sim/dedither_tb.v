// Checks rtl/dedither.v against its rule on random 3 x 3 windows, written here as a loop over the 9 pixels and not as the
// module's adders. Most neighbours are the pixel plus a change of up to about one palette step per colour, landing on both
// sides of the limits (37 for red and green, 85 for blue) and exactly on them. The whole-GPU comparison is in
// sw/tests/test_upscale_rtl.py.
`timescale 1ns / 1ps

module dedither_tb;
    localparam LATENCY = 3, COUNT = 200000;

    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg  [23:0] window [0:8];          // row by row, so 4 is the pixel itself
    wire [23:0] out;

    dedither dut (
        .clk(clk), .up_left(window[0]), .up(window[1]), .up_right(window[2]), .left(window[3]), .centre(window[4]),
        .right(window[5]), .down_left(window[6]), .down(window[7]), .down_right(window[8]), .out(out)
    );

    function integer distance(input integer x, input integer y);
        distance = (x > y) ? x - y : y - x;
    endfunction

    function integer channel(input [23:0] pixel, input integer which);
        channel = (which == 0) ? pixel[23:16] : (which == 1) ? pixel[15:8] : pixel[7:0];
    endfunction

    function integer weight(input integer index);
        weight = (index == 4) ? 4 : (index % 2) ? 2 : 1;
    endfunction

    function [23:0] wanted(input integer unused);
        integer n, ch, total [0:2];
        reg counts;
        begin
            for (ch = 0; ch < 3; ch = ch + 1) total[ch] = 8;
            for (n = 0; n < 9; n = n + 1) begin
                counts = distance(channel(window[n], 0), channel(window[4], 0)) <= 37 &&
                         distance(channel(window[n], 1), channel(window[4], 1)) <= 37 &&
                         distance(channel(window[n], 2), channel(window[4], 2)) <= 85;
                for (ch = 0; ch < 3; ch = ch + 1)
                    total[ch] = total[ch] + weight(n) * channel(counts ? window[n] : window[4], ch);
            end
            wanted = {total[0][11:4], total[1][11:4], total[2][11:4]};
        end
    endfunction

    // One colour of the pixel moved by up to limit + 2 either way, often by exactly the limit or one more, kept in range.
    function [7:0] moved(input [7:0] value, input integer limit);
        integer pick, change, result;
        begin
            pick = {$random} % 8;
            change = (pick == 0) ? limit : (pick == 1) ? limit + 1 : {$random} % (limit + 3);
            result = ({$random} % 2) ? value + change : value - change;
            moved = (result < 0) ? 0 : (result > 255) ? 255 : result;
        end
    endfunction

    reg [23:0] history [0:LATENCY];
    reg [23:0] own;
    integer i, h, n, errors = 0, smoothed = 0;

    initial begin
        for (n = 0; n < 9; n = n + 1) window[n] = 24'd0;
        for (i = 0; i < COUNT + LATENCY; i = i + 1) begin
            @(negedge clk);
            for (h = LATENCY; h > 0; h = h - 1) history[h] = history[h - 1];
            if (i >= LATENCY && out !== history[LATENCY]) begin
                errors = errors + 1;
                if (errors < 10) $display("wrong at %0d: got %06x want %06x", i, out, history[LATENCY]);
            end
            own = $random;
            for (n = 0; n < 9; n = n + 1)
                window[n] = (n == 4) ? own : ({$random} % 5 == 0) ? $random :
                            {moved(own[23:16], 37), moved(own[15:8], 37), moved(own[7:0], 85)};
            history[0] = wanted(0);
            if (history[0] !== own) smoothed = smoothed + 1;
        end
        if (errors == 0 && smoothed > COUNT / 4) $display("PASS: dedither_tb %0d windows, %0d changed the pixel", COUNT, smoothed);
        else $display("FAIL: dedither_tb %0d wrong, %0d changed the pixel", errors, smoothed);
        $finish;
    end
endmodule
