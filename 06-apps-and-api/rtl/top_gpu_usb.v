// The USB-in, USB-out version over the Tang Nano 20K's USB serial link: no HDMI cable needed.
// The PC sends commands, then reads finished pictures back with READ_RECT and shows them in a window (python -m sw.dtgc view).
// The serial link is slow for this (docs/versions.md); the top_gpu_usb_ft version on the backpack is the one meant for moving pictures.
// LEDs (active low): led[0] on = a reply has been sent, led[2] on = receive buffer overflowed or a UART stop bit was bad.
`timescale 1ns / 1ps

module top_gpu_usb #(
    parameter PHASE_INC = 7802       // baud * 65536 / 25200000. 7802 is 3 Mbaud (docs/verify.md)
) (
    input  wire        clk,          // 27 MHz board clock
    input  wire        uart_rx,
    output wire        uart_tx,
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

    wire       rx_valid, framing_error, tx_valid, tx_ready, overflow;
    wire [7:0] rx_data, tx_data;

    uart_rx #(.PHASE_INC(PHASE_INC)) receiver (
        .clk(clk_pixel), .rst(rst), .rx(uart_rx), .valid(rx_valid), .data(rx_data),
        .framing_error(framing_error)
    );

    uart_tx #(.PHASE_INC(PHASE_INC)) transmitter (
        .clk(clk_pixel), .rst(rst), .valid(tx_valid), .ready(tx_ready), .data(tx_data), .tx(uart_tx)
    );

    gpu_core #(.SCANOUT(0)) core (
        .clk(clk_pixel), .rst(rst),
        .rx_valid(rx_valid), .rx_data(rx_data), .rx_used(), .rx_overflow(overflow),
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
    assign led[2] = ~(overflow | framing_error);

endmodule
