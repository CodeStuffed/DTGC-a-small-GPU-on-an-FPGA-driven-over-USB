// The FT2232H link as the GPU sees it: bytes in and bytes out on the GPU's clock.
// The chip's clock only runs after the PC software has switched the chip to synchronous FIFO mode, so
// the GPU side must not depend on it. With no clock, no bytes arrive and replies simply wait.
`timescale 1ns / 1ps

module ft_link #(
    parameter RX_ADDR_BITS = 8,
    parameter TX_ADDR_BITS = 4
) (
    input  wire       clk,            // GPU clock
    input  wire       rst,

    output wire       rx_valid,       // one byte per clock while rx_ready is high
    output wire [7:0] rx_data,
    input  wire       rx_ready,

    input  wire       tx_valid,
    input  wire [7:0] tx_data,
    output wire       tx_ready,

    input  wire       ft_clk,
    input  wire       ft_rxf_n,
    input  wire       ft_txe_n,
    output wire       ft_oe_n,
    output wire       ft_rd_n,
    output wire       ft_wr_n,
    input  wire [7:0] ft_d_in,
    output wire [7:0] ft_d_out,
    output wire       ft_d_oe
);

    // Reset starts at once whatever the chip's clock is doing, and ends on that clock.
    reg [2:0] ft_rst_shift = 3'b111;
    always @(posedge ft_clk or posedge rst) begin
        if (rst) ft_rst_shift <= 3'b111;
        else     ft_rst_shift <= {ft_rst_shift[1:0], 1'b0};
    end
    wire ft_rst = ft_rst_shift[2];

    wire       bus_rx_valid, rx_nearly_full, bus_tx_valid, bus_tx_pop, tx_full, rx_out_valid;
    wire [7:0] bus_rx_data, bus_tx_data;

    ft_bus bus (
        .clk(ft_clk), .rst(ft_rst),
        .ft_rxf_n(ft_rxf_n), .ft_txe_n(ft_txe_n), .ft_oe_n(ft_oe_n), .ft_rd_n(ft_rd_n), .ft_wr_n(ft_wr_n),
        .ft_d_in(ft_d_in), .ft_d_out(ft_d_out), .ft_d_oe(ft_d_oe),
        .rx_valid(bus_rx_valid), .rx_data(bus_rx_data), .rx_room(!rx_nearly_full),
        .tx_valid(bus_tx_valid), .tx_data(bus_tx_data), .tx_pop(bus_tx_pop)
    );

    // After reads stop, up to 2 bytes are still on their way, so 4 spare places are plenty.
    async_fifo #(.ADDR_BITS(RX_ADDR_BITS), .SPARE(4)) rx_fifo (
        .wr_clk(ft_clk), .wr_rst(ft_rst), .wr_en(bus_rx_valid), .wr_data(bus_rx_data),
        .wr_full(), .wr_nearly_full(rx_nearly_full),
        .rd_clk(clk), .rd_rst(rst), .rd_valid(rx_out_valid), .rd_data(rx_data), .rd_pop(rx_valid)
    );

    assign rx_valid = rx_out_valid && rx_ready;

    async_fifo #(.ADDR_BITS(TX_ADDR_BITS)) tx_fifo (
        .wr_clk(clk), .wr_rst(rst), .wr_en(tx_valid), .wr_data(tx_data),
        .wr_full(tx_full), .wr_nearly_full(),
        .rd_clk(ft_clk), .rd_rst(ft_rst), .rd_valid(bus_tx_valid), .rd_data(bus_tx_data), .rd_pop(bus_tx_pop)
    );

    assign tx_ready = !tx_full;

endmodule
