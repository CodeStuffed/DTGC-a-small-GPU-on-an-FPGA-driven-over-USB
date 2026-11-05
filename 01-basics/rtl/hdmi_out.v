// DVI output stage for 24-bit RGB. HDMI monitors accept DVI signalling (video only, no audio).
// Gowin primitives are needed here, because plain logic cannot drive these pins fast enough:
//   OSER10     turns each 10-bit word into a serial stream, clocked by the 5x clock
//   TLVDS_OBUF drives one true differential output pair
`timescale 1ns / 1ps

module hdmi_out (
    input  wire       clk_pixel,
    input  wire       clk_serial,  // 5 x clk_pixel; OSER10 uses both edges, giving 10 bits per pixel
    input  wire       rst,         // active high
    input  wire       hsync,
    input  wire       vsync,
    input  wire       de,
    input  wire [7:0] red,
    input  wire [7:0] green,
    input  wire [7:0] blue,
    output wire       tmds_clk_p,
    output wire       tmds_clk_n,
    output wire [2:0] tmds_d_p,
    output wire [2:0] tmds_d_n
);

    wire [9:0] word [2:0];
    wire [2:0] serial;

    // DVI sends hsync and vsync as the control bits of the blue lane only.
    tmds_encoder enc_blue  (.clk(clk_pixel), .rst(rst), .de(de), .ctrl({vsync, hsync}), .data(blue),  .tmds(word[0]));
    tmds_encoder enc_green (.clk(clk_pixel), .rst(rst), .de(de), .ctrl(2'b00),          .data(green), .tmds(word[1]));
    tmds_encoder enc_red   (.clk(clk_pixel), .rst(rst), .de(de), .ctrl(2'b00),          .data(red),   .tmds(word[2]));

    genvar lane;
    generate
        for (lane = 0; lane < 3; lane = lane + 1) begin : gen_lane
            // D0 is sent first, which matches DVI's least-significant-bit-first order.
            OSER10 serializer (
                .Q(serial[lane]),
                .D0(word[lane][0]), .D1(word[lane][1]), .D2(word[lane][2]), .D3(word[lane][3]),
                .D4(word[lane][4]), .D5(word[lane][5]), .D6(word[lane][6]), .D7(word[lane][7]),
                .D8(word[lane][8]), .D9(word[lane][9]),
                .PCLK(clk_pixel),
                .FCLK(clk_serial),
                .RESET(rst)
            );
            TLVDS_OBUF driver (.I(serial[lane]), .O(tmds_d_p[lane]), .OB(tmds_d_n[lane]));
        end
    endgenerate

    // The pixel clock itself is sent on the fourth pair, as in Apicula's DVI example.
    TLVDS_OBUF clock_driver (.I(clk_pixel), .O(tmds_clk_p), .OB(tmds_clk_n));

endmodule
