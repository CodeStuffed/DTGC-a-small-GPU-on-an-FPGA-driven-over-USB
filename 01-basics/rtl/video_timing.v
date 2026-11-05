// Video timing generator. The defaults are 640x480 @ 60 Hz with a 25.2 MHz pixel clock.
// x and y give the current pixel position; hsync and vsync are active low unless SYNC_HIGH is 1,
// as the 720p and 1080p video standards ask for. BITS must hold the largest total.
`timescale 1ns / 1ps

module video_timing #(
    parameter H_VISIBLE = 640,
    parameter H_FRONT   = 16,
    parameter H_SYNC    = 96,
    parameter H_BACK    = 48,
    parameter V_VISIBLE = 480,
    parameter V_FRONT   = 10,
    parameter V_SYNC    = 2,
    parameter V_BACK    = 33,
    parameter BITS      = 10,
    parameter SYNC_HIGH = 0
) (
    input  wire       clk,
    input  wire       rst,   // synchronous, active high
    output reg  [BITS-1:0] x,
    output reg  [BITS-1:0] y,
    output wire       hsync,
    output wire       vsync,
    output wire       visible,
    output wire       frame_start  // high for one clock at the top-left pixel
);

    localparam H_TOTAL = H_VISIBLE + H_FRONT + H_SYNC + H_BACK;
    localparam V_TOTAL = V_VISIBLE + V_FRONT + V_SYNC + V_BACK;

    always @(posedge clk) begin
        if (rst) begin
            x <= 0;
            y <= 0;
        end else if (x == H_TOTAL - 1) begin
            x <= 0;
            y <= (y == V_TOTAL - 1) ? 0 : y + 1'b1;
        end else begin
            x <= x + 1'b1;
        end
    end

    wire in_hsync = (x >= H_VISIBLE + H_FRONT) && (x < H_VISIBLE + H_FRONT + H_SYNC);
    wire in_vsync = (y >= V_VISIBLE + V_FRONT) && (y < V_VISIBLE + V_FRONT + V_SYNC);
    assign hsync = SYNC_HIGH ? in_hsync : ~in_hsync;
    assign vsync = SYNC_HIGH ? in_vsync : ~in_vsync;
    assign visible = (x < H_VISIBLE) && (y < V_VISIBLE);
    assign frame_start = (x == 0) && (y == 0);

endmodule
