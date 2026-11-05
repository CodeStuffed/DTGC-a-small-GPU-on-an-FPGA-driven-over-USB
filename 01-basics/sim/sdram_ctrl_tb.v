// Self-checking testbench for sdram_ctrl.v: random byte writes against a shadow copy, with line
// reads and refreshes arriving on the video schedule. Pick the random run with +seed=N and the
// length with +ops=N.
`timescale 1ns / 1ps

module sdram_ctrl_tb;

    reg clk = 1'b0;
    reg rst = 1'b1;
    always #19.84 clk = ~clk;  // 25.2 MHz

    wire        init_done, rd_valid, wr_ready;
    reg         line_req = 1'b0, line_read = 1'b0;
    reg  [1:0]  line_bank = 2'd0;
    reg  [10:0] line_row = 11'd0;
    wire [31:0] rd_data;
    reg         wr_valid = 1'b0;
    reg  [1:0]  wr_bank = 2'd0;
    reg  [10:0] wr_row = 11'd0;
    reg  [7:0]  wr_col = 8'd0;
    reg  [31:0] wr_data = 32'd0;
    reg  [3:0]  wr_be = 4'b0000;
    wire        rr_ready, rr_done;
    reg         rr_valid = 1'b0;
    reg  [1:0]  rr_bank = 2'd0;
    reg  [10:0] rr_row = 11'd0;
    reg  [7:0]  rr_col = 8'd0;
    reg  [3:0]  rr_len = 4'd1;

    wire        cke, cs_n, ras_n, cas_n, we_n, dq_oe;
    wire [1:0]  ba;
    wire [10:0] addr;
    wire [3:0]  dqm;
    wire [31:0] dq_out;
    wire [31:0] dq;
    assign dq = dq_oe ? dq_out : 32'bz;

    sdram_ctrl dut (
        .clk(clk), .rst(rst), .init_done(init_done),
        .line_req(line_req), .line_read(line_read), .line_bank(line_bank), .line_row(line_row),
        .rd_valid(rd_valid), .rd_data(rd_data),
        .wr_valid(wr_valid), .wr_ready(wr_ready), .wr_bank(wr_bank), .wr_row(wr_row),
        .wr_col(wr_col), .wr_data(wr_data), .wr_be(wr_be),
        .rr_valid(rr_valid), .rr_ready(rr_ready), .rr_bank(rr_bank), .rr_row(rr_row), .rr_col(rr_col),
        .rr_len(rr_len), .rr_done(rr_done),
        .sdram_cke(cke), .sdram_cs_n(cs_n), .sdram_ras_n(ras_n), .sdram_cas_n(cas_n),
        .sdram_we_n(we_n), .sdram_ba(ba), .sdram_addr(addr), .sdram_dqm(dqm),
        .sdram_dq_out(dq_out), .sdram_dq_oe(dq_oe), .sdram_dq_in(dq)
    );

    sdram_model model (
        .clk(~clk), .cke(cke), .cs_n(cs_n), .ras_n(ras_n), .cas_n(cas_n), .we_n(we_n),
        .ba(ba), .addr(addr), .dqm(dqm), .dq(dq)
    );

    // Tests 4 banks x 8 rows x 85 columns, spreading the rows across the row bits.
    reg [31:0] shadow [0:(4 * 8 * 85) - 1];
    integer errors = 0, seed = 1, ops = 20000;
    integer writes_done = 0, lines_checked = 0, words_checked = 0;
    integer i, w_seed, l_seed, words_seen;
    integer expected_words = 0;
    integer line_index = 0;
    reg     filling = 1'b1;
    reg     done = 1'b0;

    function [10:0] row_of(input integer r);
        row_of = {r[2:0], 8'b0} ^ {8'b0, r[2:0]};  // uses both high and low address bits
    endfunction

    function integer index_of(input integer b, input integer r, input integer c);
        index_of = ((b * 8 + r) * 85) + c;
    endfunction

    // Write process: fills all the memory under test, then writes random bytes.
    integer wb, wr, wc, k;
    reg [31:0] rnd, merged;
    initial begin
        if ($value$plusargs("seed=%d", seed)) ;
        if ($value$plusargs("ops=%d", ops)) ;
        w_seed = seed;
        l_seed = seed + 1000;
        repeat (4) @(posedge clk);
        rst <= 1'b0;
        wait (init_done);

        for (wb = 0; wb < 4; wb = wb + 1)
            for (wr = 0; wr < 8; wr = wr + 1)
                for (wc = 0; wc < 85; wc = wc + 1) begin
                    rnd = $random(w_seed);
                    do_write(wb, wr, wc, rnd, 4'b1111);
                end
        filling = 1'b0;

        for (k = 0; k < ops; k = k + 1) begin
            wb = $random(w_seed) & 3;
            wr = $random(w_seed) & 7;
            wc = $unsigned($random(w_seed)) % 85;
            rnd = $random(w_seed);
            do_write(wb, wr, wc, rnd, $random(w_seed) & 15);
            if (($random(w_seed) & 7) == 0) repeat ($random(w_seed) & 15) @(posedge clk);
        end
        done = 1'b1;
    end

    task do_write(input integer b, input integer r, input integer c, input [31:0] data, input [3:0] be);
        integer idx;
        begin
            @(negedge clk);
            wr_valid = 1'b1;
            wr_bank = b;
            wr_row = row_of(r);
            wr_col = c;
            wr_data = data;
            wr_be = be;
            @(posedge clk);
            while (!wr_ready) @(posedge clk);
            idx = index_of(b, r, c);
            merged = shadow[idx];
            if (be[0]) merged[7:0] = data[7:0];
            if (be[1]) merged[15:8] = data[15:8];
            if (be[2]) merged[23:16] = data[23:16];
            if (be[3]) merged[31:24] = data[31:24];
            shadow[idx] = merged;
            writes_done = writes_done + 1;
            @(negedge clk);
            wr_valid = 1'b0;
        end
    endtask

    // Read process: random bursts, each compared with what memory held when the burst was accepted.
    // Writes keep arriving, so one lands straight after a burst whenever the controller allows it.
    integer r_seed, burst_b, burst_r, burst_c, burst_i, burst_hits = 0, burst_misses = 0;
    integer burst_words_checked = 0, burst_words_left = 0, burst_position = 0;
    reg [31:0] burst_expected [0:7];
    initial begin
        r_seed = seed + 2000;
        wait (!filling);
        while (!done) begin
            repeat ($unsigned($random(r_seed)) % 40) @(posedge clk);
            @(negedge clk);
            burst_b = $random(r_seed) & 3;
            burst_r = $random(r_seed) & 7;
            burst_c = $unsigned($random(r_seed)) % (85 - 8);
            rr_bank = burst_b;
            rr_row  = row_of(burst_r);
            rr_col  = burst_c;
            rr_len  = ($unsigned($random(r_seed)) % 8) + 1;
            rr_valid = 1'b1;
            @(posedge clk);
            while (!rr_ready) @(posedge clk);
            if (dut.read_hit) burst_hits = burst_hits + 1;
            else              burst_misses = burst_misses + 1;
            for (burst_i = 0; burst_i < rr_len; burst_i = burst_i + 1)
                burst_expected[burst_i] = shadow[index_of(burst_b, burst_r, burst_c + burst_i)];
            burst_words_left = rr_len;
            burst_position = 0;
            @(negedge clk);
            rr_valid = 1'b0;
            wait (burst_words_left == 0);
        end
    end

    always @(posedge clk) begin
        if (rr_done) begin
            if (burst_words_left == 0) begin
                $display("ERROR at %0t: a burst word arrived that nobody asked for", $realtime);
                errors = errors + 1;
            end else begin
                if (rd_data !== burst_expected[burst_position]) begin
                    if (errors < 20)
                        $display("ERROR at %0t: burst word %0d read %h, want %h", $realtime, burst_position,
                                 rd_data, burst_expected[burst_position]);
                    errors = errors + 1;
                end
                burst_position = burst_position + 1;
                burst_words_left = burst_words_left - 1;
                burst_words_checked = burst_words_checked + 1;
            end
        end
    end

    // Line process: one request per 800 clocks, as the video side will make.
    integer lb, lr;
    reg want_read;
    initial begin
        wait (init_done);
        while (!done) begin
            repeat (799) @(posedge clk);
            @(negedge clk);
            want_read = !filling && (($random(l_seed) & 3) != 0);
            lb = $random(l_seed) & 3;
            lr = $random(l_seed) & 7;
            line_req = 1'b1;
            line_read = want_read;
            line_bank = lb;
            line_row = row_of(lr);
            words_seen = 0;
            expected_words = want_read ? 85 : 0;
            line_index = index_of(lb, lr, 0);
            @(negedge clk);
            line_req = 1'b0;
            if (want_read) lines_checked = lines_checked + 1;
        end
        // Let the last line finish, then report.
        repeat (300) @(posedge clk);
        if (words_seen != expected_words) begin
            $display("ERROR last line: got %0d words, want %0d", words_seen, expected_words);
            errors = errors + 1;
        end
        $display("writes %0d, lines checked %0d, words checked %0d, SDRAM rule errors %0d",
                 writes_done, lines_checked, words_checked, model.errors);
        $display("model counted reads %0d, writes %0d, refreshes %0d",
                 model.reads, model.writes, model.refreshes);
        $display("write rate under this mix: %0d words/s",
                 $rtoi(writes_done / ($realtime * 1.0e-9)));
        $display("burst words checked %0d, bursts on an open row %0d, bursts that opened a row %0d",
                 burst_words_checked, burst_hits, burst_misses);
        if (lines_checked < 10 || words_checked != lines_checked * 85
                || burst_hits < 10 || burst_misses < 10 || burst_words_left != 0) begin
            $display("ERROR too little was checked");
            errors = errors + 1;
        end
        if (errors == 0 && model.errors == 0)
            $display("PASS: sdram_ctrl_tb seed %0d", seed);
        else
            $display("FAIL: sdram_ctrl_tb seed %0d, %0d data errors, %0d rule errors", seed, errors, model.errors);
        $finish;
    end

    // Compare every word read with the shadow copy.
    always @(posedge clk) begin
        if (rd_valid) begin
            if (rd_data !== shadow[line_index + words_seen]) begin
                if (errors < 20)
                    $display("ERROR at %0t: word %0d read %h, want %h", $realtime, words_seen,
                             rd_data, shadow[line_index + words_seen]);
                errors = errors + 1;
            end
            words_seen = words_seen + 1;
            words_checked = words_checked + 1;
        end
    end

    initial begin
        #2000000000;
        $display("FAIL: sdram_ctrl_tb timed out");
        $finish;
    end

endmodule
