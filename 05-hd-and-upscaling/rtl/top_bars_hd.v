// High resolution test: eight colour bars and no memory, to find what the HDMI output can reach.
// The default is 1920x1080 @ 30 Hz, a 74.25 MHz pixel clock, from the 27 MHz board clock:
// 27 x 55 / 4 = 371.25 MHz serial clock, divided by 5. 1280x720 @ 60 Hz uses the same clocks.
// VERIFY on hardware: PLL limits against Gowin UG286, and that the monitor accepts this mode.
`timescale 1ns / 1ps

module top_bars_hd #(
    parameter IDIV_SEL  = 3,
    parameter FBDIV_SEL = 54,
    parameter ODIV_SEL  = 2,
    parameter H_VISIBLE = 1920,
    parameter H_FRONT   = 88,
    parameter H_SYNC    = 44,
    parameter H_BACK    = 148,
    parameter V_VISIBLE = 1080,
    parameter V_FRONT   = 4,
    parameter V_SYNC    = 5,
    parameter V_BACK    = 36
) (
    input  wire       clk,         // 27 MHz board clock
    output wire       tmds_clk_p,
    output wire       tmds_clk_n,
    output wire [2:0] tmds_d_p,
    output wire [2:0] tmds_d_n
);

    wire clk_serial, clk_pixel, locked;

    video_clocks #(.IDIV_SEL(IDIV_SEL), .FBDIV_SEL(FBDIV_SEL), .ODIV_SEL(ODIV_SEL)) clocks (
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

    wire [11:0] x, y;
    wire        hsync, vsync, visible;

    video_timing #(
        .H_VISIBLE(H_VISIBLE), .H_FRONT(H_FRONT), .H_SYNC(H_SYNC), .H_BACK(H_BACK),
        .V_VISIBLE(V_VISIBLE), .V_FRONT(V_FRONT), .V_SYNC(V_SYNC), .V_BACK(V_BACK),
        .BITS(12), .SYNC_HIGH(1)
    ) timing (
        .clk(clk_pixel),
        .rst(rst),
        .x(x),
        .y(y),
        .hsync(hsync),
        .vsync(vsync),
        .visible(visible),
        .frame_start()
    );

    // A counter that restarts every bar saves a divider at this clock speed.
    localparam BAR_WIDTH = H_VISIBLE / 8;
    reg [11:0] bar_x = 12'd0;
    reg [2:0]  bar = 3'd0;
    always @(posedge clk_pixel) begin
        if (!visible) begin
            bar_x <= 12'd0;
            bar   <= 3'd0;
        end else if (bar_x == BAR_WIDTH - 1) begin
            bar_x <= 12'd0;
            bar   <= bar + 1'b1;
        end else begin
            bar_x <= bar_x + 1'b1;
        end
    end

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
