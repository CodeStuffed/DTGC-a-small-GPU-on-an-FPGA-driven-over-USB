// Self-checking testbench for video_timing.v: sync widths, line length, frame length.
`timescale 1ns / 1ps

module video_timing_tb;

    reg        clk = 1'b0;
    reg        rst = 1'b1;
    wire [9:0] x, y;
    wire       hsync, vsync, visible, frame_start;
    integer    errors = 0;
    integer    visible_count = 0;
    integer    hsync_low = 0;
    integer    vsync_low_clocks = 0;
    integer    frame_starts = 0;
    integer    cycles;
    integer    frame_starts_seen_at = -1;
    integer    frame_length = -1;

    video_timing dut (
        .clk(clk),
        .rst(rst),
        .x(x),
        .y(y),
        .hsync(hsync),
        .vsync(vsync),
        .visible(visible),
        .frame_start(frame_start)
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

        // Count over two full frames (800 x 525 clocks each).
        for (cycles = 0; cycles < 2 * 800 * 525; cycles = cycles + 1) begin
            @(negedge clk);
            if (cycles < 800 * 525) begin
                if (visible) visible_count = visible_count + 1;
                if (!vsync) vsync_low_clocks = vsync_low_clocks + 1;
                if (!hsync && y == 10'd0) hsync_low = hsync_low + 1;
                // hsync must be low only in pixels 656..751.
                if (!hsync && (x < 656 || x > 751)) fail("hsync position", x, 656);
                if (!vsync && (y < 490 || y > 491)) fail("vsync position", y, 490);
                if (visible && (x > 639 || y > 479)) fail("visible range", x, 639);
            end
            if (frame_start) begin
                if (frame_starts_seen_at >= 0 && frame_length < 0)
                    frame_length = cycles - frame_starts_seen_at;
                frame_starts_seen_at = cycles;
                frame_starts = frame_starts + 1;
            end
        end

        if (visible_count !== 640 * 480) fail("visible pixels", visible_count, 640 * 480);
        if (hsync_low !== 96)            fail("hsync width", hsync_low, 96);
        if (vsync_low_clocks !== 2 * 800) fail("vsync width in clocks", vsync_low_clocks, 1600);
        if (frame_length !== 800 * 525)  fail("frame length", frame_length, 420000);

        if (errors == 0)
            $display("PASS: video_timing_tb");
        else
            $display("FAIL: video_timing_tb, %0d errors", errors);
        $finish;
    end

endmodule
