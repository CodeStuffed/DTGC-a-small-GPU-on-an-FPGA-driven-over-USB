// UART transmitter: 8 data bits, no parity, 1 stop bit. See uart_rx.v for PHASE_INC.
`timescale 1ns / 1ps

module uart_tx #(
    parameter PHASE_INC = 7802
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       valid,
    output wire       ready,
    input  wire [7:0] data,
    output reg        tx
);

    reg [16:0] phase;
    reg [9:0]  shift;       // stop bit, 8 data bits, start bit, sent low bit first
    reg [3:0]  bits_left;

    assign ready = bits_left == 4'd0;

    always @(posedge clk) begin
        if (rst) begin
            tx        <= 1'b1;
            bits_left <= 4'd0;
            phase     <= 17'd0;
        end else if (ready) begin
            if (valid) begin
                shift     <= {1'b1, data, 1'b0};
                bits_left <= 4'd11;  // the 11th step marks the end of the stop bit's full length
                phase     <= 17'h10000;  // start the first bit on the next clock
            end
        end else begin
            phase <= {1'b0, phase[15:0]} + PHASE_INC;
            if (phase[16]) begin
                tx        <= shift[0];
                shift     <= {1'b1, shift[9:1]};
                bits_left <= bits_left - 1'b1;
            end
        end
    end

endmodule
