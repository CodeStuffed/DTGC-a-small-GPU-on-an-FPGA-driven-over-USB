// Milestone 2 top level: eight vertical color bars on HDMI at 640x480.
`timescale 1ns / 1ps

module top_colorbars (
    input  wire       clk,         // 27 MHz board clock
    output wire       tmds_clk_p,
    output wire       tmds_clk_n,
    output wire [2:0] tmds_d_p,
    output wire [2:0] tmds_d_n
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

    wire [9:0] x, y;
    wire       hsync, vsync, visible;

    video_timing timing (
        .clk(clk_pixel),
        .rst(rst),
        .x(x),
        .y(y),
        .hsync(hsync),
        .vsync(vsync),
        .visible(visible),
        .frame_start()
    );

    // Each of the 8 bars is 80 pixels wide.
    wire [2:0] bar = x / 10'd80;

    // White, yellow, cyan, green, magenta, red, blue, black.
    reg [23:0] color;
    always @* begin
        case (bar)
            3'd0: color = 24'hFFFFFF;
            3'd1: color = 24'hFFFF00;
            3'd2: color = 24'h00FFFF;
            3'd3: color = 24'h00FF00;
            3'd4: color = 24'hFF00FF;
            3'd5: color = 24'hFF0000;
            3'd6: color = 24'h0000FF;
            3'd7: color = 24'h000000;
        endcase
    end

    hdmi_out out (
        .clk_pixel(clk_pixel),
        .clk_serial(clk_serial),
        .rst(rst),
        .hsync(hsync),
        .vsync(vsync),
        .de(visible),
        .red(color[23:16]),
        .green(color[15:8]),
        .blue(color[7:0]),
        .tmds_clk_p(tmds_clk_p),
        .tmds_clk_n(tmds_clk_n),
        .tmds_d_p(tmds_d_p),
        .tmds_d_n(tmds_d_n)
    );

endmodule
