// Runs a byte stream through gpu_core.v with the HD scan-out, then saves the whole screen for sw/tests/test_upscale_rtl.py
// to compare with the Python scaler. The core and video clocks never line up, as on the real board.
// +stream=PATH +words=N +out=PREFIX as in gpu_core_tb.v. Mode and clock come from the parameters below.
// +no_screen skips the screen, for scripts/profile_raster.py, which only wants the clocks with the video reading memory.
`timescale 1ns / 1ps

module gpu_hd_tb;

    parameter SCALE = 2;
    parameter EDGE = 0;
    parameter WIDTH = 340;
    parameter HEIGHT = 340;
    parameter LINE_WORDS = 85;
    parameter H_VISIBLE = 1280;
    parameter H_FRONT = 110;
    parameter H_SYNC = 40;
    parameter H_BACK = 220;
    parameter V_VISIBLE = 720;
    parameter V_FRONT = 5;
    parameter V_SYNC = 5;
    parameter V_BACK = 20;
    parameter VIDEO_HALF_NS = 6.734;   // 74.25 MHz
    parameter CORE_HALF_NS = 10.775;   // 46.41 MHz: 371.25 MHz / 8

    localparam IDLE_TIMEOUT = 200;

    reg clk = 1'b0;
    reg clk_video = 1'b0;
    reg rst = 1'b1;
    reg rst_video = 1'b1;
    always #CORE_HALF_NS clk = ~clk;
    always #VIDEO_HALF_NS clk_video = ~clk_video;

    reg         rx_valid = 1'b0;
    reg  [7:0]  rx_data = 8'd0;
    wire [10:0] rx_used;
    wire        rx_overflow, tx_valid, hsync, vsync, de, underrun;
    wire [7:0]  tx_data, red, green, blue;
    wire        cke, cs_n, ras_n, cas_n, we_n, dq_oe;
    wire [1:0]  ba;
    wire [10:0] addr;
    wire [3:0]  dqm;
    wire [31:0] dq_out;
    wire [31:0] dq;
    assign dq = dq_oe ? dq_out : 32'bz;

    // The core's reply path is the slow serial link on real boards, tested in gpu_core_tb.v.
    gpu_core #(
        .IDLE_TIMEOUT(IDLE_TIMEOUT), .SCANOUT(2), .SCALE(SCALE), .EDGE(EDGE), .WIDTH(WIDTH), .HEIGHT(HEIGHT), .LINE_WORDS(LINE_WORDS),
        .H_VISIBLE(H_VISIBLE), .H_FRONT(H_FRONT), .H_SYNC(H_SYNC), .H_BACK(H_BACK),
        .V_VISIBLE(V_VISIBLE), .V_FRONT(V_FRONT), .V_SYNC(V_SYNC), .V_BACK(V_BACK)
    ) dut (
        .clk(clk), .rst(rst), .clk_video(clk_video), .rst_video(rst_video),
        .rx_valid(rx_valid), .rx_data(rx_data), .rx_used(rx_used),
        .rx_overflow(rx_overflow), .tx_valid(tx_valid), .tx_data(tx_data), .tx_ready(1'b1),
        .hsync(hsync), .vsync(vsync), .de(de), .red(red), .green(green), .blue(blue),
        .underrun(underrun),
        .sdram_cke(cke), .sdram_cs_n(cs_n), .sdram_ras_n(ras_n), .sdram_cas_n(cas_n),
        .sdram_we_n(we_n), .sdram_ba(ba), .sdram_addr(addr), .sdram_dqm(dqm),
        .sdram_dq_out(dq_out), .sdram_dq_oe(dq_oe), .sdram_dq_in(dq)
    );

    sdram_model model (
        .clk(~clk), .cke(cke), .cs_n(cs_n), .ras_n(ras_n), .cas_n(cas_n), .we_n(we_n),
        .ba(ba), .addr(addr), .dqm(dqm), .dq(dq)
    );

    reg [8:0] stream [0:4000000];
    integer words = 0, i, fd, px, py, replies = 0;
    reg [8*256-1:0] stream_path, out_prefix, name;
    reg [23:0] screen [0:H_VISIBLE * V_VISIBLE - 1];

    integer clocks = 0, stream_clocks = 0;
    always @(posedge clk) begin
        clocks = clocks + 1;
        if (!rst && tx_valid) replies = replies + 1;
    end

    task quiet_until_done;
        begin
            wait (rx_used == 0);
            repeat (20) @(posedge clk);
            while (dut.exec.state != dut.exec.S_IDLE || dut.parser.pkt_valid || dut.replies.busy)
                @(posedge clk);
        end
    endtask

    initial begin
        for (i = 0; i < ((HEIGHT > 512) ? 1024 : 512); i = i + 1) dut.triangles.flags.rows[i] = {$random, $random};
        if (!$value$plusargs("stream=%s", stream_path)) $fatal(1, "need +stream");
        if (!$value$plusargs("words=%d", words)) $fatal(1, "need +words");
        if (!$value$plusargs("out=%s", out_prefix)) $fatal(1, "need +out");
        $readmemh(stream_path, stream, 0, words - 1);

        repeat (4) @(posedge clk);
        rst <= 1'b0;
        rst_video <= 1'b0;
        wait (dut.init_done);
        repeat (300) @(posedge clk);

        for (i = 0; i < words; i = i + 1) begin
            if (stream[i] === 9'h100) begin
                @(negedge clk);
                rx_valid = 1'b0;
                quiet_until_done;
                repeat (IDLE_TIMEOUT + 10) @(posedge clk);
            end else begin
                while (rx_used > 900) @(posedge clk);
                @(negedge clk);
                rx_valid = 1'b1;
                rx_data = stream[i][7:0];
            end
            @(negedge clk);
            rx_valid = 1'b0;
        end
        quiet_until_done;
        stream_clocks = clocks;

        // A whole frame goes by so the last swap has shown, then the next frame is saved.
        if (!$test$plusargs("no_screen")) begin
            @(negedge vsync);
            @(negedge vsync);
        end
        px = 0;
        py = $test$plusargs("no_screen") ? V_VISIBLE : 0;
        while (py < V_VISIBLE) begin
            @(posedge clk_video);
            if (de === 1'b1) begin
                screen[py * H_VISIBLE + px] = {red, green, blue};
                if (px == H_VISIBLE - 1) begin
                    px = 0;
                    py = py + 1;
                end else begin
                    px = px + 1;
                end
            end
        end

        if (!$test$plusargs("no_screen")) begin
            $sformat(name, "%0s.screen", out_prefix);
            fd = $fopen(name, "w");
            for (i = 0; i < H_VISIBLE * V_VISIBLE; i = i + 1) $fdisplay(fd, "%06x", screen[i]);
            $fclose(fd);
        end

        $sformat(name, "%0s.state", out_prefix);
        fd = $fopen(name, "w");
        $fdisplay(fd, "overflow %0d", rx_overflow);
        $fdisplay(fd, "underrun %0d", underrun);
        $fdisplay(fd, "rule_errors %0d", model.errors);
        $fdisplay(fd, "stream_clocks %0d", stream_clocks);
        $fclose(fd);

        $display("PASS: gpu_hd_tb finished, %0d words, %0d reply bytes, %0d SDRAM rule errors", words, replies, model.errors);
        $finish;
    end

    initial begin
        #8000000000;
        $display("FAIL: gpu_hd_tb timed out at word %0d", i);
        $finish;
    end

endmodule
