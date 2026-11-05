// Self-checking testbench for blink.v. Prints PASS or FAIL and exits.
`timescale 1ns / 1ps

module blink_tb;

    // A small clock rate keeps the run short: half a "second" is 10 cycles.
    localparam CLK_HZ      = 20;
    localparam HALF_SECOND = CLK_HZ / 2;
    localparam STEPS       = 70;    // more than 64, so the count wraps

    reg        clk = 1'b0;
    wire [5:0] led;
    reg  [5:0] expected;
    integer    errors = 0;
    integer    edges;

    blink #(.CLK_HZ(CLK_HZ)) dut (
        .clk(clk),
        .led(led)
    );

    always #5 clk = ~clk;

    initial begin
        // All LEDs start off (active low, so all ones).
        #1;
        if (led !== 6'b111111) begin
            $display("ERROR t=%0t led=%b expected all off at start", $time, led);
            errors = errors + 1;
        end

        // After every clock edge the LEDs must show exactly the right count.
        for (edges = 1; edges <= STEPS * HALF_SECOND; edges = edges + 1) begin
            @(posedge clk);
            #1;
            expected = ~((edges / HALF_SECOND) % 64);
            if (led !== expected) begin
                $display("ERROR t=%0t edge=%0d led=%b expected=%b", $time, edges, led, expected);
                errors = errors + 1;
            end
        end

        if (errors == 0)
            $display("PASS: blink_tb");
        else
            $display("FAIL: blink_tb, %0d errors", errors);
        $finish;
    end

endmodule
