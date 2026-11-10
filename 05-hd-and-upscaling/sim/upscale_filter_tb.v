// Every weight pair on random pixels and the extreme corners, against the same sum done in full.
// sw/tests/test_upscale_rtl.py checks whole pictures against the Python model.
`timescale 1ns / 1ps

module upscale_filter_tb;
    parameter SCALE = 2;
    localparam LATENCY = 8;

    reg clk = 0;
    always #5 clk = ~clk;

    reg  [1:0] wx = 0, wy = 0;
    reg  [7:0] a = 0, b = 0, c = 0, d = 0;
    wire [7:0] out;

    upscale_filter #(.SCALE(SCALE)) dut (
        .clk(clk), .weight_x(wx), .weight_y(wy), .top_left(a), .top_right(b), .bottom_left(c), .bottom_right(d), .out(out)
    );

    function integer weight(input [1:0] code);
        if (SCALE == 2) weight = (code == 2'd3) ? 192 : 64;
        else weight = (code == 2'd0) ? 0 : (code == 2'd1) ? 85 : 170;
    endfunction

    reg [7:0] want [0:LATENCY];
    integer i, seed = 7, errors = 0, checked = 0, age = 0, wxv, wyv;

    function [1:0] pick(input [31:0] r);
        pick = (SCALE == 2) ? (r[0] ? 2'd3 : 2'd1) : (r[15:0] % 3);
    endfunction

    initial begin
        for (i = 0; i < 400000; i = i + 1) begin
            @(negedge clk);
            if (age > LATENCY && out !== want[LATENCY]) begin
                errors = errors + 1;
                if (errors <= 10) $display("clock %0d: got %0d, wanted %0d", i, out, want[LATENCY]);
            end
            if (age > LATENCY) checked = checked + 1;
            age = age + 1;
            wx = pick($random(seed));
            wy = pick($random(seed));
            if (i % 4 == 0) begin
                a = $random(seed) & 1 ? 8'd255 : 8'd0;
                b = $random(seed) & 1 ? 8'd255 : 8'd0;
                c = $random(seed) & 1 ? 8'd255 : 8'd0;
                d = $random(seed) & 1 ? 8'd255 : 8'd0;
            end else begin
                a = $random(seed);
                b = $random(seed);
                c = $random(seed);
                d = $random(seed);
            end
            wxv = weight(wx);
            wyv = weight(wy);
            // Newest goes in slot 1, because the check above runs one clock before the shift below.
            want[0] = (((a * (256 - wxv) + b * wxv) * (256 - wyv) + (c * (256 - wxv) + d * wxv) * wyv) + 32768) >> 16;
            for (wxv = LATENCY; wxv > 0; wxv = wxv - 1) want[wxv] = want[wxv - 1];
        end
        if (errors == 0 && checked > 390000)
            $display("PASS: upscale_filter_tb scale %0d, %0d blends compared", SCALE, checked);
        else
            $display("FAIL: upscale_filter_tb scale %0d, %0d errors in %0d blends", SCALE, errors, checked);
        $finish;
    end
endmodule
