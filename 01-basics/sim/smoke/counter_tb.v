// Self-checking testbench for counter.v. Prints PASS or FAIL and exits.
`timescale 1ns / 1ps

module counter_tb;

    reg        clk = 1'b0;
    reg        rst = 1'b1;
    reg        en  = 1'b0;
    wire [3:0] count;
    integer    errors = 0;
    integer    i;

    counter #(.WIDTH(4)) dut (
        .clk(clk),
        .rst(rst),
        .en(en),
        .count(count)
    );

    always #5 clk = ~clk;

    // Wait for one rising edge, then compare just before the next inputs change.
    task check(input [3:0] expected);
        begin
            @(posedge clk);
            #1;
            if (count !== expected) begin
                $display("ERROR t=%0t count=%0d expected=%0d", $time, count, expected);
                errors = errors + 1;
            end
        end
    endtask

    initial begin
        // Reset clears the counter.
        check(4'd0);
        rst = 1'b0;

        // Holds its value while en is low.
        check(4'd0);

        // Counts up and wraps from 15 to 0.
        en = 1'b1;
        for (i = 1; i <= 16; i = i + 1)
            check(i[3:0]);

        // Holds again, then reset wins over en.
        en = 1'b0;
        check(4'd0);
        en = 1'b1;
        check(4'd1);
        rst = 1'b1;
        check(4'd0);

        if (errors == 0)
            $display("PASS: counter_tb");
        else
            $display("FAIL: counter_tb, %0d errors", errors);
        $finish;
    end

endmodule
