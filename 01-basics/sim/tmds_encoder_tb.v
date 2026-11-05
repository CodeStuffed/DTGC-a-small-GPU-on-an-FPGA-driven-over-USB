// Self-checking testbench for tmds_encoder.v. Decodes every output word back to the input,
// and checks that the line stays DC balanced (ones and zeros stay roughly equal).
`timescale 1ns / 1ps

module tmds_encoder_tb;

    reg        clk = 1'b0;
    reg        rst = 1'b1;
    reg        de = 1'b0;
    reg  [1:0] ctrl = 2'b00;
    reg  [7:0] data = 8'd0;
    wire [9:0] tmds;
    integer    errors = 0;
    integer    i, n, ones, running = 0, worst = 0;
    localparam LATENCY = 4;
    reg  [7:0] sent_data [0:LATENCY - 1];
    reg  [LATENCY - 1:0] sent_valid = 0;

    tmds_encoder dut (.clk(clk), .rst(rst), .de(de), .ctrl(ctrl), .data(data), .tmds(tmds));

    always #5 clk = ~clk;

    // The standard DVI decoder.
    function [7:0] decode(input [9:0] w);
        reg [7:0] d;
        integer k;
        begin
            d = w[9] ? ~w[7:0] : w[7:0];
            decode[0] = d[0];
            for (k = 1; k < 8; k = k + 1)
                decode[k] = w[8] ? (d[k] ^ d[k-1]) : ~(d[k] ^ d[k-1]);
        end
    endfunction

    task send_and_check(input [7:0] value);
        begin
            @(negedge clk);
            de = 1'b1;
            data = value;
            for (i = LATENCY - 1; i > 0; i = i - 1) sent_data[i] = sent_data[i - 1];
            sent_data[0] = value;
            sent_valid = {sent_valid[LATENCY - 2:0], 1'b1};
            @(posedge clk);
            #1;
            if (sent_valid[LATENCY - 1]) begin
                if (decode(tmds) !== sent_data[LATENCY - 1]) begin
                    $display("ERROR t=%0t sent=%h tmds=%b decoded=%h", $time, sent_data[LATENCY - 1], tmds, decode(tmds));
                    errors = errors + 1;
                end
                ones = 0;
                for (i = 0; i < 10; i = i + 1)
                    ones = ones + tmds[i];
                running = running + 2 * ones - 10;
                if (running > worst) worst = running;
                if (-running > worst) worst = -running;
            end
        end
    endtask

    task check_ctrl(input [1:0] value, input [9:0] want);
        begin
            @(negedge clk);
            de = 1'b0;
            ctrl = value;
            repeat (LATENCY) @(posedge clk);
            #1;
            if (tmds !== want) begin
                $display("ERROR ctrl=%b tmds=%b want=%b", value, tmds, want);
                errors = errors + 1;
            end
        end
    endtask

    initial begin
        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 1'b0;

        // Control tokens from the DVI specification.
        check_ctrl(2'b00, 10'b1101010100);
        check_ctrl(2'b01, 10'b0010101011);
        check_ctrl(2'b10, 10'b0101010100);
        check_ctrl(2'b11, 10'b1010101011);

        // Every value, in order, then many random values.
        running = 0;
        for (n = 0; n < 256; n = n + 1)
            send_and_check(n[7:0]);
        for (n = 0; n < 200000; n = n + 1)
            send_and_check($random);

        // Worst case for balance: long runs of one value.
        for (n = 0; n < 1000; n = n + 1) send_and_check(8'h00);
        for (n = 0; n < 1000; n = n + 1) send_and_check(8'hFF);
        for (n = 0; n < 1000; n = n + 1) send_and_check(8'h55);

        // Balance stays bounded instead of drifting away.
        if (worst > 40) begin
            $display("ERROR running disparity reached %0d", worst);
            errors = errors + 1;
        end
        $display("worst running disparity: %0d bits", worst);

        if (errors == 0)
            $display("PASS: tmds_encoder_tb");
        else
            $display("FAIL: tmds_encoder_tb, %0d errors", errors);
        $finish;
    end

endmodule
