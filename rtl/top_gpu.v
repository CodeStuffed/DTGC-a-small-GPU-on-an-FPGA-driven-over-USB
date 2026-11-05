// Milestone 4 top level: the GPU driven by the PC over the Tang Nano 20K's USB serial link.
// LEDs (active low): led[0] on = a reply has been sent, led[1] on = scan-out ran out of pixels,
// led[2] on = receive buffer overflowed or a UART stop bit was bad. The last two should stay off.
`timescale 1ns / 1ps

module top_gpu #(
    parameter PHASE_INC = 7802       // baud * 65536 / 25200000. 7802 is 3 Mbaud (docs/verify.md)
) (
    input  wire        clk,          // 27 MHz board clock
    input  wire        uart_rx,
    output wire        uart_tx,
    output wire        tmds_clk_p,
    output wire        tmds_clk_n,
    output wire [2:0]  tmds_d_p,
    output wire [2:0]  tmds_d_n,
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

    wire       hsync, vsync, de, underrun;
    wire [7:0] red, green, blue;

    gpu_core core (
        .clk(clk_pixel), .rst(rst),
        .rx_valid(rx_valid), .rx_data(rx_data), .rx_used(), .rx_overflow(overflow),
        .tx_valid(tx_valid), .tx_data(tx_data), .tx_ready(tx_ready),
        .hsync(hsync), .vsync(vsync), .de(de), .red(red), .green(green), .blue(blue),
        .underrun(underrun),
        .sdram_cke(O_sdram_cke), .sdram_cs_n(O_sdram_cs_n), .sdram_ras_n(O_sdram_ras_n),
        .sdram_cas_n(O_sdram_cas_n), .sdram_we_n(O_sdram_wen_n), .sdram_ba(O_sdram_ba),
        .sdram_addr(O_sdram_addr), .sdram_dqm(O_sdram_dqm), .sdram_dq_out(dq_out),
        .sdram_dq_oe(dq_oe), .sdram_dq_in(IO_sdram_dq)
    );

    reg replied = 1'b0;
    always @(posedge clk_pixel) if (tx_valid) replied <= 1'b1;

    assign led[0] = ~replied;
    assign led[1] = ~underrun;
    assign led[2] = ~(overflow | framing_error);

    hdmi_out out (
        .clk_pixel(clk_pixel), .clk_serial(clk_serial), .rst(rst),
        .hsync(hsync), .vsync(vsync), .de(de), .red(red), .green(green), .blue(blue),
        .tmds_clk_p(tmds_clk_p), .tmds_clk_n(tmds_clk_n), .tmds_d_p(tmds_d_p), .tmds_d_n(tmds_d_n)
    );

endmodule
