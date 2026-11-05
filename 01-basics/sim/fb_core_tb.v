// Self-checking testbench for fb_core.v: runs several video frames through the SDRAM model and
// compares every window pixel with the expected pattern. Writes the last frame to a PPM file.
// Use +frames=N for the run length and +ppm=PATH for the output file.
`timescale 1ns / 1ps

module fb_core_tb;

    reg clk = 1'b0;
    reg rst = 1'b1;
    always #19.84 clk = ~clk;  // 25.2 MHz

    wire        hsync, vsync, de, underrun, swap_done, front;
    wire [7:0]  red, green, blue;
    wire        cke, cs_n, ras_n, cas_n, we_n, dq_oe;
    wire [1:0]  ba;
    wire [10:0] addr;
    wire [3:0]  dqm;
    wire [31:0] dq_out;
    wire [31:0] dq;
    assign dq = dq_oe ? dq_out : 32'bz;

    fb_core dut (
        .clk(clk), .rst(rst),
        .hsync(hsync), .vsync(vsync), .de(de), .red(red), .green(green), .blue(blue),
        .underrun(underrun), .swap_done(swap_done), .front(front),
        .sdram_cke(cke), .sdram_cs_n(cs_n), .sdram_ras_n(ras_n), .sdram_cas_n(cas_n),
        .sdram_we_n(we_n), .sdram_ba(ba), .sdram_addr(addr), .sdram_dqm(dqm),
        .sdram_dq_out(dq_out), .sdram_dq_oe(dq_oe), .sdram_dq_in(dq)
    );

    sdram_model model (
        .clk(~clk), .cke(cke), .cs_n(cs_n), .ras_n(ras_n), .cas_n(cas_n), .we_n(we_n),
        .ba(ba), .addr(addr), .dqm(dqm), .dq(dq)
    );

    integer errors = 0, frames = 8, swaps = 0, frames_checked = 0, pixels_checked = 0;
    integer px = 0, py = 0;
    integer de_count = 0;
    integer fd;
    reg [23:0] capture [0:640 * 480 - 1];
    reg [8*256-1:0] ppm_path = "fb_core_tb.ppm";
    reg [7:0]  shown = 8'd0;       // pattern frame number on screen
    reg [7:0]  next_shown = 8'd0;
    reg        checking = 1'b0;
    reg        last_vsync = 1'b1;

    function [23:0] expected(input integer x, input integer y, input [7:0] frame);
        reg [7:0] p;
        begin
            if (x < 150 || x >= 490 || y < 70 || y >= 410) begin
                expected = 24'd0;
            end else begin
                p = ((x - 150) ^ (y - 70)) + frame;
                expected = {p[7:5], p[7:5], p[7:6], p[4:2], p[4:2], p[4:3], p[1:0], p[1:0], p[1:0], p[1:0]};
            end
        end
    endfunction

    initial begin
        if ($value$plusargs("frames=%d", frames)) ;
        if ($value$plusargs("ppm=%s", ppm_path)) ;
        repeat (4) @(posedge clk);
        rst <= 1'b0;
    end

    always @(posedge clk) if (!rst) begin
        if (swap_done) begin
            swaps = swaps + 1;
            if (swaps > 1) next_shown = next_shown + 1'b1;
            shown = next_shown;
            checking = 1'b1;  // from now on the screen holds a finished picture
        end

        if (de === 1'b1) begin
            if (checking && {red, green, blue} !== expected(px, py, shown)) begin
                if (errors < 20)
                    $display("ERROR pixel (%0d,%0d) frame %0d: got %h, want %h",
                             px, py, shown, {red, green, blue}, expected(px, py, shown));
                errors = errors + 1;
            end
            if (checking) pixels_checked = pixels_checked + 1;
            capture[py * 640 + px] = {red, green, blue};
            de_count = de_count + 1;
            if (px == 639) begin
                px = 0;
                py = (py == 479) ? 0 : py + 1;
            end else begin
                px = px + 1;
            end
        end

        // Frame boundary: the falling edge of vsync comes just after the visible lines.
        if (last_vsync && !vsync) begin
            if (checking) frames_checked = frames_checked + 1;
            if (py != 0 || px != 0) begin
                $display("ERROR frame ended at (%0d,%0d)", px, py);
                errors = errors + 1;
            end
            if (frames_checked == frames) finish_up;
        end
        last_vsync = vsync;

        if (underrun === 1'b1) begin
            $display("ERROR scan-out ran out of pixels at %0t", $realtime);
            errors = errors + 1;
            finish_up;
        end
    end

    integer rx, ry;
    task finish_up;
        begin
            // Save the pixels the design really put out for the last frame.
            fd = $fopen(ppm_path, "w");
            $fdisplay(fd, "P3\n640 480\n255");
            for (ry = 0; ry < 480; ry = ry + 1)
                for (rx = 0; rx < 640; rx = rx + 1)
                    $fdisplay(fd, "%0d %0d %0d", capture[ry * 640 + rx][23:16],
                              capture[ry * 640 + rx][15:8], capture[ry * 640 + rx][7:0]);
            $fclose(fd);
            $display("frames checked %0d, pixels checked %0d, swaps %0d, underrun %b", frames_checked,
                     pixels_checked, swaps, underrun);
            $display("model counted reads %0d, writes %0d, refreshes %0d, longest 4096-refresh span %0d us",
                     model.reads, model.writes, model.refreshes, model.max_refresh_window_us);
            if (errors == 0 && model.errors == 0 && frames_checked == frames && swaps >= 2)
                $display("PASS: fb_core_tb");
            else
                $display("FAIL: fb_core_tb, %0d pixel errors, %0d SDRAM rule errors", errors, model.errors);
            $finish;
        end
    endtask

    initial begin
        #2000000000;
        $display("FAIL: fb_core_tb timed out, %0d swaps, %0d frames", swaps, frames_checked);
        $finish;
    end

endmodule
