// Tiny counter used only to prove the simulation tools run (Milestone 0).
`timescale 1ns / 1ps

module counter #(
    parameter WIDTH = 4
) (
    input  wire             clk,
    input  wire             rst,   // synchronous, active high
    input  wire             en,    // count only when high
    output reg  [WIDTH-1:0] count
);

    always @(posedge clk) begin
        if (rst)
            count <= {WIDTH{1'b0}};
        else if (en)
            count <= count + 1'b1;
    end

endmodule
