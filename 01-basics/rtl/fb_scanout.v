// Framebuffer scan-out: asks for each line during horizontal blanking, holds it in a line buffer,
// then turns 8-bit pixels into 24-bit colour through a palette while the window is on screen.
// The picture sits 1:1 in the middle of the screen, with black around it.
// Outputs are 2 clocks behind x and y, because both memories have one clock of read delay.
`timescale 1ns / 1ps

module fb_scanout #(
    parameter WIN_X = 150,     // (640 - 340) / 2
    parameter WIN_Y = 70,      // (480 - 340) / 2
    parameter WIDTH = 340,
    parameter HEIGHT = 340,
    parameter LINE_WORDS = 85,
    parameter H_VISIBLE = 640,
    parameter V_VISIBLE = 480,
    parameter V_TOTAL = 525
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        mem_ready,   // SDRAM has finished starting up

    input  wire [9:0]  x,
    input  wire [9:0]  y,
    input  wire        hsync,
    input  wire        vsync,
    input  wire        visible,

    // Double buffering: the two pictures live in SDRAM banks 0 and 1.
    input  wire        swap_req,    // pulse: show the other buffer from the next frame
    output reg         swap_done,   // pulse: the swap happened, during vertical blanking
    output reg         front,       // which buffer is on screen

    output wire        line_req,
    output wire        line_read,
    output wire [1:0]  line_bank,
    output wire [10:0] line_row,
    input  wire        rd_valid,
    input  wire [31:0] rd_data,

    // Palette write port, ignored while the default palette is loading after reset.
    input  wire        pal_we,
    input  wire [7:0]  pal_addr,
    input  wire [23:0] pal_data,

    output reg         hsync_out,
    output reg         vsync_out,
    output reg         de_out,
    output wire [7:0]  red,
    output wire [7:0]  green,
    output wire [7:0]  blue,
    output reg         underrun     // sticky: a line was not ready when the window reached it
);

    wire [9:0] next_y = (y == V_TOTAL - 1) ? 10'd0 : y + 1'b1;
    wire next_in_window = next_y >= WIN_Y && next_y < WIN_Y + HEIGHT;
    wire line_start = x == H_VISIBLE;

    // Every line asks for refreshes, and lines inside the window also ask for pixels.
    assign line_req  = line_start;
    assign line_read = next_in_window;
    assign line_bank = {1'b0, front};
    assign line_row  = next_y - WIN_Y;

    wire in_window = x >= WIN_X && x < WIN_X + WIDTH && y >= WIN_Y && y < WIN_Y + HEIGHT;
    wire [9:0] win_x = x - WIN_X;

    // Line buffer, written from SDRAM and read by the video side. Becomes block RAM.
    reg [31:0] line_mem [0:127];
    reg [6:0]  line_wr_addr;
    reg [31:0] line_word;
    always @(posedge clk) begin
        if (rd_valid) line_mem[line_wr_addr] <= rd_data;
        line_word <= line_mem[win_x[8:2]];
    end

    // Palette RAM. Loaded by this logic rather than from a RAM init file, so it needs nothing
    // special from the toolchain. The default maps a pixel to RRRGGGBB.
    reg  [23:0] pal_mem [0:255];
    reg  [23:0] pal_q;
    reg  [8:0]  boot_addr;
    wire        booting = !boot_addr[8];
    wire [2:0]  boot_r = boot_addr[7:5];
    wire [2:0]  boot_g = boot_addr[4:2];
    wire [1:0]  boot_b = boot_addr[1:0];
    wire [23:0] boot_rgb = {boot_r, boot_r, boot_r[2:1],
                            boot_g, boot_g, boot_g[2:1],
                            boot_b, boot_b, boot_b, boot_b};
    wire        pal_write = booting || pal_we;
    wire [7:0]  pal_waddr = booting ? boot_addr[7:0] : pal_addr;
    wire [23:0] pal_wdata = booting ? boot_rgb : pal_data;

    reg  [1:0]  byte_sel;
    reg         in_window_d1, in_window_d2;
    reg         hsync_d1, vsync_d1, de_d1;

    wire [7:0] pixel = (byte_sel == 2'd0) ? line_word[7:0] :
                       (byte_sel == 2'd1) ? line_word[15:8] :
                       (byte_sel == 2'd2) ? line_word[23:16] : line_word[31:24];

    always @(posedge clk) begin
        if (pal_write) pal_mem[pal_waddr] <= pal_wdata;
        pal_q <= pal_mem[pixel];
    end

    assign red   = in_window_d2 ? pal_q[23:16] : 8'd0;
    assign green = in_window_d2 ? pal_q[15:8]  : 8'd0;
    assign blue  = in_window_d2 ? pal_q[7:0]   : 8'd0;

    reg       armed;         // only report underrun for frames that began with memory ready
    reg       swap_pending;
    reg [6:0] words_in;

    always @(posedge clk) begin
        byte_sel     <= win_x[1:0];
        in_window_d1 <= in_window;
        in_window_d2 <= in_window_d1;
        hsync_d1     <= hsync;
        vsync_d1     <= vsync;
        de_d1        <= visible;
        hsync_out    <= hsync_d1;
        vsync_out    <= vsync_d1;
        de_out       <= de_d1;
        swap_done    <= 1'b0;

        if (rst) begin
            de_d1        <= 1'b0;   // no stray pixels leave the delay line after reset
            de_out       <= 1'b0;
            boot_addr    <= 9'd0;
            front        <= 1'b0;
            swap_pending <= 1'b0;
            armed        <= 1'b0;
            underrun     <= 1'b0;
            words_in     <= 7'd0;
            line_wr_addr <= 7'd0;
        end else begin
            if (booting) boot_addr <= boot_addr + 1'b1;

            if (x == 10'd0 && y == 10'd0 && mem_ready) armed <= 1'b1;

            if (line_start) begin
                line_wr_addr <= 7'd0;
                words_in     <= 7'd0;
            end else if (rd_valid) begin
                line_wr_addr <= line_wr_addr + 1'b1;
                words_in     <= words_in + 1'b1;
            end

            if (armed && x == WIN_X && y >= WIN_Y && y < WIN_Y + HEIGHT && words_in != LINE_WORDS)
                underrun <= 1'b1;

            if (swap_req) swap_pending <= 1'b1;
            if (x == 10'd0 && y == V_VISIBLE && swap_pending) begin
                front        <= ~front;
                swap_pending <= 1'b0;
                swap_done    <= 1'b1;
            end
        end
    end

endmodule
