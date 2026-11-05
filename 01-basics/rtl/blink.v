// Milestone 1: shows a binary count on the 6 LEDs, proving the toolchain and flashing.
// The count goes up every half second, so led[0] blinks once per second.
`timescale 1ns / 1ps

module blink #(
    parameter CLK_HZ = 27000000
) (
    input  wire       clk,
    output wire [5:0] led   // active low: 0 turns the LED on
);

    localparam HALF_SECOND = CLK_HZ / 2;

    // No reset input: these start values are loaded when the FPGA configures.
    reg [31:0] divider = 32'd0;
    reg [5:0]  count   = 6'd0;

    always @(posedge clk) begin
        if (divider == HALF_SECOND - 1) begin
            divider <= 32'd0;
            count   <= count + 1'b1;
        end else begin
            divider <= divider + 1'b1;
        end
    end

    assign led = ~count;

endmodule
