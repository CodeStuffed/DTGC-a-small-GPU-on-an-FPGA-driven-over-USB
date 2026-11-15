// The USB-in, USB-out version over the FT2232H backpack: one cable, no HDMI cable needed.
// Same as top_gpu_ft.v without the video output. The PC reads finished pictures back with READ_RECT.
// LEDs (active low): led[0] on = a reply has been sent, led[2] on = receive buffer overflowed.
`timescale 1ns / 1ps

module top_gpu_usb_ft (
    input  wire        clk,          // 27 MHz board clock
    input  wire        ft_clk,       // 60 MHz from the FT2232H, once the PC has started it
    input  wire        ft_rxf_n,
    input  wire        ft_txe_n,
    output wire        ft_oe_n,
    output wire        ft_rd_n,
    output wire        ft_wr_n,
    inout  wire [7:0]  ft_d,
    output wire [2:0]  led,

    // SDRAM inside the FPGA package. Port names and locations: docs/verify.md
    output wire        O_sdram_clk,
    output wire        O_sdram_cke,
    output wire        O_sdram_cs_n,
    output wire        O_sdram_cas_n,
    output wire        O_sdram_ras_n,
    output wire        O_sdram_wen_n,
    output wire [10:0] O_sdram_addr,
    output wire [1:0]  O_sdram_ba,
    output wire [3:0]  O_sdram_dqm,
    inout  wire [31:0] IO_sdram_dq
);

    wire clk_serial, clk_pixel, locked;

    // The same clock as the HDMI version, so the memory timing is the one already tested. The fast clock goes unused.
    video_clocks clocks (
        .clk_27(clk),
        .clk_serial(clk_serial),
        .clk_pixel(clk_pixel),
        .locked(locked)
    );

    // Hold everything in reset until the PLL has locked, then release on the pixel clock.
    reg [3:0] rst_shift = 4'hF;
    always @(posedge clk_pixel or negedge locked) begin
        if (!locked)
            rst_shift <= 4'hF;
        else
            rst_shift <= {rst_shift[2:0], 1'b0};
    end
    wire rst = rst_shift[3];

    // The SDRAM samples on the opposite edge, which gives half a cycle of margin both ways.
    assign O_sdram_clk = ~clk_pixel;

    wire [31:0] dq_out;
    wire        dq_oe;
    assign IO_sdram_dq = dq_oe ? dq_out : 32'bz;

    wire       ft_d_oe;
    wire [7:0] ft_d_out;
    assign ft_d = ft_d_oe ? ft_d_out : 8'bz;

    wire        rx_valid, tx_valid, tx_ready, overflow;
    wire [7:0]  rx_data, tx_data;
    wire [10:0] rx_used;

    // Stopping a little short of full means the USB link simply waits, so no byte is ever lost here.
    wire rx_ready = rx_used < 11'd1020;

    ft_link link (
        .clk(clk_pixel), .rst(rst),
        .rx_valid(rx_valid), .rx_data(rx_data), .rx_ready(rx_ready),
        .tx_valid(tx_valid), .tx_data(tx_data), .tx_ready(tx_ready),
        .ft_clk(ft_clk), .ft_rxf_n(ft_rxf_n), .ft_txe_n(ft_txe_n), .ft_oe_n(ft_oe_n), .ft_rd_n(ft_rd_n),
        .ft_wr_n(ft_wr_n), .ft_d_in(ft_d), .ft_d_out(ft_d_out), .ft_d_oe(ft_d_oe)
    );

    gpu_core #(.SCANOUT(0)) core (
        .clk(clk_pixel), .rst(rst),
        .rx_valid(rx_valid), .rx_data(rx_data), .rx_used(rx_used), .rx_overflow(overflow),
        .tx_valid(tx_valid), .tx_data(tx_data), .tx_ready(tx_ready),
        .hsync(), .vsync(), .de(), .red(), .green(), .blue(), .underrun(),
        .sdram_cke(O_sdram_cke), .sdram_cs_n(O_sdram_cs_n), .sdram_ras_n(O_sdram_ras_n),
        .sdram_cas_n(O_sdram_cas_n), .sdram_we_n(O_sdram_wen_n), .sdram_ba(O_sdram_ba),
        .sdram_addr(O_sdram_addr), .sdram_dqm(O_sdram_dqm), .sdram_dq_out(dq_out),
        .sdram_dq_oe(dq_oe), .sdram_dq_in(IO_sdram_dq)
    );

    reg replied = 1'b0;
    always @(posedge clk_pixel) if (tx_valid) replied <= 1'b1;

    assign led[0] = ~replied;
    assign led[1] = 1'b1;
    assign led[2] = ~overflow;

endmodule
