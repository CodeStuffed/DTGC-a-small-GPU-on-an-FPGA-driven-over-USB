// Milestone 3 top level: animated test pattern drawn into the SDRAM, shown 1:1 in a 340x340 window
// on HDMI at 640x480. LEDs (active low): led[0] on = first picture drawn, led[1] on = scan-out ran out of
// pixels (should stay off), led[2] toggles at every buffer swap.
`timescale 1ns / 1ps

module top_framebuffer (
    input  wire        clk,         // 27 MHz board clock
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

    wire       hsync, vsync, de, underrun, swap_done, front;
    wire [7:0] red, green, blue;

    fb_core core (
        .clk(clk_pixel),
        .rst(rst),
        .hsync(hsync),
        .vsync(vsync),
        .de(de),
        .red(red),
        .green(green),
        .blue(blue),
        .underrun(underrun),
        .swap_done(swap_done),
        .front(front),
        .sdram_cke(O_sdram_cke),
        .sdram_cs_n(O_sdram_cs_n),
        .sdram_ras_n(O_sdram_ras_n),
        .sdram_cas_n(O_sdram_cas_n),
        .sdram_we_n(O_sdram_wen_n),
        .sdram_ba(O_sdram_ba),
        .sdram_addr(O_sdram_addr),
        .sdram_dqm(O_sdram_dqm),
        .sdram_dq_out(dq_out),
        .sdram_dq_oe(dq_oe),
        .sdram_dq_in(IO_sdram_dq)
    );

    // SDRAM start-up has finished once the first swap has happened.
    reg init_seen = 1'b0;
    always @(posedge clk_pixel) if (swap_done) init_seen <= 1'b1;

    assign led[0] = ~init_seen;
    assign led[1] = ~underrun;
    assign led[2] = front;

    hdmi_out out (
        .clk_pixel(clk_pixel),
        .clk_serial(clk_serial),
        .rst(rst),
        .hsync(hsync),
        .vsync(vsync),
        .de(de),
        .red(red),
        .green(green),
        .blue(blue),
        .tmds_clk_p(tmds_clk_p),
        .tmds_clk_n(tmds_clk_n),
        .tmds_d_p(tmds_d_p),
        .tmds_d_n(tmds_d_n)
    );

endmodule
