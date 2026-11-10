// Byte FIFO between two unrelated clocks. Pointers cross in Gray code, where only one bit changes per
// step, so a pointer caught mid-change reads as either its old or its new value and never as nonsense.
// The output shows the oldest byte while rd_valid is high; pulse rd_pop to take it.
// Writing while wr_full is high is ignored. Each side has its own reset, and both start from zero.
`timescale 1ns / 1ps

module async_fifo #(
    parameter ADDR_BITS = 4,
    parameter SPARE = 4
) (
    input  wire       wr_clk,
    input  wire       wr_rst,
    input  wire       wr_en,
    input  wire [7:0] wr_data,
    output wire       wr_full,
    output wire       wr_nearly_full,  // SPARE places or fewer are left, as far as this side knows

    input  wire       rd_clk,
    input  wire       rd_rst,
    output reg        rd_valid,
    output reg  [7:0] rd_data,
    input  wire       rd_pop
);

    reg [7:0] mem [0:(1 << ADDR_BITS) - 1];

    // Starting values matter: one side's clock may not be running while the other's reset ends.
    reg [ADDR_BITS:0] wr_bin = 0, wr_gray = 0, rd_bin = 0, rd_gray = 0;
    reg [ADDR_BITS:0] rd_gray_sync1 = 0, rd_gray_sync2 = 0;   // in wr_clk
    reg [ADDR_BITS:0] wr_gray_sync1 = 0, wr_gray_sync2 = 0;   // in rd_clk
    initial rd_valid = 1'b0;

    wire [ADDR_BITS:0] wr_bin_next = wr_bin + 1'b1;
    wire [ADDR_BITS:0] rd_bin_next = rd_bin + 1'b1;

    // Full when the write pointer has gone once round further than the read pointer: in Gray code,
    // that is the top two bits different and the rest the same.
    assign wr_full = wr_gray == {~rd_gray_sync2[ADDR_BITS:ADDR_BITS - 1], rd_gray_sync2[ADDR_BITS - 2:0]};

    // The read pointer seen here is a little old, which can only make the FIFO look fuller than it is.
    function [ADDR_BITS:0] gray_to_binary(input [ADDR_BITS:0] gray);
        integer i;
        begin
            gray_to_binary[ADDR_BITS] = gray[ADDR_BITS];
            for (i = ADDR_BITS - 1; i >= 0; i = i - 1)
                gray_to_binary[i] = gray_to_binary[i + 1] ^ gray[i];
        end
    endfunction

    wire [ADDR_BITS:0] wr_used = wr_bin - gray_to_binary(rd_gray_sync2);
    assign wr_nearly_full = wr_used >= (1 << ADDR_BITS) - SPARE;

    always @(posedge wr_clk) begin
        if (wr_en && !wr_full) mem[wr_bin[ADDR_BITS - 1:0]] <= wr_data;
        if (wr_rst) begin
            wr_bin  <= 0;
            wr_gray <= 0;
            rd_gray_sync1 <= 0;
            rd_gray_sync2 <= 0;
        end else begin
            rd_gray_sync1 <= rd_gray;
            rd_gray_sync2 <= rd_gray_sync1;
            if (wr_en && !wr_full) begin
                wr_bin  <= wr_bin_next;
                wr_gray <= wr_bin_next ^ (wr_bin_next >> 1);
            end
        end
    end

    wire empty = rd_gray == wr_gray_sync2;
    wire fetch = !empty && (!rd_valid || rd_pop);

    always @(posedge rd_clk) begin
        if (fetch) rd_data <= mem[rd_bin[ADDR_BITS - 1:0]];
        if (rd_rst) begin
            rd_bin   <= 0;
            rd_gray  <= 0;
            rd_valid <= 1'b0;
            wr_gray_sync1 <= 0;
            wr_gray_sync2 <= 0;
        end else begin
            wr_gray_sync1 <= wr_gray;
            wr_gray_sync2 <= wr_gray_sync1;
            if (fetch) begin
                rd_bin   <= rd_bin_next;
                rd_gray  <= rd_bin_next ^ (rd_bin_next >> 1);
                rd_valid <= 1'b1;
            end else if (rd_pop) begin
                rd_valid <= 1'b0;
            end
        end
    end

endmodule
