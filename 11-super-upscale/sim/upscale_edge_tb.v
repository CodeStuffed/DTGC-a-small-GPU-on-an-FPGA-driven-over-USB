// Checks rtl/upscale_edge.v against its formula on random pixels, written here from the triangle equations in
// sw/dtgc/upscale.py and not from the module's weight table. Half the pixels are a flat colour plus a small change, so the
// two diagonals' brightness changes are often close or equal. Run once per SCALE (-Pupscale_edge_tb.SCALE=N).
// The whole-GPU comparison is in sw/tests/test_upscale_rtl.py.
`timescale 1ns / 1ps

module upscale_edge_tb;
    parameter SCALE = 2;
    localparam LATENCY = 8, COUNT = 200000, UNIT = 2 * SCALE;

    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg  [4:0]  u = 5'd1, v = 5'd1;
    reg  [23:0] a = 0, b = 0, c = 0, d = 0;
    wire [23:0] out;

    upscale_edge #(.SCALE(SCALE)) dut (
        .clk(clk), .phase_x(u), .phase_y(v), .top_left(a), .top_right(b), .bottom_left(c), .bottom_right(d), .out(out)
    );

    function integer brightness(input [23:0] pixel);
        brightness = (pixel[23:16] + 2 * pixel[15:8] + pixel[7:0]) / 4;
    endfunction

    function integer distance(input integer x, input integer y);
        distance = (x > y) ? x - y : y - x;
    endfunction

    function integer blend(input integer ca, input integer cb, input integer cc, input integer cd,
                           input integer pu, input integer pv, input main_diagonal);
        integer picked;
        begin
            if (main_diagonal)
                picked = (pu >= pv) ? UNIT * ca + pu * (cb - ca) + pv * (cd - cb)
                                    : UNIT * ca + pu * (cd - cc) + pv * (cc - ca);
            else
                picked = (pu + pv <= UNIT) ? UNIT * ca + pu * (cb - ca) + pv * (cc - ca)
                                           : UNIT * cd + (UNIT - pu) * (cc - cd) + (UNIT - pv) * (cb - cd);
            blend = (picked + SCALE) / UNIT;
        end
    endfunction

    function [23:0] wanted(input [23:0] pa, input [23:0] pb, input [23:0] pc, input [23:0] pd, input integer pu, input integer pv);
        reg main_diagonal;
        integer red, green, blue;
        begin
            main_diagonal = distance(brightness(pa), brightness(pd)) <= distance(brightness(pb), brightness(pc));
            red   = blend(pa[23:16], pb[23:16], pc[23:16], pd[23:16], pu, pv, main_diagonal);
            green = blend(pa[15:8], pb[15:8], pc[15:8], pd[15:8], pu, pv, main_diagonal);
            blue  = blend(pa[7:0], pb[7:0], pc[7:0], pd[7:0], pu, pv, main_diagonal);
            wanted = {red[7:0], green[7:0], blue[7:0]};
        end
    endfunction

    function [23:0] near(input [23:0] pixel);
        integer change;
        begin
            change = $random & 3;
            near = pixel ^ change;
        end
    endfunction

    reg [23:0] history [0:LATENCY];
    integer i, h, errors = 0;

    initial begin
        for (i = 0; i < COUNT + LATENCY; i = i + 1) begin
            @(negedge clk);
            for (h = LATENCY; h > 0; h = h - 1) history[h] = history[h - 1];
            if (i >= LATENCY && out !== history[LATENCY]) begin
                errors = errors + 1;
                if (errors < 10) $display("wrong at %0d: got %06x want %06x", i, out, history[LATENCY]);
            end
            a = $random;
            b = (i % 2) ? near(a) : $random;
            c = (i % 2) ? near(a) : $random;
            d = (i % 2) ? near(a) : $random;
            // A position the scan-out makes: 2 * k, plus 1 when SCALE is even, for k from 0 to SCALE - 1.
            u = 2 * ({$random} % SCALE) + (SCALE % 2 == 0);
            v = 2 * ({$random} % SCALE) + (SCALE % 2 == 0);
            history[0] = wanted(a, b, c, d, u, v);
        end
        if (errors == 0) $display("PASS: upscale_edge_tb x%0d %0d pixels", SCALE, COUNT);
        else $display("FAIL: upscale_edge_tb %0d wrong", errors);
        $finish;
    end
endmodule
