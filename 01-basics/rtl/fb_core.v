// Framebuffer core with no vendor parts: video timing, SDRAM controller, scan-out and test pattern.
// top_framebuffer.v adds the clocks and HDMI output, and the testbench runs this module directly.
`timescale 1ns / 1ps

module fb_core (
    input  wire        clk,
    input  wire        rst,

    output wire        hsync,
    output wire        vsync,
    output wire        de,
    output wire [7:0]  red,
    output wire [7:0]  green,
    output wire [7:0]  blue,
    output wire        underrun,
    output wire        swap_done,
    output wire        front,

    output wire        sdram_cke,
    output wire        sdram_cs_n,
    output wire        sdram_ras_n,
    output wire        sdram_cas_n,
    output wire        sdram_we_n,
    output wire [1:0]  sdram_ba,
    output wire [10:0] sdram_addr,
    output wire [3:0]  sdram_dqm,
    output wire [31:0] sdram_dq_out,
    output wire        sdram_dq_oe,
    input  wire [31:0] sdram_dq_in
);

    wire [9:0] x, y;
    wire       raw_hsync, raw_vsync, visible;

    video_timing timing (
        .clk(clk),
        .rst(rst),
        .x(x),
        .y(y),
        .hsync(raw_hsync),
        .vsync(raw_vsync),
        .visible(visible),
        .frame_start()
    );

    wire        init_done, line_req, line_read, rd_valid;
    wire [1:0]  line_bank, wr_bank;
    wire [10:0] line_row, wr_row;
    wire [31:0] rd_data, wr_data;
    wire        wr_valid, wr_ready, swap_req;
    wire [7:0]  wr_col;

    sdram_ctrl memory (
        .clk(clk),
        .rst(rst),
        .init_done(init_done),
        .line_req(line_req),
        .line_read(line_read),
        .line_bank(line_bank),
        .line_row(line_row),
        .rd_valid(rd_valid),
        .rd_data(rd_data),
        .wr_valid(wr_valid),
        .wr_ready(wr_ready),
        .wr_bank(wr_bank),
        .wr_row(wr_row),
        .wr_col(wr_col),
        .wr_data(wr_data),
        .wr_be(4'b1111),
        .rr_valid(1'b0), .rr_ready(), .rr_bank(2'd0), .rr_row(11'd0), .rr_col(8'd0), .rr_len(4'd1), .rr_done(),
        .sdram_cke(sdram_cke),
        .sdram_cs_n(sdram_cs_n),
        .sdram_ras_n(sdram_ras_n),
        .sdram_cas_n(sdram_cas_n),
        .sdram_we_n(sdram_we_n),
        .sdram_ba(sdram_ba),
        .sdram_addr(sdram_addr),
        .sdram_dqm(sdram_dqm),
        .sdram_dq_out(sdram_dq_out),
        .sdram_dq_oe(sdram_dq_oe),
        .sdram_dq_in(sdram_dq_in)
    );

    fb_scanout scanout (
        .clk(clk),
        .rst(rst),
        .mem_ready(init_done),
        .x(x),
        .y(y),
        .hsync(raw_hsync),
        .vsync(raw_vsync),
        .visible(visible),
        .swap_req(swap_req),
        .swap_done(swap_done),
        .front(front),
        .line_req(line_req),
        .line_read(line_read),
        .line_bank(line_bank),
        .line_row(line_row),
        .rd_valid(rd_valid),
        .rd_data(rd_data),
        .pal_we(1'b0),
        .pal_addr(8'd0),
        .pal_data(24'd0),
        .hsync_out(hsync),
        .vsync_out(vsync),
        .de_out(de),
        .red(red),
        .green(green),
        .blue(blue),
        .underrun(underrun)
    );

    fb_pattern pattern (
        .clk(clk),
        .rst(rst),
        .mem_ready(init_done),
        .front(front),
        .swap_req(swap_req),
        .swap_done(swap_done),
        .wr_valid(wr_valid),
        .wr_ready(wr_ready),
        .wr_bank(wr_bank),
        .wr_row(wr_row),
        .wr_col(wr_col),
        .wr_data(wr_data)
    );

endmodule
