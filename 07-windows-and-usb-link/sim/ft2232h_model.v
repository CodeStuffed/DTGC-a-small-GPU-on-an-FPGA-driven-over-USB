// Behaviour of the FT2232H in synchronous FIFO mode, as far as we understand it, with rule checks.
// It is written from FTDI's description, so passing against it does not prove the real chip agrees.
// OUT_DELAY is the chip's clock-to-output time. FTDI AN_130 as quoted gives 7.15 ns at most: VERIFY.
`timescale 1ns / 1ps

module ft2232h_model #(
    parameter OUT_DELAY = 7.15,
    parameter QUEUE_BITS = 16
) (
    input  wire       clk,
    output reg        rxf_n,
    output reg        txe_n,
    input  wire       oe_n,
    input  wire       rd_n,
    input  wire       wr_n,
    input  wire [7:0] d_from_fpga,
    input  wire       d_oe_fpga,
    output wire [7:0] d_to_fpga
);

    integer stall_rx_percent = 0, stall_tx_percent = 0, seed = 1;
    integer errors = 0;
    integer rx_head = 0, rx_tail = 0;          // PC to FPGA
    integer tx_count = 0;                      // FPGA to PC
    reg [7:0] rx_queue [0:(1 << QUEUE_BITS) - 1];
    reg [7:0] tx_queue [0:(1 << QUEUE_BITS) - 1];
    reg       oe_seen = 1'b0, rx_stalled = 1'b0, tx_stalled = 1'b0;

    initial begin
        rxf_n = 1'b1;
        txe_n = 1'b1;
    end

    task pc_send(input [7:0] value);
        begin
            rx_queue[rx_tail] = value;
            rx_tail = rx_tail + 1;
        end
    endtask

    // The chip drives the pins whenever OE# is low.
    assign #(OUT_DELAY) d_to_fpga = oe_n ? 8'hxx : rx_queue[rx_head];

    task fail(input [8*40-1:0] why);
        begin
            errors = errors + 1;
            if (errors <= 10) $display("FT MODEL ERROR at %0t: %0s", $time, why);
        end
    endtask

    always @(posedge clk) begin
        // Rules, checked on what the chip sees at this edge.
        if (!oe_n && d_oe_fpga) fail("both sides drive the data pins");
        if (!rd_n && !oe_seen) fail("RD# low without OE# low a clock before");
        if (!rd_n && !wr_n) fail("RD# and WR# low together");
        if (!wr_n && !oe_n) fail("WR# low while OE# low");
        if (!wr_n && !d_oe_fpga) fail("WR# low with data pins not driven");
        if (!wr_n && ^d_from_fpga === 1'bx) fail("writing unknown data");

        if (!rd_n && !rxf_n && !oe_n) rx_head = rx_head + 1;
        if (!wr_n && !txe_n) begin
            tx_queue[tx_count] = d_from_fpga;
            tx_count = tx_count + 1;
        end
        oe_seen = !oe_n;

        rx_stalled = ($unsigned($random(seed)) % 100) < stall_rx_percent;
        tx_stalled = ($unsigned($random(seed)) % 100) < stall_tx_percent;
        rxf_n <= #(OUT_DELAY) (rx_head == rx_tail) || rx_stalled;
        txe_n <= #(OUT_DELAY) tx_stalled;
    end

endmodule
