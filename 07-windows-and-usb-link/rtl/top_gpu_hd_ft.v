// The HD version over the FT2232H backpack: top_gpu_hd.v with the fast USB link in place of the serial one.
// LEDs (active low): led[0] on = a reply has been sent, led[1] on = a row was late, led[2] on = receive buffer overflowed.
`timescale 1ns / 1ps

module top_gpu_hd_ft #(
    parameter IDIV_SEL  = 3,
    parameter FBDIV_SEL = 54,
    parameter ODIV_SEL  = 2,
    parameter SDIV_SEL  = 8,         // core clock = serial clock / this. 371.25 / 8 = 46.41 MHz
    parameter SCALE     = 2,
    parameter EDGE      = 0,         // 0 bilinear scaling, 1 edge-directed, 2 edge-directed after de-dither (fb_scanout_dd.v)
    parameter WIDTH     = 340,       // the picture drawn. 960 x 540 at SCALE 2 fills a 1080p screen.
    parameter HEIGHT    = 340,
    parameter LINE_WORDS = 85,
    parameter H_VISIBLE = 1280,
    parameter H_FRONT   = 110,
    parameter H_SYNC    = 40,
    parameter H_BACK    = 220,
    parameter V_VISIBLE = 720,
    parameter V_FRONT   = 5,
    parameter V_SYNC    = 5,
    parameter V_BACK    = 20
) (
    input  wire        clk,          // 27 MHz board clock
    input  wire        ft_clk,       // 60 MHz from the FT2232H, once the PC has started it
    input  wire        ft_rxf_n,
    input  wire        ft_txe_n,
    output wire        ft_oe_n,
    output wire        ft_rd_n,
    output wire        ft_wr_n,
    inout  wire [7:0]  ft_d,
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

    wire clk_serial, clk_video, clk_core, locked;

    video_clocks #(.IDIV_SEL(IDIV_SEL), .FBDIV_SEL(FBDIV_SEL), .ODIV_SEL(ODIV_SEL), .SDIV_SEL(SDIV_SEL)) clocks (
        .clk_27(clk),
        .clk_serial(clk_serial),
        .clk_pixel(clk_video),
        .clk_slow(clk_core),
        .locked(locked)
    );

    // Hold each side in reset until the PLL has locked, then release on its own clock.
    reg [3:0] rst_shift = 4'hF;
    always @(posedge clk_core or negedge locked) begin
        if (!locked)
            rst_shift <= 4'hF;
        else
            rst_shift <= {rst_shift[2:0], 1'b0};
    end
    wire rst = rst_shift[3];

    reg [3:0] rst_video_shift = 4'hF;
    always @(posedge clk_video or negedge locked) begin
        if (!locked)
            rst_video_shift <= 4'hF;
        else
            rst_video_shift <= {rst_video_shift[2:0], 1'b0};
    end
    wire rst_video = rst_video_shift[3];

    // The SDRAM samples on the opposite edge, which gives half a cycle of margin both ways.
    assign O_sdram_clk = ~clk_core;

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
        .clk(clk_core), .rst(rst),
        .rx_valid(rx_valid), .rx_data(rx_data), .rx_ready(rx_ready),
        .tx_valid(tx_valid), .tx_data(tx_data), .tx_ready(tx_ready),
        .ft_clk(ft_clk), .ft_rxf_n(ft_rxf_n), .ft_txe_n(ft_txe_n), .ft_oe_n(ft_oe_n), .ft_rd_n(ft_rd_n),
        .ft_wr_n(ft_wr_n), .ft_d_in(ft_d), .ft_d_out(ft_d_out), .ft_d_oe(ft_d_oe)
    );

    wire       hsync, vsync, de, underrun;
    wire [7:0] red, green, blue;

    gpu_core #(
        .SCANOUT(2), .SCALE(SCALE), .EDGE(EDGE), .WIDTH(WIDTH), .HEIGHT(HEIGHT), .LINE_WORDS(LINE_WORDS), .H_VISIBLE(H_VISIBLE), .H_FRONT(H_FRONT), .H_SYNC(H_SYNC), .H_BACK(H_BACK),
        .V_VISIBLE(V_VISIBLE), .V_FRONT(V_FRONT), .V_SYNC(V_SYNC), .V_BACK(V_BACK)
    ) core (
        .clk(clk_core), .rst(rst), .clk_video(clk_video), .rst_video(rst_video),
        .rx_valid(rx_valid), .rx_data(rx_data), .rx_used(rx_used), .rx_overflow(overflow),
        .tx_valid(tx_valid), .tx_data(tx_data), .tx_ready(tx_ready),
        .hsync(hsync), .vsync(vsync), .de(de), .red(red), .green(green), .blue(blue),
        .underrun(underrun),
        .sdram_cke(O_sdram_cke), .sdram_cs_n(O_sdram_cs_n), .sdram_ras_n(O_sdram_ras_n),
        .sdram_cas_n(O_sdram_cas_n), .sdram_we_n(O_sdram_wen_n), .sdram_ba(O_sdram_ba),
        .sdram_addr(O_sdram_addr), .sdram_dqm(O_sdram_dqm), .sdram_dq_out(dq_out),
        .sdram_dq_oe(dq_oe), .sdram_dq_in(IO_sdram_dq)
    );

    reg replied = 1'b0;
    always @(posedge clk_core) if (tx_valid) replied <= 1'b1;

    assign led[0] = ~replied;
    assign led[1] = ~underrun;
    assign led[2] = ~overflow;

    hdmi_out out (
        .clk_pixel(clk_video), .clk_serial(clk_serial), .rst(rst_video),
        .hsync(hsync), .vsync(vsync), .de(de), .red(red), .green(green), .blue(blue),
        .tmds_clk_p(tmds_clk_p), .tmds_clk_n(tmds_clk_n), .tmds_d_p(tmds_d_p), .tmds_d_n(tmds_d_n)
    );

endmodule
