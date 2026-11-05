// Byte FIFO in block RAM. The output shows the oldest byte while out_valid is high;
// pulse out_pop to take it. Bytes arriving while full are lost and set overflow (sticky).
`timescale 1ns / 1ps

module byte_fifo #(
    parameter ADDR_BITS = 10
) (
    input  wire                 clk,
    input  wire                 rst,
    input  wire                 in_valid,
    input  wire [7:0]           in_data,
    output reg                  out_valid,
    output reg  [7:0]           out_data,
    input  wire                 out_pop,
    output wire [ADDR_BITS:0]   used,
    output reg                  overflow
);

    reg [7:0]         mem [0:(1 << ADDR_BITS) - 1];
    reg [ADDR_BITS:0] write_ptr, read_ptr;

    assign used = write_ptr - read_ptr;
    wire full  = used[ADDR_BITS];
    wire empty = write_ptr == read_ptr;
    wire fetch = !empty && (!out_valid || out_pop);

    always @(posedge clk) begin
        if (in_valid && !full) mem[write_ptr[ADDR_BITS - 1:0]] <= in_data;
        if (fetch) out_data <= mem[read_ptr[ADDR_BITS - 1:0]];

        if (rst) begin
            write_ptr <= 0;
            read_ptr  <= 0;
            out_valid <= 1'b0;
            overflow  <= 1'b0;
        end else begin
            if (in_valid) begin
                if (full) overflow <= 1'b1;
                else write_ptr <= write_ptr + 1'b1;
            end
            if (fetch) begin
                read_ptr  <= read_ptr + 1'b1;
                out_valid <= 1'b1;
            end else if (out_pop) begin
                out_valid <= 1'b0;
            end
        end
    end

endmodule
