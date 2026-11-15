// Only for measuring rtl/shade_pipe.v on its own: a chain of registers feeds it from one pin and its result goes out to one,
// so a place-and-route run sees real paths without 190 pins. Usage: see docs/architecture-1080p30.md.
`timescale 1ns / 1ps

module shade_pipe_wrap (
    input  wire clk,
    input  wire data_in,
    output reg  data_out
);
    reg [186:0] chain = 0;
    wire        out_valid;
    wire [23:0] out;

    shade_pipe dut (
        .clk(clk), .in_valid(chain[186]),
        .normal_x(chain[185:170]), .normal_y(chain[169:154]), .normal_z(chain[153:138]),
        .light_x(chain[137:122]), .light_y(chain[121:106]), .light_z(chain[105:90]),
        .ambient(chain[89:81]), .noise_amount(chain[80:73]), .pixel_x(chain[72:65]), .pixel_y(chain[64:57]),
        .base(chain[56:33]), .dst(chain[32:9]), .alpha(chain[8:0]),
        .out_valid(out_valid), .out(out)
    );

    always @(posedge clk) begin
        chain <= {chain[185:0], data_in};
        data_out <= ^{out_valid, out};
    end
endmodule
