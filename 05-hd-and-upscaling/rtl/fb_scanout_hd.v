// HD scan-out: shows the picture SCALE times larger, with DT-Upscale's bilinear blend, on a fast video clock.
// The GPU core and SDRAM keep their own slow clock, so all their timing stays as it was tested. The two sides share only
// the line memory, the palette and two toggle signals that say "new frame" and "the next row may be read".
// The picture on screen must match "bilinear" in sw/dtgc/upscale.py bit for bit (sw/tests/test_upscale_rtl.py).
//
// Each output pixel blends a square of 4 source pixels. Four rows wait in the line memory: the two being shown, the one
// being read, and one spare. Each new source column takes 2 reads, top then bottom, so one read port is enough at any SCALE.
// Inside each source pixel the output steps through SCALE positions (column_sub, row_sub). As a phase in units of
// 1 / (2 * SCALE) a position is 2 * sub, plus 1 when SCALE is even, which is _positions() in upscale.py.
`timescale 1ns / 1ps

module fb_scanout_hd #(
    parameter SCALE = 2,
    parameter EDGE = 0,                // 1 uses upscale_edge.v, any SCALE from 2 to 12. 0 uses the bilinear upscale_filter.v, SCALE 2 or 3.
    parameter WIDTH = 340,
    parameter HEIGHT = 340,
    parameter LINE_WORDS = 85,
    parameter CORE_LINE_START = 640,   // where in its line the core's slow timer asks for refreshes and a row
    parameter H_VISIBLE = 1280,
    parameter H_FRONT = 110,
    parameter H_SYNC = 40,
    parameter H_BACK = 220,
    parameter V_VISIBLE = 720,
    parameter V_FRONT = 5,
    parameter V_SYNC = 5,
    parameter V_BACK = 20
) (
    // The core's side
    input  wire        clk,
    input  wire        rst,
    input  wire        mem_ready,
    input  wire [9:0]  x,              // the core's slow timer, which paces refresh and row reads

    input  wire        swap_req,
    output reg         swap_done,
    output reg         front,

    output wire        line_req,
    output wire        line_read,
    output wire [1:0]  line_bank,
    output wire [10:0] line_row,
    input  wire        rd_valid,
    input  wire [31:0] rd_data,

    input  wire        pal_we,
    input  wire [7:0]  pal_addr,
    input  wire [23:0] pal_data,
    output reg         underrun,       // sticky: a row was not ready when the picture reached it

    // The video side
    input  wire        clk_video,
    input  wire        rst_video,
    output wire        hsync_out,
    output wire        vsync_out,
    output wire        de_out,
    output wire [7:0]  red,
    output wire [7:0]  green,
    output wire [7:0]  blue
);

    localparam WIN_W = WIDTH * SCALE;
    localparam WIN_H = HEIGHT * SCALE;
    localparam WIN_X = (H_VISIBLE - WIN_W) / 2;
    localparam WIN_Y = (V_VISIBLE - WIN_H) / 2;
    localparam V_TOTAL = V_VISIBLE + V_FRONT + V_SYNC + V_BACK;
    localparam H_TOTAL = H_VISIBLE + H_FRONT + H_SYNC + H_BACK;
    // Just before the window opens, which is at the end of the line before when it fills the whole screen.
    localparam PRE_TOP = (WIN_X + H_TOTAL - 8) % H_TOTAL;
    localparam PRE_BOTTOM = (WIN_X + H_TOTAL - 7) % H_TOTAL;
    localparam PRE_COLUMN = (WIN_X + H_TOTAL - 1) % H_TOTAL;
    localparam COLUMN_BITS = (LINE_WORDS > 128) ? 8 : 7;   // of a row's words in the line memory
    localparam DELAY = 13;             // clocks from the timing counters to the pixel leaving
    localparam TO_FILTER = 5;          // clocks from the timing counters to the blend's inputs
    // The first output pixel of a line or frame sits this far into source pixel -1, half a picture pixel before pixel 0.
    localparam [3:0] FIRST_SUB = (SCALE + 1) / 2;
    localparam [3:0] LAST_SUB = SCALE - 1;
    localparam ODD_PHASE = (SCALE % 2) == 0;

    // Memories ------------------------------------------------------------------------------------------------------
    // Line memory: 4 rows. Written on the core's clock, read on the video clock. Becomes block RAM.
    reg [31:0] line_mem [0:(4 << COLUMN_BITS) - 1];
    reg [COLUMN_BITS+1:0] line_wr_addr;
    wire [COLUMN_BITS+1:0] line_rd_addr;
    reg [31:0] line_word;
    always @(posedge clk) if (rd_valid) line_mem[line_wr_addr] <= rd_data;
    always @(posedge clk_video) line_word <= line_mem[line_rd_addr];

    // Palette RAM, loaded by this logic after reset as in fb_scanout.v. The default maps a pixel to RRRGGGBB.
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
    wire [7:0]  pixel;
    always @(posedge clk) if (booting || pal_we) pal_mem[booting ? boot_addr[7:0] : pal_addr] <= booting ? boot_rgb : pal_data;
    always @(posedge clk_video) pal_q <= pal_mem[pixel];

    // The core's side ------------------------------------------------------------------------------------------------
    reg        frame_toggle, advance_toggle;    // video clock
    reg [2:0]  frame_sync, advance_sync;
    wire       frame_event = frame_sync[2] != frame_sync[1];
    wire       advance_event = advance_sync[2] != advance_sync[1];

    reg [9:0]  next_row, allowed, filled;
    reg [7:0]  words_in;
    reg        swap_pending, armed;

    assign line_req  = x == CORE_LINE_START;
    assign line_read = next_row < allowed;
    assign line_bank = {1'b0, front};
    assign line_row  = {1'b0, next_row};

    always @(posedge clk) begin
        frame_sync   <= {frame_sync[1:0], frame_toggle};
        advance_sync <= {advance_sync[1:0], advance_toggle};
        swap_done    <= 1'b0;

        if (rst) begin
            boot_addr    <= 9'd0;
            front        <= 1'b0;
            swap_pending <= 1'b0;
            armed        <= 1'b0;
            underrun     <= 1'b0;
            next_row     <= 10'd0;
            allowed      <= 10'd0;
            filled       <= 10'd0;
            words_in     <= 8'd0;
            line_wr_addr <= 0;
        end else begin
            if (booting) boot_addr <= boot_addr + 1'b1;
            if (swap_req) swap_pending <= 1'b1;

            if (line_req && mem_ready && line_read) begin
                line_wr_addr <= {next_row[1:0], {COLUMN_BITS{1'b0}}};
                words_in     <= 8'd0;
                next_row     <= next_row + 1'b1;
            end else if (rd_valid) begin
                line_wr_addr <= line_wr_addr + 1'b1;
                words_in     <= words_in + 1'b1;
                if (words_in == LINE_WORDS - 1) filled <= filled + 1'b1;
            end

            if (advance_event) begin
                if (armed && filled < allowed) underrun <= 1'b1;
                if (allowed < HEIGHT) allowed <= allowed + 1'b1;
            end

            // Video has finished a frame, so this is the moment to change buffers and start reading from row 0.
            if (frame_event) begin
                next_row <= 10'd0;
                allowed  <= 10'd2;
                filled   <= 10'd0;
                armed    <= mem_ready;
                if (swap_pending) begin
                    front        <= ~front;
                    swap_pending <= 1'b0;
                    swap_done    <= 1'b1;
                end
            end
        end
    end

    // The video side -------------------------------------------------------------------------------------------------
    wire [11:0] vx, vy;
    wire        raw_hsync, raw_vsync, raw_visible;

    video_timing #(
        .H_VISIBLE(H_VISIBLE), .H_FRONT(H_FRONT), .H_SYNC(H_SYNC), .H_BACK(H_BACK),
        .V_VISIBLE(V_VISIBLE), .V_FRONT(V_FRONT), .V_SYNC(V_SYNC), .V_BACK(V_BACK),
        .BITS(12), .SYNC_HIGH(1)
    ) timing (
        .clk(clk_video), .rst(rst_video), .x(vx), .y(vy), .hsync(raw_hsync), .vsync(raw_vsync),
        .visible(raw_visible), .frame_start()
    );

    // Which rows: row -1 means the blend starts above the picture, so both rows are row 0.
    // row_plus_one and row_sub follow _positions() in upscale.py, and only change between lines.
    wire [11:0] next_vy = (vy == V_TOTAL - 1) ? 12'd0 : vy + 1'b1;
    reg         in_rows;
    reg  [9:0]  row_plus_one;
    reg  [3:0]  row_sub;
    wire [9:0]  top_row = (row_plus_one == 0) ? 10'd0 : row_plus_one - 1'b1;
    wire [9:0]  bottom_row = (row_plus_one >= HEIGHT) ? HEIGHT - 1 : row_plus_one;
    wire [4:0]  phase_y = {row_sub, 1'b0} + ODD_PHASE;
    wire [1:0]  weight_y = (SCALE == 2) ? phase_y[1:0] : phase_y[2:1];   // the bilinear filter's weight codes

    always @(posedge clk_video) begin
        if (rst_video) begin
            frame_toggle   <= 1'b0;
            advance_toggle <= 1'b0;
            in_rows        <= 1'b0;
            row_plus_one   <= 10'd0;
            row_sub        <= 4'd0;
        end else if (vx == H_VISIBLE) begin
            if (next_vy == V_VISIBLE) frame_toggle <= ~frame_toggle;
            if (next_vy == WIN_Y) begin
                in_rows      <= 1'b1;
                row_plus_one <= 10'd0;
                row_sub      <= FIRST_SUB;
            end else if (next_vy == WIN_Y + WIN_H) begin
                in_rows      <= 1'b0;
            end else if (in_rows) begin
                if (row_sub == LAST_SUB) begin
                    row_sub        <= 4'd0;
                    row_plus_one   <= row_plus_one + 1'b1;
                    advance_toggle <= ~advance_toggle;
                end else begin
                    row_sub <= row_sub + 1'b1;
                end
            end
        end
    end

    // Which column. Column 0 is read before the window opens, since the first output pixel uses it on both sides.
    wire       pre_top = in_rows && vx == PRE_TOP;
    wire       pre_bottom = in_rows && vx == PRE_BOTTOM;
    wire       window = in_rows && vx >= WIN_X && vx < WIN_X + WIN_W;
    reg  [9:0] column;
    reg  [3:0] column_sub;
    always @(posedge clk_video) begin
        if (vx == PRE_COLUMN) begin
            column     <= 10'd0;
            column_sub <= FIRST_SUB;
        end else if (window) begin
            if (column_sub == LAST_SUB) begin
                column_sub <= 4'd0;
                column     <= column + 1'b1;
            end else begin
                column_sub <= column_sub + 1'b1;
            end
        end
    end

    wire       read_top = pre_top || (window && column_sub == 4'd0);
    wire       read_bottom = pre_bottom || (window && column_sub == 4'd1);
    wire [9:0] read_column = (pre_top || pre_bottom) ? 10'd0 : (column >= WIDTH) ? WIDTH - 1 : column;
    wire [9:0] read_row = read_bottom ? bottom_row : top_row;
    assign line_rd_addr = {read_row[1:0], read_column[COLUMN_BITS+1:2]};

    reg [1:0] byte_sel;
    assign pixel = (byte_sel == 2'd0) ? line_word[7:0] :
                   (byte_sel == 2'd1) ? line_word[15:8] :
                   (byte_sel == 2'd2) ? line_word[23:16] : line_word[31:24];

    // Flags that follow the reads along the pipeline. Index n is valid n clocks after the timing counters.
    wire [4:0] phase_x_now = {column_sub, 1'b0} + ODD_PHASE;
    reg  [2:1] top_ready, bottom_ready;
    reg  [4:1] load_flag, first_flag;
    reg  [4:0] phase_x [1:TO_FILTER];
    reg  [DELAY:1] window_delay, hsync_delay, vsync_delay, de_delay;
    reg  [23:0] incoming_top, incoming_bottom, left_top, left_bottom, right_top, right_bottom;
    integer i;

    always @(posedge clk_video) begin
        byte_sel     <= read_column[1:0];
        top_ready    <= {top_ready[1], read_top};
        bottom_ready <= {bottom_ready[1], read_bottom};
        load_flag    <= {load_flag[3:1], window && column_sub == 4'd0};
        first_flag   <= {first_flag[3:1], pre_top};
        phase_x[1]   <= phase_x_now;
        for (i = 2; i <= TO_FILTER; i = i + 1) phase_x[i] <= phase_x[i - 1];
        window_delay <= {window_delay[DELAY-1:1], window};
        hsync_delay  <= {hsync_delay[DELAY-1:1], raw_hsync};
        vsync_delay  <= {vsync_delay[DELAY-1:1], raw_vsync};
        de_delay     <= rst_video ? {DELAY{1'b0}} : {de_delay[DELAY-1:1], raw_visible};

        if (top_ready[2]) incoming_top <= pal_q;
        if (bottom_ready[2]) incoming_bottom <= pal_q;

        if (first_flag[4]) begin
            left_top     <= incoming_top;
            left_bottom  <= incoming_bottom;
            right_top    <= incoming_top;
            right_bottom <= incoming_bottom;
        end else if (load_flag[4]) begin
            left_top     <= right_top;
            left_bottom  <= right_bottom;
            right_top    <= incoming_top;
            right_bottom <= incoming_bottom;
        end
    end

    // The row weight stays the same all along a line, so it can come straight from its register.
    wire [7:0] blend_r, blend_g, blend_b;
    wire [4:0] phase_x_in = phase_x[TO_FILTER];
    wire [1:0] weight_x_in = (SCALE == 2) ? phase_x_in[1:0] : phase_x_in[2:1];   // the bilinear filter's weight codes
    generate
        if (EDGE) begin : edge_directed
            upscale_edge #(.SCALE(SCALE)) filter (
                .clk(clk_video), .phase_x(phase_x_in), .phase_y(phase_y), .top_left(left_top),
                .top_right(right_top), .bottom_left(left_bottom), .bottom_right(right_bottom),
                .out({blend_r, blend_g, blend_b})
            );
        end else begin : bilinear
            upscale_filter #(.SCALE(SCALE)) filter_r (
                .clk(clk_video), .weight_x(weight_x_in), .weight_y(weight_y), .top_left(left_top[23:16]),
                .top_right(right_top[23:16]), .bottom_left(left_bottom[23:16]), .bottom_right(right_bottom[23:16]), .out(blend_r)
            );
            upscale_filter #(.SCALE(SCALE)) filter_g (
                .clk(clk_video), .weight_x(weight_x_in), .weight_y(weight_y), .top_left(left_top[15:8]),
                .top_right(right_top[15:8]), .bottom_left(left_bottom[15:8]), .bottom_right(right_bottom[15:8]), .out(blend_g)
            );
            upscale_filter #(.SCALE(SCALE)) filter_b (
                .clk(clk_video), .weight_x(weight_x_in), .weight_y(weight_y), .top_left(left_top[7:0]),
                .top_right(right_top[7:0]), .bottom_left(left_bottom[7:0]), .bottom_right(right_bottom[7:0]), .out(blend_b)
            );
        end
    endgenerate

    assign red       = window_delay[DELAY] ? blend_r : 8'd0;
    assign green     = window_delay[DELAY] ? blend_g : 8'd0;
    assign blue      = window_delay[DELAY] ? blend_b : 8'd0;
    assign hsync_out = hsync_delay[DELAY];
    assign vsync_out = vsync_delay[DELAY];
    assign de_out    = de_delay[DELAY];

endmodule
