// Drives rtl/shade_pipe.v from a file of test vectors, one pixel per clock, and writes what comes out.
// +in=PATH +words=N +out=PATH. Each vector is one hex line, packed as in sw/tests/test_shade_rtl.py.
// Gaps with in_valid low check that the valid flag follows the data.
`timescale 1ns / 1ps

module shade_pipe_tb;
    localparam BITS = 6 * 16 + 9 + 8 + 8 + 8 + 24 + 24 + 9;

    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg [BITS-1:0] vectors [0:200000];
    reg [BITS-1:0] now = 0;
    reg in_valid = 1'b0;
    wire out_valid;
    wire [23:0] out;

    shade_pipe dut (
        .clk(clk), .in_valid(in_valid),
        .normal_x(now[185:170]), .normal_y(now[169:154]), .normal_z(now[153:138]),
        .light_x(now[137:122]), .light_y(now[121:106]), .light_z(now[105:90]),
        .ambient(now[89:81]), .noise_amount(now[80:73]), .pixel_x(now[72:65]), .pixel_y(now[64:57]),
        .base(now[56:33]), .dst(now[32:9]), .alpha(now[8:0]),
        .out_valid(out_valid), .out(out)
    );

    integer words = 0, i, fd, seen = 0;
    reg [8*256-1:0] in_path, out_path;

    always @(posedge clk) begin
        if (out_valid === 1'b1) begin
            $fdisplay(fd, "%06x", out);
            seen = seen + 1;
        end
    end

    initial begin
        if (!$value$plusargs("in=%s", in_path)) $fatal(1, "need +in");
        if (!$value$plusargs("out=%s", out_path)) $fatal(1, "need +out");
        if (!$value$plusargs("words=%d", words)) $fatal(1, "need +words");
        $readmemh(in_path, vectors, 0, words - 1);
        fd = $fopen(out_path, "w");
        repeat (8) @(negedge clk);
        for (i = 0; i < words; i = i + 1) begin
            now = vectors[i];
            in_valid = 1'b1;
            @(negedge clk);
            if (i % 7 == 3) begin
                in_valid = 1'b0;
                now = {BITS{1'b1}};
                @(negedge clk);
            end
        end
        in_valid = 1'b0;
        repeat (10) @(negedge clk);
        $fclose(fd);
        if (seen == words) $display("PASS: shade_pipe_tb %0d pixels came out", seen);
        else $display("FAIL: shade_pipe_tb %0d of %0d pixels came out", seen, words);
        $finish;
    end
endmodule
