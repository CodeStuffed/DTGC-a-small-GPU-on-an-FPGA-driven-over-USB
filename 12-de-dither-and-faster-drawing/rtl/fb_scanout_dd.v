// HD scan-out with de-dither: as fb_scanout_hd.v with the edge-directed blend, except that every source pixel goes through
// dedither.v first, which smooths the GPU's dither pattern so that scaling up does not turn it into visible blocks.
// The picture on screen must match "edge_dd" in sw/dtgc/upscale.py bit for bit (sw/tests/test_upscale_rtl.py).
//
// The core's side is the same as fb_scanout_hd.v, reading one row further ahead. The video side differs like this:
// An output pixel blends a square of 4 de-dithered pixels, and each of those needs its 8 neighbours, so 4 rows by 4 columns
// of source pixels are in play: rows A, B, C and D, one above the square to one below it. Each new source column takes
// 2 clocks: rows A and B, then C and D. That needs 2 reads per clock, so the line memory and the palette are each kept
// twice, written together and read apart. 8 rows wait in each line memory: the 4 in use, the one being read, and spares.
// The last 3 columns read (prev, mid, next) feed two filters, one for the square's top row and one for its bottom row,
// and what they give for column mid becomes the square's right-hand side.
`timescale 1ns / 1ps

module fb_scanout_dd #(
    parameter SCALE = 4,               // any whole number from 2 to 12
    parameter WIDTH = 480,
    parameter HEIGHT = 270,
    parameter LINE_WORDS = 120,
    parameter CORE_LINE_START = 640,   // where in its line the core's slow timer asks for refreshes and a row
    parameter H_VISIBLE = 1920,
    parameter H_FRONT = 88,
    parameter H_SYNC = 44,
    parameter H_BACK = 148,
    parameter V_VISIBLE = 1080,
    parameter V_FRONT = 4,
    parameter V_SYNC = 5,
    parameter V_BACK = 36
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
    // Columns 0 and 1 are read just before the window opens, which is at the end of the line before when the window
    // fills the whole screen. Each read takes 2 clocks.
    localparam PRE_FIRST = (WIN_X + H_TOTAL - 4) % H_TOTAL;
    localparam PRE_FIRST_2 = (WIN_X + H_TOTAL - 3) % H_TOTAL;
    localparam PRE_SECOND = (WIN_X + H_TOTAL - 2) % H_TOTAL;
    localparam PRE_SECOND_2 = (WIN_X + H_TOTAL - 1) % H_TOTAL;
    localparam PRE_COLUMN = (WIN_X + H_TOTAL - 1) % H_TOTAL;
    localparam COLUMN_BITS = (LINE_WORDS > 128) ? 8 : 7;   // of a row's words in the line memory
    localparam TO_SHIFT = 3;           // clocks from the timing counters to a column of 4 pixels arriving
    localparam TO_FILTER = 8;          // clocks from the timing counters to the blend's inputs: 4 more for dedither.v, 1 to load
    localparam DELAY = 16;             // clocks from the timing counters to the pixel leaving
    // The first output pixel of a line or frame sits this far into source pixel -1, half a picture pixel before pixel 0.
    localparam [3:0] FIRST_SUB = (SCALE + 1) / 2;
    localparam [3:0] LAST_SUB = SCALE - 1;
    localparam ODD_PHASE = (SCALE % 2) == 0;

    // Memories ------------------------------------------------------------------------------------------------------
    // Line memory: 8 rows, twice. Written on the core's clock, read on the video clock. Becomes block RAM.
    reg [31:0] line_mem_1 [0:(8 << COLUMN_BITS) - 1];
    reg [31:0] line_mem_2 [0:(8 << COLUMN_BITS) - 1];
    reg [COLUMN_BITS+2:0] line_wr_addr;
    wire [COLUMN_BITS+2:0] line_rd_addr_1, line_rd_addr_2;
    reg [31:0] line_word_1, line_word_2;
    always @(posedge clk) if (rd_valid) begin
        line_mem_1[line_wr_addr] <= rd_data;
        line_mem_2[line_wr_addr] <= rd_data;
    end
    always @(posedge clk_video) begin
        line_word_1 <= line_mem_1[line_rd_addr_1];
        line_word_2 <= line_mem_2[line_rd_addr_2];
    end

    // Palette RAM, twice, loaded by this logic after reset as in fb_scanout.v. The default maps a pixel to RRRGGGBB.
    reg  [23:0] pal_mem_1 [0:255];
    reg  [23:0] pal_mem_2 [0:255];
    reg  [23:0] pal_q_1, pal_q_2;
    reg  [8:0]  boot_addr;
    wire        booting = !boot_addr[8];
    wire [2:0]  boot_r = boot_addr[7:5];
    wire [2:0]  boot_g = boot_addr[4:2];
    wire [1:0]  boot_b = boot_addr[1:0];
    wire [23:0] boot_rgb = {boot_r, boot_r, boot_r[2:1],
                            boot_g, boot_g, boot_g[2:1],
                            boot_b, boot_b, boot_b, boot_b};
    wire [7:0]  pal_wr_addr = booting ? boot_addr[7:0] : pal_addr;
    wire [23:0] pal_wr_data = booting ? boot_rgb : pal_data;
    wire [7:0]  pixel_1, pixel_2;
    always @(posedge clk) if (booting || pal_we) begin
        pal_mem_1[pal_wr_addr] <= pal_wr_data;
        pal_mem_2[pal_wr_addr] <= pal_wr_data;
    end
    always @(posedge clk_video) begin
        pal_q_1 <= pal_mem_1[pixel_1];
        pal_q_2 <= pal_mem_2[pixel_2];
    end

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
                line_wr_addr <= {next_row[2:0], {COLUMN_BITS{1'b0}}};
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
            // Three rows may be read at once: the first line on screen needs rows 0 and 1, and one more keeps ahead.
            if (frame_event) begin
                next_row <= 10'd0;
                allowed  <= (HEIGHT < 3) ? HEIGHT : 10'd3;
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

    // Which rows. The square's top row is row_plus_one - 1 and its bottom row is row_plus_one, each kept on the picture,
    // and row_sub is how far down the square the line is: _positions() in upscale.py. They only change between lines.
    wire [11:0] next_vy = (vy == V_TOTAL - 1) ? 12'd0 : vy + 1'b1;
    reg         in_rows;
    reg  [9:0]  row_plus_one;
    reg  [3:0]  row_sub;
    // Rows A to D are row_plus_one - 2 to row_plus_one + 1, kept on the picture.
    wire [9:0]  row_a = (row_plus_one < 2) ? 10'd0 : row_plus_one - 2'd2;
    wire [9:0]  row_b = (row_plus_one == 0) ? 10'd0 : row_plus_one - 1'b1;
    wire [9:0]  row_c = (row_plus_one >= HEIGHT) ? HEIGHT - 1 : row_plus_one;
    wire [9:0]  row_d = (row_plus_one + 1'b1 >= HEIGHT) ? HEIGHT - 1 : row_plus_one + 1'b1;

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

    // The last pixels of a line are still in the pipeline when the row counters above move on to the next line, so what
    // the pipeline uses of them is copied here once per line, just before the line's first read.
    // Normally the top filter's rows are A, B, C and the bottom filter's are B, C, D. On the first rows of the screen the
    // square's top and bottom are both row 0 (B, C, D), and on the last they are both the last row (A, B, C).
    reg  [4:0]  phase_y;
    reg         top_uses_bcd, bottom_uses_abc;
    always @(posedge clk_video) begin
        if (vx == PRE_FIRST) begin
            phase_y         <= {row_sub, 1'b0} + ODD_PHASE;
            top_uses_bcd    <= row_plus_one == 0;
            bottom_uses_abc <= row_plus_one >= HEIGHT;
        end
    end

    // Which column. column is the square's right-hand column, and column_sub how far across the square the pixel is.
    wire       pre_first_start = in_rows && vx == PRE_FIRST;
    wire       pre_first_end = in_rows && vx == PRE_FIRST_2;
    wire       pre_second_start = in_rows && vx == PRE_SECOND;
    wire       pre_second_end = in_rows && vx == PRE_SECOND_2;
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

    // A new square needs the column after its right-hand column, as that column's right-hand neighbours.
    // Rows A and B are read on the first clock of a read, C and D on the second.
    wire       new_square = window && column_sub == 4'd0;
    wire       read_ab = pre_first_start || pre_second_start || new_square;
    wire       read_cd = pre_first_end || pre_second_end || (window && column_sub == 4'd1);
    wire [9:0] last_column = WIDTH - 1;
    wire [9:0] read_column = (pre_first_start || pre_first_end) ? 10'd0 :
                             (pre_second_start || pre_second_end) ? ((WIDTH > 1) ? 10'd1 : 10'd0) :
                             (column + 1'b1 >= WIDTH) ? last_column : column + 1'b1;
    wire [9:0] read_row_1 = read_cd ? row_c : row_a;
    wire [9:0] read_row_2 = read_cd ? row_d : row_b;
    assign line_rd_addr_1 = {read_row_1[2:0], read_column[COLUMN_BITS+1:2]};
    assign line_rd_addr_2 = {read_row_2[2:0], read_column[COLUMN_BITS+1:2]};

    reg [1:0] byte_sel;
    assign pixel_1 = (byte_sel == 2'd0) ? line_word_1[7:0] :
                     (byte_sel == 2'd1) ? line_word_1[15:8] :
                     (byte_sel == 2'd2) ? line_word_1[23:16] : line_word_1[31:24];
    assign pixel_2 = (byte_sel == 2'd0) ? line_word_2[7:0] :
                     (byte_sel == 2'd1) ? line_word_2[15:8] :
                     (byte_sel == 2'd2) ? line_word_2[23:16] : line_word_2[31:24];

    // Flags that follow the reads along the pipeline. Index n is valid n clocks after the timing counters.
    wire [4:0] phase_x_now = {column_sub, 1'b0} + ODD_PHASE;
    reg  [2:1] ab_ready;
    reg  [TO_SHIFT:1] shift_flag;                  // a column of 4 pixels arrives
    reg  [TO_FILTER-1:1] load_flag, first_flag;    // a new square, and the first square of a line
    reg  [4:0] phase_x [1:TO_FILTER];
    reg  [DELAY:1] window_delay, hsync_delay, vsync_delay, de_delay;
    reg  [23:0] incoming_a, incoming_b;
    reg  [95:0] prev, mid, next;                   // 3 columns of rows {A, B, C, D}
    wire [23:0] smooth_top, smooth_bottom;
    reg  [23:0] left_top, left_bottom, right_top, right_bottom;
    integer i;

    // Past the picture's right-hand edge the square's right side is the last column again, so nothing moves along.
    wire       shift_now = pre_first_start || pre_second_start || (new_square && column < WIDTH);

    always @(posedge clk_video) begin
        byte_sel     <= read_column[1:0];
        ab_ready     <= {ab_ready[1], read_ab};
        shift_flag   <= {shift_flag[TO_SHIFT-1:1], shift_now};
        load_flag    <= {load_flag[TO_FILTER-2:1], new_square};
        first_flag   <= {first_flag[TO_FILTER-2:1], pre_second_start};
        phase_x[1]   <= phase_x_now;
        for (i = 2; i <= TO_FILTER; i = i + 1) phase_x[i] <= phase_x[i - 1];
        window_delay <= {window_delay[DELAY-1:1], window};
        hsync_delay  <= {hsync_delay[DELAY-1:1], raw_hsync};
        vsync_delay  <= {vsync_delay[DELAY-1:1], raw_vsync};
        de_delay     <= rst_video ? {DELAY{1'b0}} : {de_delay[DELAY-1:1], raw_visible};

        if (ab_ready[2]) begin
            incoming_a <= pal_q_1;
            incoming_b <= pal_q_2;
        end

        // Rows C and D come out of the palette on this same clock. Column 0 is its own left-hand neighbour, so when
        // column 1 arrives, column 0 fills both of the places behind it.
        if (shift_flag[TO_SHIFT]) begin
            next <= {incoming_a, incoming_b, pal_q_1, pal_q_2};
            mid  <= next;
            prev <= first_flag[TO_SHIFT] ? next : mid;
        end

        if (first_flag[TO_FILTER-1]) begin
            left_top     <= smooth_top;
            left_bottom  <= smooth_bottom;
            right_top    <= smooth_top;
            right_bottom <= smooth_bottom;
        end else if (load_flag[TO_FILTER-1]) begin
            left_top     <= right_top;
            left_bottom  <= right_bottom;
            right_top    <= smooth_top;
            right_bottom <= smooth_bottom;
        end
    end

    // Three rows of each column for each filter: {row above, the row, row below}.
    wire [71:0] top_prev = top_uses_bcd ? prev[71:0] : prev[95:24];
    wire [71:0] top_mid = top_uses_bcd ? mid[71:0] : mid[95:24];
    wire [71:0] top_next = top_uses_bcd ? next[71:0] : next[95:24];
    wire [71:0] bottom_prev = bottom_uses_abc ? prev[95:24] : prev[71:0];
    wire [71:0] bottom_mid = bottom_uses_abc ? mid[95:24] : mid[71:0];
    wire [71:0] bottom_next = bottom_uses_abc ? next[95:24] : next[71:0];

    dedither smooth_top_row (
        .clk(clk_video), .up_left(top_prev[71:48]), .up(top_mid[71:48]), .up_right(top_next[71:48]),
        .left(top_prev[47:24]), .centre(top_mid[47:24]), .right(top_next[47:24]),
        .down_left(top_prev[23:0]), .down(top_mid[23:0]), .down_right(top_next[23:0]), .out(smooth_top)
    );
    dedither smooth_bottom_row (
        .clk(clk_video), .up_left(bottom_prev[71:48]), .up(bottom_mid[71:48]), .up_right(bottom_next[71:48]),
        .left(bottom_prev[47:24]), .centre(bottom_mid[47:24]), .right(bottom_next[47:24]),
        .down_left(bottom_prev[23:0]), .down(bottom_mid[23:0]), .down_right(bottom_next[23:0]), .out(smooth_bottom)
    );

    wire [7:0] blend_r, blend_g, blend_b;
    upscale_edge #(.SCALE(SCALE)) filter (
        .clk(clk_video), .phase_x(phase_x[TO_FILTER]), .phase_y(phase_y), .top_left(left_top),
        .top_right(right_top), .bottom_left(left_bottom), .bottom_right(right_bottom),
        .out({blend_r, blend_g, blend_b})
    );

    assign red       = window_delay[DELAY] ? blend_r : 8'd0;
    assign green     = window_delay[DELAY] ? blend_g : 8'd0;
    assign blue      = window_delay[DELAY] ? blend_b : 8'd0;
    assign hsync_out = hsync_delay[DELAY];
    assign vsync_out = vsync_delay[DELAY];
    assign de_out    = de_delay[DELAY];

endmodule
