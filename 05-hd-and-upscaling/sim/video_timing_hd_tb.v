// Self-checking testbench for video_timing.v in the 1920x1080 @ 30 Hz mode: 2200 x 1125 clocks,
// sync active high and in the positions the video standard gives.
`timescale 1ns / 1ps

module video_timing_hd_tb;

    reg         clk = 1'b0;
    reg         rst = 1'b1;
    wire [11:0] x, y;
    wire        hsync, vsync, visible, frame_start;
    integer     errors = 0, cycles, visible_count = 0, hsync_high = 0, vsync_high = 0;
    integer     first_start = -1, frame_length = -1;

    video_timing #(
        .H_VISIBLE(1920), .H_FRONT(88), .H_SYNC(44), .H_BACK(148),
        .V_VISIBLE(1080), .V_FRONT(4), .V_SYNC(5), .V_BACK(36),
        .BITS(12), .SYNC_HIGH(1)
    ) dut (
        .clk(clk), .rst(rst), .x(x), .y(y), .hsync(hsync), .vsync(vsync),
        .visible(visible), .frame_start(frame_start)
    );

    always #5 clk = ~clk;

    task fail(input [8*40-1:0] message, input integer got, input integer want);
        begin
            $display("ERROR %0s: got %0d, want %0d", message, got, want);
            errors = errors + 1;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst = 1'b0;
        for (cycles = 0; cycles < 2 * 2200 * 1125; cycles = cycles + 1) begin
            @(negedge clk);
            if (cycles < 2200 * 1125) begin
                if (visible) visible_count = visible_count + 1;
                if (vsync) vsync_high = vsync_high + 1;
                if (hsync && y == 12'd0) hsync_high = hsync_high + 1;
                if (hsync && (x < 2008 || x > 2051)) fail("hsync position", x, 2008);
                if (vsync && (y < 1084 || y > 1088)) fail("vsync position", y, 1084);
                if (visible && (x > 1919 || y > 1079)) fail("visible range", x, 1919);
            end
            if (frame_start) begin
                if (first_start >= 0 && frame_length < 0) frame_length = cycles - first_start;
                if (first_start < 0) first_start = cycles;
            end
        end
        if (visible_count !== 1920 * 1080) fail("visible pixels", visible_count, 1920 * 1080);
        if (hsync_high !== 44)             fail("hsync width", hsync_high, 44);
        if (vsync_high !== 5 * 2200)       fail("vsync width in clocks", vsync_high, 11000);
        if (frame_length !== 2200 * 1125)  fail("frame length", frame_length, 2475000);
        if (errors == 0)
            $display("PASS: video_timing_hd_tb");
        else
            $display("FAIL: video_timing_hd_tb, %0d errors", errors);
        $finish;
    end

endmodule
