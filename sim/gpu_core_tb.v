// Runs a byte stream through gpu_core.v, then dumps everything sw/tests/test_rtl_match.py compares
// with the Python emulator: both framebuffers, the palette, the replies and the final screen.
// +stream=PATH is a hex file, one 9-bit word a line: 0-255 is a byte, 100 hex means "stay silent long
// enough for the parser's timeout". +words=N is its length. +out=PREFIX names the dump files.
// Compiled with -DUSE_FT_LINK, the bytes travel through rtl/ft_link.v and the FT2232H model instead of
// going straight in, with +rxstall=PERCENT and +txstall=PERCENT making the chip hesitate.
// -Pgpu_core_tb.SCANOUT=0 tests the USB-output version: the same, with no video to check.
`timescale 1ns / 1ps

module gpu_core_tb;

    reg clk = 1'b0;
    reg rst = 1'b1;
    always #19.84 clk = ~clk;  // 25.2 MHz

    localparam IDLE_TIMEOUT = 200;
    parameter SCANOUT = 1;
    parameter WIDTH = 340;
    parameter HEIGHT = 340;
    localparam LINE_WORDS = (WIDTH + 3) / 4;
    localparam DEPTH_WORDS = WIDTH / 2;
    localparam TWO_DEPTH_ROWS = WIDTH > 512;

`ifdef USE_FT_LINK
    wire        rx_valid, tx_ready;
    wire [7:0]  rx_data;
`else
    reg         rx_valid = 1'b0;
    reg  [7:0]  rx_data = 8'd0;
    // The link taking reply bytes only some of the time: +txstall=PERCENT is the chance it refuses one.
    reg         tx_ready = 1'b1;
    integer     tx_stall = 0;
    always @(negedge clk) tx_ready = ($urandom_range(99) >= tx_stall);
`endif
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

    gpu_core #(.IDLE_TIMEOUT(IDLE_TIMEOUT), .SCANOUT(SCANOUT), .WIDTH(WIDTH), .HEIGHT(HEIGHT), .LINE_WORDS(LINE_WORDS)) dut (
        .clk(clk), .rst(rst), .rx_valid(rx_valid), .rx_data(rx_data), .rx_used(rx_used),
        .rx_overflow(rx_overflow), .tx_valid(tx_valid), .tx_data(tx_data), .tx_ready(tx_ready),
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

`ifdef USE_FT_LINK
    reg ft_clk = 1'b0;
    always #8.333 ft_clk = ~ft_clk;  // 60 MHz

    wire       rxf_n, txe_n, oe_n, rd_n, wr_n, d_oe;
    wire [7:0] d_out, d_in;

    // The same limit as rtl/top_gpu_ft.v.
    ft_link link (
        .clk(clk), .rst(rst), .rx_valid(rx_valid), .rx_data(rx_data), .rx_ready(rx_used < 11'd1020),
        .tx_valid(tx_valid), .tx_data(tx_data), .tx_ready(tx_ready),
        .ft_clk(ft_clk), .ft_rxf_n(rxf_n), .ft_txe_n(txe_n), .ft_oe_n(oe_n), .ft_rd_n(rd_n), .ft_wr_n(wr_n),
        .ft_d_in(d_in), .ft_d_out(d_out), .ft_d_oe(d_oe)
    );

    ft2232h_model #(.QUEUE_BITS(22)) chip (
        .clk(ft_clk), .rxf_n(rxf_n), .txe_n(txe_n), .oe_n(oe_n), .rd_n(rd_n), .wr_n(wr_n),
        .d_from_fpga(d_out), .d_oe_fpga(d_oe), .d_to_fpga(d_in)
    );

    // Every byte has left the chip and crossed into the GPU's own buffer.
    task link_drained;
        begin
            wait (chip.rx_head == chip.rx_tail);
            repeat (40) @(posedge clk);
        end
    endtask
`endif

    reg [8:0] stream [0:4000000];
    integer words = 0, i, fd, replies = 0, px, py, b, r, c;
    reg [8*256-1:0] stream_path, out_prefix, name;
    reg [23:0] screen [0:640 * 480 - 1];

    // Replies go straight to a file.
    integer reply_fd;
