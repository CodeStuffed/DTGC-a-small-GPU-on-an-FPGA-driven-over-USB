// Self-checking testbench for uart_tx.v and uart_rx.v: every byte value in a loop from one to the
// other, at several rates and with the receiver's clock slightly off, plus a bad stop bit.
`timescale 1ns / 1ps

module uart_tb;

    reg clk = 1'b0;
    reg rst = 1'b1;
    always #19.84 clk = ~clk;  // 25.2 MHz

    // PHASE_INC = baud * 65536 / 25200000
    parameter TX_INC = 7802;  // 3 Mbaud
    parameter RX_INC = 7802;

    reg        tx_valid = 1'b0;
    reg  [7:0] tx_data = 8'd0;
    wire       tx_ready, line, rx_valid, framing_error;
    wire [7:0] rx_data;
    reg        force_low = 1'b0;

    uart_tx #(.PHASE_INC(TX_INC)) transmitter (
        .clk(clk), .rst(rst), .valid(tx_valid), .ready(tx_ready), .data(tx_data), .tx(line)
    );
    uart_rx #(.PHASE_INC(RX_INC)) receiver (
        .clk(clk), .rst(rst), .rx(line & ~force_low), .valid(rx_valid), .data(rx_data),
        .framing_error(framing_error)
    );

    integer errors = 0, received = 0, i, pass;
    reg [7:0] expected [0:1023];
    integer sent = 0;

    always @(posedge clk) if (rx_valid) begin
        if (rx_data !== expected[received]) begin
            $display("ERROR byte %0d: got %h, want %h", received, rx_data, expected[received]);
            errors = errors + 1;
        end
        received = received + 1;
    end

    initial begin
        repeat (4) @(posedge clk);
        rst <= 1'b0;
        repeat (4) @(posedge clk);
        for (pass = 0; pass < 2; pass = pass + 1)
            for (i = 0; i < 256; i = i + 1) begin
                @(negedge clk);
                while (!tx_ready) @(negedge clk);
                expected[sent] = i;
                sent = sent + 1;
                tx_valid = 1'b1;
                tx_data = i;
                @(negedge clk);
                tx_valid = 1'b0;
            end
        while (!tx_ready) @(negedge clk);
        repeat (400) @(posedge clk);

        if (received !== sent) begin
            $display("ERROR received %0d of %0d bytes", received, sent);
            errors = errors + 1;
        end
        if (framing_error) begin
            $display("ERROR framing error on a clean line");
            errors = errors + 1;
        end

        // A line low through the stop bit must be reported and must not deliver a byte. Held for 10
        // bits: past the stop bit's sample, and released before the next start bit would be accepted.
        i = received;
        force_low = 1'b1;
        repeat (655360 / RX_INC) @(posedge clk);
        force_low = 1'b0;
        repeat (131072 / RX_INC * 12) @(posedge clk);
        if (!framing_error) begin
            $display("ERROR broken stop bit was not reported");
            errors = errors + 1;
        end
        if (received !== i) begin
            $display("ERROR broken byte was delivered");
            errors = errors + 1;
        end

        if (errors == 0) $display("PASS: uart_tb TX_INC %0d RX_INC %0d", TX_INC, RX_INC);
        else $display("FAIL: uart_tb TX_INC %0d RX_INC %0d, %0d errors", TX_INC, RX_INC, errors);
        $finish;
    end

endmodule
