// Moves random bytes both ways through ft_link at the same time, against the FT2232H model.
// Every byte must arrive once, unchanged and in order, with the chip and the GPU both stalling at random.
// The chip's clock starts late and can also stop part way, as it would when the PC software starts and
// when a USB cable is pulled, because the design has to survive both.
// Options: +seed=N +bytes=N +rxstall=PERCENT +txstall=PERCENT +gpustall=PERCENT +clockgaps=N
`timescale 1ns / 1ps

module ft_link_tb;
    reg clk = 0, ft_clk = 0, rst = 1, ft_clock_on = 0;
    always #19.841 clk = ~clk;        // 25.2 MHz
    always begin
        #8.333;
        if (ft_clock_on || ft_clk) ft_clk = ~ft_clk;  // 60 MHz, stopping only when low
    end

    integer seed = 1, start_seed = 1, total = 5000, rx_stall = 0, tx_stall = 0, gpu_stall = 0, clock_gaps = 0;
    integer received = 0, sent = 0, i, errors = 0;
    reg     replies_too_late = 1'b0;

    wire       rx_valid, tx_ready;
    wire [7:0] rx_data;
    reg        rx_ready = 0, tx_valid = 0;
    reg  [7:0] tx_data = 0;

    wire       rxf_n, txe_n, oe_n, rd_n, wr_n, d_oe;
    wire [7:0] d_out, d_in;

    ft_link dut (
        .clk(clk), .rst(rst), .rx_valid(rx_valid), .rx_data(rx_data), .rx_ready(rx_ready),
        .tx_valid(tx_valid), .tx_data(tx_data), .tx_ready(tx_ready),
        .ft_clk(ft_clk), .ft_rxf_n(rxf_n), .ft_txe_n(txe_n), .ft_oe_n(oe_n), .ft_rd_n(rd_n), .ft_wr_n(wr_n),
        .ft_d_in(d_in), .ft_d_out(d_out), .ft_d_oe(d_oe)
    );

    ft2232h_model chip (
        .clk(ft_clk), .rxf_n(rxf_n), .txe_n(txe_n), .oe_n(oe_n), .rd_n(rd_n), .wr_n(wr_n),
        .d_from_fpga(d_out), .d_oe_fpga(d_oe), .d_to_fpga(d_in)
    );

    // The data each way comes from a formula of its position, so nothing has to be stored to check it.
    function [7:0] down_byte(input integer n); down_byte = (n * 37 + (n >> 8) * 11 + 5); endfunction
    function [7:0] up_byte(input integer n);   up_byte   = (n * 91 + (n >> 8) * 23 + 17); endfunction

    always @(posedge clk) begin
        if (!rst) begin
            if (rx_valid && !rx_ready) begin
                errors = errors + 1;
                if (errors <= 10) $display("FAIL: a byte came while the GPU was not ready");
            end
            // Replies must get out while the PC is still sending, because the PC waits for them.
            if (chip.tx_count == 0 && received >= total / 2 && !replies_too_late) begin
                replies_too_late = 1'b1;
                errors = errors + 1;
                $display("FAIL: half the bytes came in before any reply went out");
            end
            if (rx_valid) begin
                if (rx_data !== down_byte(received)) begin
                    errors = errors + 1;
                    if (errors <= 10) $display("byte %0d to GPU: got %02x, wanted %02x", received, rx_data, down_byte(received));
                end
                received = received + 1;
            end
            rx_ready <= ($unsigned($random(seed)) % 100) >= gpu_stall;

            if (tx_valid && tx_ready) sent = sent + 1;
            if (sent < total && (($unsigned($random(seed)) % 100) >= gpu_stall)) begin
                tx_valid <= 1'b1;
                tx_data  <= up_byte(sent);
            end else if (tx_valid && tx_ready) begin
                tx_valid <= 1'b0;
            end
        end
    end

    task check_released(input [8*20-1:0] when);
        if (oe_n !== 1'b1 || rd_n !== 1'b1 || wr_n !== 1'b1 || d_oe !== 1'b0) begin
            errors = errors + 1;
            if (errors <= 10) $display("FAIL: pins not released %0s: OE# %b RD# %b WR# %b drive %b", when, oe_n, rd_n, wr_n, d_oe);
        end
    endtask

    initial begin
        if (!$value$plusargs("seed=%d", seed)) seed = 1;
        if (!$value$plusargs("bytes=%d", total)) total = 5000;
        if (!$value$plusargs("rxstall=%d", rx_stall)) rx_stall = 0;
        if (!$value$plusargs("txstall=%d", tx_stall)) tx_stall = 0;
        if (!$value$plusargs("gpustall=%d", gpu_stall)) gpu_stall = 0;
        if (!$value$plusargs("clockgaps=%d", clock_gaps)) clock_gaps = 0;
        start_seed = seed;
        chip.seed = seed + 1000;
        chip.stall_rx_percent = rx_stall;
        chip.stall_tx_percent = tx_stall;
        for (i = 0; i < total; i = i + 1) chip.pc_send(down_byte(i));

        // Before the chip's clock exists, the FPGA must stay off its pins, reset or not.
        #1;
        check_released("at power-up");
        repeat (20) @(posedge clk);
        rst = 0;
        repeat (300) begin
            @(posedge clk);
            check_released("with no chip clock");
            if (rx_valid !== 1'b0) begin
                errors = errors + 1;
                $display("FAIL: a byte reached the GPU with no chip clock");
            end
        end
        ft_clock_on = 1;

        for (i = 0; i < clock_gaps; i = i + 1) begin
            #(($unsigned($random(seed)) % 200000) + 1000);
            ft_clock_on = 0;
            #(($unsigned($random(seed)) % 20000) + 100);
            ft_clock_on = 1;
        end

        fork : wait_or_give_up
            begin
                wait (received == total && chip.tx_count == total);
                disable wait_or_give_up;
            end
            begin
                #(total * 6000 + 2000000);
                $display("FAIL: timed out, %0d of %0d to the GPU, %0d of %0d to the PC", received, total, chip.tx_count, total);
                errors = errors + 1;
                disable wait_or_give_up;
            end
        join

        repeat (200) @(posedge clk);
        for (i = 0; i < chip.tx_count; i = i + 1)
            if (chip.tx_queue[i] !== up_byte(i)) begin
                errors = errors + 1;
                if (errors <= 10) $display("byte %0d to PC: got %02x, wanted %02x", i, chip.tx_queue[i], up_byte(i));
            end
        if (received != total || chip.tx_count != total) begin
            errors = errors + 1;
            $display("counts: %0d to the GPU, %0d to the PC, wanted %0d", received, chip.tx_count, total);
        end
        if (errors == 0 && chip.errors == 0)
            $display("PASS: ft_link_tb seed %0d rx %0d%% tx %0d%% gpu %0d%% gaps %0d, %0d bytes each way", start_seed, rx_stall, tx_stall, gpu_stall, clock_gaps, total);
        else
            $display("FAIL: ft_link_tb seed %0d, %0d errors, %0d chip rule errors", start_seed, errors, chip.errors);
        $finish;
    end
endmodule