`ifndef USE_FT_LINK
    always @(posedge clk) if (!rst && tx_valid && tx_ready) begin
        $fdisplay(reply_fd, "%02x", tx_data);
        replies = replies + 1;
    end
`endif

    // Anything written outside the picture would be invisible in the memory dump, so count it here.
    integer out_of_range = 0;
    always @(posedge clk) if (!rst && dut.wr_valid && dut.wr_ready
                              && ((dut.wr_bank[1] == 1'b0 && (dut.wr_row >= HEIGHT || dut.wr_col >= LINE_WORDS))
                                  || (dut.wr_bank == 2'd2 && !TWO_DEPTH_ROWS && (dut.wr_row >= HEIGHT || dut.wr_col >= DEPTH_WORDS))
                                  || (dut.wr_bank == 2'd2 && TWO_DEPTH_ROWS
                                      && (dut.wr_row >= 2 * HEIGHT || {dut.wr_row[0], dut.wr_col} >= DEPTH_WORDS))))
        out_of_range = out_of_range + 1;

    // A read word that arrives while nothing waits for one does no harm until a later read
    // starts soon enough to count it as its own, so one arriving at all is an error.
    integer stray_words = 0;
    always @(posedge clk) if (!rst && dut.rr_done && dut.triangles.state != dut.triangles.S_DEPTH_WAIT
                              && dut.triangles.state != dut.triangles.S_TEX_WAIT
                              && dut.reader.state != dut.reader.S_WAIT)
        stray_words = stray_words + 1;

    // How long the design took to take the whole stream, for scripts/rtl_speed.py.
    integer clocks = 0, stream_clocks = 0;
    always @(posedge clk) if (!rst && dut.init_done) clocks = clocks + 1;

    task quiet_until_done;
        begin
            // Everything sent has been taken, and the parser and executor have gone idle.
            wait (rx_used == 0);
            repeat (20) @(posedge clk);
            while (dut.exec.state != dut.exec.S_IDLE || dut.parser.pkt_valid || dut.replies.busy)
                @(posedge clk);
        end
    endtask

    initial begin
        // Real block RAM wakes up holding anything. An unknown here would read as "marked" and hide a missed row.
        for (i = 0; i < ((HEIGHT > 512) ? 1024 : 512); i = i + 1) dut.triangles.flags.rows[i] = {$random, $random};
        if (!$value$plusargs("stream=%s", stream_path)) $fatal(1, "need +stream");
        if (!$value$plusargs("words=%d", words)) $fatal(1, "need +words");
        if (!$value$plusargs("out=%s", out_prefix)) $fatal(1, "need +out");
        $readmemh(stream_path, stream, 0, words - 1);
        $sformat(name, "%0s.replies", out_prefix);
        reply_fd = $fopen(name, "w");

        repeat (4) @(posedge clk);
        rst <= 1'b0;
        wait (dut.init_done);
        repeat (300) @(posedge clk);  // the default palette has finished loading

`ifdef USE_FT_LINK
        if ($value$plusargs("rxstall=%d", i)) chip.stall_rx_percent = i;
        if ($value$plusargs("txstall=%d", i)) chip.stall_tx_percent = i;
        for (i = 0; i < words; i = i + 1) begin
            if (stream[i] === 9'h100) begin
                link_drained;
                quiet_until_done;
                repeat (IDLE_TIMEOUT + 10) @(posedge clk);
            end else begin
                chip.pc_send(stream[i][7:0]);
            end
        end
        link_drained;
`else
        if ($value$plusargs("txstall=%d", i)) tx_stall = i;
        for (i = 0; i < words; i = i + 1) begin
            if (stream[i] === 9'h100) begin
                @(negedge clk);
                rx_valid = 1'b0;
                quiet_until_done;
                repeat (IDLE_TIMEOUT + 10) @(posedge clk);
            end else begin
                // Holding back at 900 stands in for the PC's flow control.
                while (rx_used > 900) @(posedge clk);
                @(negedge clk);
                rx_valid = 1'b1;
                rx_data = stream[i][7:0];
            end
            @(negedge clk);
            rx_valid = 1'b0;
        end
`endif
        quiet_until_done;
        stream_clocks = clocks;

        // Let a complete frame go by, then capture the next from the video output.
        @(negedge vsync);
        @(negedge vsync);
        px = 0;
        py = 0;
        while (SCANOUT != 0 && py < 480) begin
            @(posedge clk);
            if (de === 1'b1) begin
                screen[py * 640 + px] = {red, green, blue};
                if (px == 639) begin
                    px = 0;
                    py = py + 1;
                end else begin
                    px = px + 1;
                end
            end
        end

`ifdef USE_FT_LINK
        // What matters is what reached the PC, so these come from the chip's end of the link.
        replies = chip.tx_count;
        for (i = 0; i < chip.tx_count; i = i + 1) $fdisplay(reply_fd, "%02x", chip.tx_queue[i]);
        if (chip.errors != 0) $display("FAIL: %0d FT2232H rule errors", chip.errors);
`endif
        $fclose(reply_fd);

        $sformat(name, "%0s.memory", out_prefix);
        fd = $fopen(name, "w");
        for (b = 0; b < 2; b = b + 1)
            for (r = 0; r < HEIGHT; r = r + 1)
                for (c = 0; c < LINE_WORDS; c = c + 1)
                    $fdisplay(fd, "%08x", model.mem[{b[1:0], r[10:0], c[7:0]}]);
        $fclose(fd);

        $sformat(name, "%0s.depth", out_prefix);
        fd = $fopen(name, "w");
        for (r = 0; r < HEIGHT; r = r + 1)
            for (c = 0; c < DEPTH_WORDS; c = c + 1)
                if (TWO_DEPTH_ROWS) $fdisplay(fd, "%08x", model.mem[{2'd2, r[9:0], c[8], c[7:0]}]);
                else $fdisplay(fd, "%08x", model.mem[{2'd2, r[10:0], c[7:0]}]);
        $fclose(fd);

        // Only the rows and columns the test streams make known: 32 rows of 16 bytes.
        $sformat(name, "%0s.texture", out_prefix);
        fd = $fopen(name, "w");
        for (r = 0; r < 32; r = r + 1)
            for (c = 0; c < 4; c = c + 1)
                $fdisplay(fd, "%08x", model.mem[{2'd3, r[10:0], c[7:0]}]);
        $fclose(fd);

        $sformat(name, "%0s.palette", out_prefix);
        fd = $fopen(name, "w");
        for (i = 0; i < 256; i = i + 1) $fdisplay(fd, "%06x", dut.sd.scanout.pal_mem[i]);
        $fclose(fd);

        $sformat(name, "%0s.screen", out_prefix);
        fd = $fopen(name, "w");
        for (i = 0; i < 640 * 480; i = i + 1) $fdisplay(fd, "%06x", screen[i]);
        $fclose(fd);

        $sformat(name, "%0s.state", out_prefix);
        fd = $fopen(name, "w");
        $fdisplay(fd, "front %0d", dut.front);
        $fdisplay(fd, "expected %0d", dut.exec.expected);
        $fdisplay(fd, "overflow %0d", rx_overflow);
        $fdisplay(fd, "underrun %0d", SCANOUT != 0 && underrun);
        $fdisplay(fd, "rule_errors %0d", model.errors);
        $fdisplay(fd, "out_of_range %0d", out_of_range);
        $fdisplay(fd, "stray_words %0d", stray_words);
        $fdisplay(fd, "stream_clocks %0d", stream_clocks);
        $fclose(fd);

`ifdef USE_FT_LINK
        if (chip.errors != 0) $finish;
`endif
        $display("PASS: gpu_core_tb finished, %0d words, %0d reply bytes, %0d SDRAM rule errors",
                 words, replies, model.errors);
        $finish;
    end

    initial begin
        #4000000000;
        $display("FAIL: gpu_core_tb timed out at word %0d", i);
        $finish;
    end

endmodule
