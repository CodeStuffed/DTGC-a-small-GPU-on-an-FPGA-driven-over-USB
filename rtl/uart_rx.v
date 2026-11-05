// UART receiver: 8 data bits, no parity, 1 stop bit. The bit time comes from a phase accumulator
// because 25.2 MHz does not divide evenly into common fast baud rates.
// PHASE_INC = baud * 65536 / clock. Default 7802 is 3 Mbaud at 25.2 MHz; the real maximum baud rate
// of the Tang's USB bridge is not known yet (docs/verify.md).
`timescale 1ns / 1ps

module uart_rx #(
    parameter PHASE_INC = 7802
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       rx,
    output reg        valid,
    output reg  [7:0] data,
    output reg        framing_error  // sticky: a stop bit was low
);

    reg [1:0]  rx_sync;
    reg [16:0] phase;
    reg [3:0]  bit_index;   // 0 = start bit, 1-8 = data, 9 = stop
    reg        busy;

    always @(posedge clk) begin
        rx_sync <= {rx_sync[0], rx};
        valid   <= 1'b0;
        if (rst) begin
            rx_sync       <= 2'b11;
            busy          <= 1'b0;
            framing_error <= 1'b0;
        end else if (!busy) begin
            if (!rx_sync[1]) begin
                busy      <= 1'b1;
                bit_index <= 4'd0;
                phase     <= 17'h08000;  // half a bit, so samples land mid-bit
            end
        end else begin
            phase <= {1'b0, phase[15:0]} + PHASE_INC;
            if (phase[16]) begin
                bit_index <= bit_index + 1'b1;
                if (bit_index == 4'd0) begin
                    if (rx_sync[1]) busy <= 1'b0;   // glitch, not a start bit
                end else if (bit_index == 4'd9) begin
                    busy <= 1'b0;
                    if (rx_sync[1]) valid <= 1'b1;
                    else framing_error <= 1'b1;
                end else begin
                    data <= {rx_sync[1], data[7:1]};
                end
            end
        end
    end

endmodule
