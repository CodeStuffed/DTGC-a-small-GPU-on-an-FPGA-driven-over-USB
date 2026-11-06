// Triangle rasterizer: one unit. Reads a 37-byte TRIANGLE payload, works out the edges and planes, then
// visits every pixel in the bounding box. Rules: docs/rasterizer.md. Must match sw/dtgc/raster.py.
//
// Setup multiplies with the chip's hard multipliers, one product per clock. Build with RASTER_SERIAL_MATH defined
// to use a serial multiplier instead (one bit per clock, no multiplier blocks), in case the open-source tools'
// support for them turns out not to work on the real chip (docs/verify.md). The results are the same either way.
// The divider takes two bits per clock and skips the leading zeros of what it divides.
// The pixel loop needs adders only, and handles one pixel per clock until it needs memory. It jumps 8 pixels at a time
// over empty space at the start of a row, and colour writes go out while it carries on.
//
// This unit also owns the fast depth clear (op 1). Clearing marks every depth tile in depth_flags, and a marked tile
// is filled from the clear value when first needed, with no memory read. Op 2 writes all marked tiles out to memory,
// which DEPTH_RECT needs before it can change part of a tile.
`timescale 1ns / 1ps

module raster #(
    parameter WIDTH = 340,
    parameter HEIGHT = 340
) (
    input  wire        clk,
    input  wire        rst,

    input  wire        start,        // one clock; for op 0 the payload is in the packet buffer
    input  wire [1:0]  op,           // 0 triangle, 1 clear depth, 2 write out marked depth tiles
    input  wire [15:0] clear_value,  // with op 1
    output reg         done,         // one clock
    output reg         bad_value,    // valid with done
    output reg         busy,

    output reg  [9:0]  buf_addr,
    input  wire [7:0]  buf_q,

    input  wire [1:0]  back_bank,

    output reg         wr_valid,
    input  wire        wr_ready,
    output reg  [1:0]  wr_bank,
    output reg  [10:0] wr_row,
    output reg  [7:0]  wr_col,
    output reg  [31:0] wr_data,
    output reg  [3:0]  wr_be,

    output reg         rr_valid,
    input  wire        rr_ready,
    output reg  [1:0]  rr_bank,
    output reg  [10:0] rr_row,
    output reg  [7:0]  rr_col,
    output reg  [3:0]  rr_len,
    input  wire        rr_done,
    input  wire [31:0] rr_data
);

    localparam BANK_DEPTH = 2'd2, BANK_TEXTURE = 2'd3;
    localparam PAYLOAD_SIZE = 37;
    localparam ATTR_R = 3'd0, ATTR_Z = 3'd3, ATTR_U = 3'd4, ATTR_LAST = 3'd5;

    localparam S_IDLE = 5'd0, S_LOAD_WAIT = 5'd1, S_LOAD_TAKE = 5'd2, S_CHECK = 5'd3;
    localparam S_AREA = 5'd4, S_AREA_DONE = 5'd5, S_SWAP = 5'd6, S_BOX = 5'd7;
    localparam S_EDGE = 5'd8, S_EDGE_DONE = 5'd9;
    localparam S_ATTR = 5'd10, S_ATTR_DONE = 5'd11, S_DIV_DONE = 5'd12;
    localparam S_MUL = 5'd13, S_DIV = 5'd14;
    localparam S_PIXEL = 5'd15, S_DRAIN = 5'd16;
    localparam S_DEPTH_READ = 5'd17, S_DEPTH_WAIT = 5'd18;
    localparam S_TEX_READ = 5'd19, S_TEX_WAIT = 5'd20;
    localparam S_COLOR_FLUSH = 5'd21, S_DEPTH_FLUSH = 5'd22, S_FINISH = 5'd23;
    localparam S_FLAG_WALK = 5'd24, S_FLAG_WAIT = 5'd25, S_FLAG_TAKE = 5'd26;
    localparam S_RESOLVE_WAIT = 5'd27, S_RESOLVE_TAKE = 5'd28, S_RESOLVE_TILE = 5'd29;
    localparam TILES_PER_ROW = (WIDTH + 15) / 16, DEPTH_WORDS_PER_ROW = WIDTH / 2;
    // A picture wider than 512 pixels has more depth in a row than one SDRAM row holds, so each picture row takes two.
    localparam TWO_DEPTH_ROWS = WIDTH > 512;
    // Pixels of the last tile in a row that are on the picture.
    localparam [15:0] LAST_TILE_PIXELS = (WIDTH % 16 == 0) ? 16'hFFFF : (16'd1 << (WIDTH % 16)) - 16'd1;

    reg [4:0] state;
    reg [5:0] load_index;
    reg [3:0] load_at;               // byte within the vertex
    reg [1:0] load_vertex;

    // The payload, unpacked.
    reg [7:0]         mode;
    reg [10:0]        tex_row;
    reg [7:0]         tex_size;
    reg signed [15:0] vx [0:2];
    reg signed [15:0] vy [0:2];
    reg [15:0]        attr [0:17];   // vertex * 6 + attribute: r, g, b, z, u, v
    reg [15:0]        raw;           // a 16-bit value arriving low byte first

    wire use_depth   = mode[0];
    wire use_texture = mode[1];
    wire use_dither  = mode[2];

    wire [7:0] tex_mask = (8'd1 << tex_size[3:0]) - 1'b1;  // size 8 gives 256 - 1, all ones

    wire signed [17:0] dx1 = vx[1] - vx[0];
    wire signed [17:0] dy1 = vy[1] - vy[0];
    wire signed [17:0] dx2 = vx[2] - vx[0];
    wire signed [17:0] dy2 = vy[2] - vy[0];

    function in_range(input signed [15:0] value);
        in_range = value[15] == value[14];  // within -16384 to 16383
    endfunction

    // Bounding box in whole pixels, limited to the picture. The sign is kept for the limit test.
    wire signed [15:0] low_x  = (vx[0] < vx[1]) ? ((vx[0] < vx[2]) ? vx[0] : vx[2]) : ((vx[1] < vx[2]) ? vx[1] : vx[2]);
    wire signed [15:0] high_x = (vx[0] > vx[1]) ? ((vx[0] > vx[2]) ? vx[0] : vx[2]) : ((vx[1] > vx[2]) ? vx[1] : vx[2]);
    wire signed [15:0] low_y  = (vy[0] < vy[1]) ? ((vy[0] < vy[2]) ? vy[0] : vy[2]) : ((vy[1] < vy[2]) ? vy[1] : vy[2]);
    wire signed [15:0] high_y = (vy[0] > vy[1]) ? ((vy[0] > vy[2]) ? vy[0] : vy[2]) : ((vy[1] > vy[2]) ? vy[1] : vy[2]);
    wire signed [11:0] low_px  = low_x >>> 4;
    wire signed [11:0] high_px = high_x >>> 4;
    wire signed [11:0] low_py  = low_y >>> 4;
    wire signed [11:0] high_py = high_y >>> 4;
    wire signed [11:0] box_min_x = (low_px < 0) ? 12'sd0 : low_px;
    wire signed [11:0] box_max_x = (high_px > WIDTH - 1) ? WIDTH - 1 : high_px;
    wire signed [11:0] box_min_y = (low_py < 0) ? 12'sd0 : low_py;
    wire signed [11:0] box_max_y = (high_py > HEIGHT - 1) ? HEIGHT - 1 : high_py;

    reg [9:0] min_x, max_x, max_y;
    reg [9:0] px, py;

    function [10:0] depth_sdram_row(input [9:0] row, input second);
        depth_sdram_row = TWO_DEPTH_ROWS ? {row, second} : {1'b0, row};
    endfunction

    wire signed [17:0] start_x = {min_x, 4'd8};
    wire signed [17:0] start_y = {py, 4'd8};

    // Multiplier: a * b. In serial form, one bit of b per clock.
`ifdef RASTER_SERIAL_MATH
    localparam USE_DSP = 0;
`else
    localparam USE_DSP = 1;
`endif
    reg signed [55:0] mul_a, mul_p;
    reg signed [17:0] mul_b;
    reg [17:0]        mul_left;
    reg               mul_negative;
    reg [4:0]         return_state;
    // a is 32 bits at most when a multiplication starts: an 18-bit difference or a gradient.
    wire signed [49:0] hard_product = $signed(mul_a[31:0]) * mul_b;

    task start_multiply(input signed [55:0] a, input signed [17:0] b, input [4:0] after);
        begin
            mul_a        <= a;
            mul_b        <= b;
            mul_p        <= 56'sd0;
            mul_left     <= b[17] ? -b : b;
            mul_negative <= b[17];
            return_state <= after;
            state        <= S_MUL;
        end
    endtask

    // Divider: (|numerator| << 20) / area, two bits per clock. Each bit is one shift and one trial subtraction.
    reg [35:0] area;
    reg [55:0] div_q;
    reg [36:0] div_r;
    reg [5:0]  div_count;
    reg        div_negative;
    wire [36:0] div_shift1 = {div_r[35:0], div_q[55]};
    wire        div_fits1  = div_shift1 >= {1'b0, area};
    wire [36:0] div_rem1   = div_fits1 ? div_shift1 - {1'b0, area} : div_shift1;
    wire [36:0] div_shift2 = {div_rem1[35:0], div_q[54]};
    wire        div_fits2  = div_shift2 >= {1'b0, area};
    wire [36:0] div_rem2   = div_fits2 ? div_shift2 - {1'b0, area} : div_shift2;
    // While the remainder is zero, eight zero bits on top of the number only add eight zeros to the answer.
    wire        div_skip   = div_r == 37'd0 && div_q[55:48] == 8'd0 && div_count > 6'd8;
    wire [31:0] div_limited = (div_q >= 56'h80000000) ? 32'h7FFFFFFF : div_q[31:0];
    wire signed [31:0] div_result = div_negative ? -$signed(div_limited) : $signed(div_limited);

    // Setup progress.
    reg signed [55:0] t0;
    reg [1:0]         edge_index;
    reg               edge_part;
    reg [2:0]         attr_index;
    reg [2:0]         attr_part;

    wire [1:0] edge_b = (edge_index == 2'd2) ? 2'd0 : edge_index + 1'b1;
    wire signed [15:0] ax = vx[edge_index];
    wire signed [15:0] ay = vy[edge_index];
    wire signed [15:0] bx = vx[edge_b];
    wire signed [15:0] by = vy[edge_b];
    wire signed [17:0] edge_dx = bx - ax;
    wire signed [17:0] edge_dy = by - ay;
    wire top_left = edge_dy < 0 || (edge_dy == 0 && edge_dx > 0);

    // Edge values and their steps. Values fit in 36 bits with coordinates limited to 15 bits.
    reg signed [36:0] e [0:2];
    reg signed [36:0] e_row [0:2];
    reg signed [22:0] e_step_x [0:2];
    reg signed [22:0] e_step_y [0:2];
    wire inside = !e[0][36] && !e[1][36] && !e[2][36];

    // Planes: value, value at the start of the row, and the per-pixel steps.
    reg signed [47:0] value [0:5];
    reg signed [47:0] value_row [0:5];
    reg signed [31:0] grad_x [0:5];
    reg signed [31:0] grad_y [0:5];

    wire signed [17:0] dc1 = $signed({2'b00, attr[6 + attr_index]}) - $signed({2'b00, attr[attr_index]});
    wire signed [17:0] dc2 = $signed({2'b00, attr[12 + attr_index]}) - $signed({2'b00, attr[attr_index]});
    wire signed [47:0] c0_fixed = {16'd0, attr[attr_index], 16'd0};

    // Attributes a triangle does not use are skipped: colour when textured, u and v when not.
    function attr_needed(input [2:0] index, input textured, input depth);
        if (index == ATTR_Z)        attr_needed = depth;
        else if (index >= ATTR_U)   attr_needed = textured;
        else                        attr_needed = !textured;
    endfunction

    function [7:0] clamp8(input signed [47:0] v);
        clamp8 = v[47] ? 8'd0 : (v[46:24] != 0) ? 8'd255 : v[23:16];
    endfunction

    function [15:0] clamp16(input signed [47:0] v);
        clamp16 = v[47] ? 16'd0 : (v[46:32] != 0) ? 16'hFFFF : v[31:16];
    endfunction

    wire [7:0]  now_r = clamp8(value[0]);
    wire [7:0]  now_g = clamp8(value[1]);
    wire [7:0]  now_b = clamp8(value[2]);
    wire [15:0] now_z = clamp16(value[3]);
    wire [7:0]  now_u = clamp8(value[4]) & tex_mask;
    wire [7:0]  now_v = clamp8(value[5]) & tex_mask;

    // Ordered dither: a repeating 4 x 4 pattern added before the colour is cut down to 8 bits.
    reg [3:0] bayer;
    always @* case ({py[1:0], px[1:0]})
        4'd0:  bayer = 4'd0;
        4'd1:  bayer = 4'd8;
        4'd2:  bayer = 4'd2;
        4'd3:  bayer = 4'd10;
        4'd4:  bayer = 4'd12;
        4'd5:  bayer = 4'd4;
        4'd6:  bayer = 4'd14;
        4'd7:  bayer = 4'd6;
        4'd8:  bayer = 4'd3;
        4'd9:  bayer = 4'd11;
        4'd10: bayer = 4'd1;
        4'd11: bayer = 4'd9;
        4'd12: bayer = 4'd15;
        4'd13: bayer = 4'd7;
        4'd14: bayer = 4'd13;
        default: bayer = 4'd5;
    endcase
    // Scaling first (by 7/8, or 3/4 for blue) makes the average match the palette, and keeps white in range.
    wire [7:0] dither_r = use_dither ? now_r - (now_r >> 3) + {bayer, 1'b0} : now_r;
    wire [7:0] dither_g = use_dither ? now_g - (now_g >> 3) + {bayer, 1'b0} : now_g;
    wire [7:0] dither_b = use_dither ? now_b - (now_b >> 2) + {bayer, 2'b00} : now_b;

    // A little of each memory is held here, because neighbouring pixels share it: one word of colour
    // (4 pixels), one word of texture (4 texels), and for depth a tile of 8 words (16 pixels) read as
    // one burst. Most pixels need no memory access. Writes pile up until the pixel moves on.
    reg [31:0] color_word;
    reg [3:0]  color_be;             // bytes changed and not yet written; zero means nothing is held
    reg [9:0]  color_row;
    reg [7:0]  color_col;
    wire       color_hit = color_row == py && color_col == px[9:2];

    reg [255:0] depth_tile;          // one 16-bit depth per pixel
    reg [15:0]  depth_dirty;         // pixels changed and not yet written
    reg         depth_valid;
    reg [9:0]   depth_row;
    reg [5:0]   depth_col;           // which tile in the row
    reg [2:0]   fill_word;
    reg [3:0]   flush_word;          // 8 means every word has been offered
    // Only the words a triangle can reach are read, so a hit also needs this pixel's word to be among them.
    reg  [2:0]  depth_first, depth_last;
    wire [2:0]  read_first = px[3:1];
    wire [2:0]  read_last = (max_x[9:4] == px[9:4]) ? max_x[3:1] : 3'd7;
    wire        depth_hit = depth_valid && depth_row == py && depth_col == px[9:4]
                            && px[3:1] >= depth_first && px[3:1] <= depth_last;
    wire [15:0] stored_z = depth_tile[16 * px[3:0] +: 16];
    // The changed words not yet sent, and the first of them.
    wire [7:0] dirty_words = {|depth_dirty[15:14], |depth_dirty[13:12], |depth_dirty[11:10], |depth_dirty[9:8],
                              |depth_dirty[7:6], |depth_dirty[5:4], |depth_dirty[3:2], |depth_dirty[1:0]};
    wire [7:0] flush_left = flush_word[3] ? 8'd0 : dirty_words & (8'hFF << flush_word[2:0]);
    wire [2:0] flush_next = flush_left[0] ? 3'd0 : flush_left[1] ? 3'd1 : flush_left[2] ? 3'd2 : flush_left[3] ? 3'd3 :
                            flush_left[4] ? 3'd4 : flush_left[5] ? 3'd5 : flush_left[6] ? 3'd6 : 3'd7;
    wire [1:0] flush_dirty = depth_dirty[2 * flush_next +: 2];

    reg [31:0] tex_word;
    reg        tex_valid;
    reg [10:0] tex_held_row;
    reg [5:0]  tex_held_col;
    wire [10:0] tex_row_now = tex_row + now_v;
    wire       tex_hit = tex_valid && tex_held_row == tex_row_now && tex_held_col == now_u[7:2];
    reg [7:0] tex_byte;
    always @* case (now_u[1:0])
        2'd0: tex_byte = tex_word[7:0];
        2'd1: tex_byte = tex_word[15:8];
        2'd2: tex_byte = tex_word[23:16];
        default: tex_byte = tex_word[31:24];
    endcase
    wire [7:0] pixel_color = use_texture ? tex_byte : {dither_r[7:5], dither_g[7:5], dither_b[7:6]};

    reg row_entered;                 // this row has already had a pixel inside the triangle

    // Fast depth clear.
    reg [15:0] depth_clear_value;
    reg        clears_pending;       // some tile may still be marked
    reg [9:0]  walk_row;
    reg [TILES_PER_ROW-1:0] resolve_flags;
    reg [5:0]  resolve_tile;
    reg [3:0]  resolve_word;         // 8 means this tile is finished
    wire       resolving = state == S_RESOLVE_WAIT || state == S_RESOLVE_TAKE || state == S_RESOLVE_TILE;
    wire [9:0] flag_read_row = resolving ? walk_row : py;
    wire [TILES_PER_ROW-1:0] flag_q;
    reg        flag_write;
    reg [9:0]  flag_write_row;
    reg [TILES_PER_ROW-1:0] flag_write_value;
    wire [8:0] resolve_col = {resolve_tile, resolve_word[2:0]};

    depth_flags #(.TILES(TILES_PER_ROW), .ROWS((HEIGHT > 512) ? 1024 : 512)) flags (
        .clk(clk), .read_row(flag_read_row), .read_flags(flag_q),
        .write(flag_write), .write_row(flag_write_row), .write_flags(flag_write_value)
    );

    // Where a pixel's colour word would have to go out first, and whether the write port can take it.
    wire color_miss = color_be != 0 && !color_hit;
    wire write_free = !wr_valid || wr_ready;

    // The jump over empty space. An edge that is negative here and 8 pixels on is negative everywhere between.
    wire signed [36:0] e_jump0 = e[0] + (e_step_x[0] <<< 3);
    wire signed [36:0] e_jump1 = e[1] + (e_step_x[1] <<< 3);
    wire signed [36:0] e_jump2 = e[2] + (e_step_x[2] <<< 3);
    wire can_jump = ({1'b0, px} + 11'd8 <= {1'b0, max_x}) &&
                    ((e[0][36] && e_jump0[36]) || (e[1][36] && e_jump1[36]) || (e[2][36] && e_jump2[36]));

    reg finishing;                   // flushes return to S_DRAIN instead of S_PIXEL

    integer i;
    reg advance;
    wire last_in_row = px == max_x;

    always @(posedge clk) begin
        done <= 1'b0;
        advance = 1'b0;
        flag_write <= 1'b0;
        if (wr_valid && wr_ready) wr_valid <= 1'b0;

        if (rst) begin
            // Block RAM holds nothing useful at power-up, but marks are only read while clears_pending is set,
            // and the depth clear that sets it writes every row first.
            state    <= S_IDLE;
            clears_pending <= 1'b0;
            depth_valid <= 1'b0;
            busy     <= 1'b0;
            wr_valid <= 1'b0;
            rr_valid <= 1'b0;
            color_be <= 4'd0;
            depth_dirty <= 16'd0;
            flush_word  <= 4'd0;
        end else case (state)
            S_IDLE: if (start && op == 2'd1) begin
                busy <= 1'b1;
                bad_value <= 1'b0;
                depth_clear_value <= clear_value;
                clears_pending <= 1'b1;
                walk_row <= 10'd0;
                state <= S_FLAG_WALK;
            end else if (start && op == 2'd2) begin
                busy <= 1'b1;
                bad_value <= 1'b0;
                walk_row <= 10'd0;
                state <= clears_pending ? S_RESOLVE_WAIT : S_FINISH;
            end else if (start) begin
                busy       <= 1'b1;
                bad_value  <= 1'b0;
                depth_valid <= 1'b0;
                // Other commands may have changed memory since the last triangle.
                tex_valid   <= 1'b0;
                finishing   <= 1'b0;
                load_index <= 6'd0;
                load_at    <= 4'd0;
                load_vertex <= 2'd0;
                buf_addr   <= 10'd0;
                state      <= S_LOAD_WAIT;
            end

            // Payload: mode, texture row (2), texture size, then three vertices of 11 bytes:
            // x (2), y (2), z (2), r, g, b, u, v. The payload RAM has one clock of delay, so the address
            // runs one step ahead and a byte arrives on every clock.
            S_LOAD_WAIT: begin
                buf_addr <= buf_addr + 1'b1;
                state    <= S_LOAD_TAKE;
            end
            S_LOAD_TAKE: begin
                raw <= {buf_q, raw[15:8]};
                if (load_index == 0) mode <= buf_q;
                if (load_index == 2) tex_row <= {buf_q[2:0], raw[15:8]};
                if (load_index == 3) tex_size <= buf_q;
                if (load_index >= 4) begin
                    case (load_at)
                        4'd1: vx[load_vertex] <= {buf_q, raw[15:8]};
                        4'd3: vy[load_vertex] <= {buf_q, raw[15:8]};
                        4'd5: attr[load_vertex * 6 + 3] <= {buf_q, raw[15:8]};
                        4'd6: attr[load_vertex * 6 + 0] <= {8'd0, buf_q};
                        4'd7: attr[load_vertex * 6 + 1] <= {8'd0, buf_q};
                        4'd8: attr[load_vertex * 6 + 2] <= {8'd0, buf_q};
                        4'd9: attr[load_vertex * 6 + 4] <= {8'd0, buf_q};
                        4'd10: attr[load_vertex * 6 + 5] <= {8'd0, buf_q};
                        default: ;
                    endcase
                    if (load_at == 4'd10) begin
                        load_at     <= 4'd0;
                        load_vertex <= load_vertex + 1'b1;
                    end else begin
                        load_at <= load_at + 1'b1;
                    end
                end
                buf_addr   <= buf_addr + 1'b1;
                load_index <= load_index + 1'b1;
                if (load_index == PAYLOAD_SIZE - 1) state <= S_CHECK;
            end

            S_CHECK: begin
                if (tex_size > 8'd8 || !in_range(vx[0]) || !in_range(vx[1]) || !in_range(vx[2])
                        || !in_range(vy[0]) || !in_range(vy[1]) || !in_range(vy[2])) begin
                    bad_value <= 1'b1;
                    state     <= S_FINISH;
                end else begin
                    start_multiply(dx1, dy2, S_AREA);
                end
            end
            S_AREA: begin
                t0 <= mul_p;
                start_multiply(dx2, dy1, S_AREA_DONE);
            end
            S_AREA_DONE: begin : area_done
                reg signed [55:0] signed_area;
                signed_area = t0 - mul_p;
                if (signed_area == 0) begin
                    state <= S_FINISH;
                end else if (signed_area < 0) begin
                    area  <= -signed_area;
                    state <= S_SWAP;
                end else begin
                    area  <= signed_area;
                    state <= S_BOX;
                end
            end
            S_SWAP: begin  // keeps every triangle wound the same way, so inside is always positive
                vx[1] <= vx[2];
                vx[2] <= vx[1];
                vy[1] <= vy[2];
                vy[2] <= vy[1];
                for (i = 0; i < 6; i = i + 1) begin
                    attr[6 + i]  <= attr[12 + i];
                    attr[12 + i] <= attr[6 + i];
                end
                state <= S_BOX;
            end
            S_BOX: begin
                if (box_min_x > box_max_x || box_min_y > box_max_y) begin
                    state <= S_FINISH;
                end else begin
                    min_x      <= box_min_x[9:0];
                    max_x      <= box_max_x[9:0];
                    px         <= box_min_x[9:0];
                    py         <= box_min_y[9:0];
                    max_y      <= box_max_y[9:0];
                    edge_index <= 2'd0;
                    edge_part  <= 1'b0;
                    row_entered <= 1'b0;
                    state      <= S_EDGE;
                end
            end

            // Each edge: dx * (start_y - ay) - dy * (start_x - ax), minus one unless top or left.
            S_EDGE: start_multiply(edge_part ? edge_dy : edge_dx, edge_part ? (start_x - ax) : (start_y - ay), S_EDGE_DONE);
            S_EDGE_DONE: begin
                if (!edge_part) begin
                    t0        <= mul_p;
                    edge_part <= 1'b1;
                    state     <= S_EDGE;
                end else begin
                    e[edge_index]        <= t0 - mul_p - (top_left ? 0 : 1);
                    e_row[edge_index]    <= t0 - mul_p - (top_left ? 0 : 1);
                    e_step_x[edge_index] <= -(edge_dy * 16);
                    e_step_y[edge_index] <= edge_dx * 16;
                    edge_part            <= 1'b0;
                    if (edge_index == 2'd2) begin
                        attr_index <= 3'd0;
                        attr_part  <= 3'd0;
                        state      <= S_ATTR;
                    end else begin
                        edge_index <= edge_index + 1'b1;
                        state      <= S_EDGE;
                    end
                end
            end

            // Each plane, six steps:
            //   0, 1: grad_x = (dc1 * dy2 - dc2 * dy1 << 20) / area
            //   2, 3: grad_y = (dc2 * dx1 - dc1 * dx2 << 20) / area
            //   4, 5: start = (c0 << 16) + ((grad_x * (start_x - x0) + grad_y * (start_y - y0)) >> 4)
            S_ATTR: begin
                if (!attr_needed(attr_index, use_texture, use_depth)) begin
                    grad_x[attr_index]    <= 32'sd0;
                    grad_y[attr_index]    <= 32'sd0;
                    value[attr_index]     <= 48'sd0;
                    value_row[attr_index] <= 48'sd0;
                    if (attr_index == ATTR_LAST) begin
                        state <= S_PIXEL;
                    end else begin
                        attr_index <= attr_index + 1'b1;
                    end
                end else if (dc1 == 0 && dc2 == 0) begin
                    // The same at all three corners, which is every colour of a flat-shaded triangle. No sums to do.
                    grad_x[attr_index]    <= 32'sd0;
                    grad_y[attr_index]    <= 32'sd0;
                    value[attr_index]     <= c0_fixed;
                    value_row[attr_index] <= c0_fixed;
                    if (attr_index == ATTR_LAST) begin
                        state <= S_PIXEL;
                    end else begin
                        attr_index <= attr_index + 1'b1;
                    end
                end else begin
                    case (attr_part)
                        3'd0: start_multiply(dc1, dy2, S_ATTR_DONE);
                        3'd1: start_multiply(dc2, dy1, S_ATTR_DONE);
                        3'd2: start_multiply(dc2, dx1, S_ATTR_DONE);
                        3'd3: start_multiply(dc1, dx2, S_ATTR_DONE);
                        3'd4: start_multiply(grad_x[attr_index], start_x - vx[0], S_ATTR_DONE);
                        default: start_multiply(grad_y[attr_index], start_y - vy[0], S_ATTR_DONE);
                    endcase
                end
            end
            S_ATTR_DONE: begin : attr_done
                reg signed [55:0] difference;
                reg [55:0] magnitude;
                difference = t0 - mul_p;
                magnitude = difference[55] ? -difference : difference;
                attr_part <= attr_part + 1'b1;
                case (attr_part)
                    3'd0, 3'd2, 3'd4: begin
                        t0    <= mul_p;
                        state <= S_ATTR;
                    end
                    3'd1, 3'd3: begin
                        div_q        <= {magnitude[35:0], 20'd0};
                        div_r        <= 37'd0;
                        div_count    <= 6'd56;
                        div_negative <= difference[55];
                        state        <= S_DIV;
                    end
                    default: begin : plane_start
                        reg signed [55:0] sum;
                        reg signed [47:0] plane;
                        sum = t0 + mul_p;
                        plane = c0_fixed + (sum >>> 4);
                        value[attr_index]     <= plane;
                        value_row[attr_index] <= plane;
                        attr_part             <= 3'd0;
                        if (attr_index == ATTR_LAST) begin
                            state <= S_PIXEL;
                        end else begin
                            attr_index <= attr_index + 1'b1;
                            state      <= S_ATTR;
                        end
                    end
                endcase
            end
            S_DIV_DONE: begin
                if (attr_part == 3'd2) grad_x[attr_index] <= div_result;
                else                   grad_y[attr_index] <= div_result;
                state <= S_ATTR;
            end

            S_MUL: begin
                if (USE_DSP) begin
                    mul_p <= hard_product;
                    state <= return_state;
                end else if (mul_left == 0) begin
                    if (mul_negative) mul_p <= -mul_p;
                    state <= return_state;
                end else begin
                    if (mul_left[0]) mul_p <= mul_p + mul_a;
                    mul_a    <= mul_a << 1;
                    mul_left <= mul_left >> 1;
                end
            end

            S_DIV: begin
                if (div_skip) begin
                    div_q     <= {div_q[47:0], 8'd0};
                    div_count <= div_count - 6'd8;
                end else begin
                    div_r     <= div_rem2;
                    div_q     <= {div_q[53:0], div_fits1, div_fits2};
                    div_count <= div_count - 6'd2;
                    if (div_count == 6'd2) state <= S_DIV_DONE;
                end
            end

            // One pixel per clock, as long as the words it needs are already held here. Anything missing
            // is fetched or flushed by another state, which comes back here to try the same pixel again.
            S_PIXEL: begin
                if (!inside) begin
                    advance = 1'b1;
                end else if (use_depth && !depth_hit) begin
                    state <= (depth_dirty != 0) ? S_DEPTH_FLUSH : clears_pending ? S_FLAG_WAIT : S_DEPTH_READ;
                end else if (use_depth && now_z >= stored_z) begin
                    advance = 1'b1;
                end else if (use_texture && !tex_hit) begin
                    state <= S_TEX_READ;
                end else if (!color_miss || write_free) begin
                    // A held word for somewhere else goes out now, and this pixel starts the next one.
                    if (color_miss) begin
                        wr_bank  <= back_bank;
                        wr_row   <= {1'b0, color_row};
                        wr_col   <= color_col;
                        wr_data  <= color_word;
                        wr_be    <= color_be;
                        wr_valid <= 1'b1;
                        color_be <= 4'b0001 << px[1:0];
                    end else begin
                        color_be[px[1:0]] <= 1'b1;
                    end
                    color_row <= py;
                    color_col <= px[9:2];
                    color_word[8 * px[1:0] +: 8] <= pixel_color;
                    if (use_depth) begin
                        depth_tile[16 * px[3:0] +: 16] <= now_z;
                        depth_dirty[px[3:0]] <= 1'b1;
                    end
                    advance = 1'b1;
                end
            end

            // A marked tile needs no memory read, only the clear value. All of it must then reach memory when it goes
            // out, since memory never saw the clear. The last tile of a row is only 4 pixels wide.
            S_FLAG_WAIT: state <= S_FLAG_TAKE;
            S_FLAG_TAKE: begin
                if (flag_q[px[9:4]]) begin
                    depth_tile  <= {16{depth_clear_value}};
                    depth_first <= 3'd0;
                    depth_last  <= 3'd7;
                    depth_dirty <= (px[9:4] == TILES_PER_ROW - 1) ? LAST_TILE_PIXELS : 16'hFFFF;
                    depth_valid <= 1'b1;
                    depth_row   <= py;
                    depth_col   <= px[9:4];
                    flag_write       <= 1'b1;
                    flag_write_row   <= py;
                    flag_write_value <= flag_q & ~({{TILES_PER_ROW-1{1'b0}}, 1'b1} << px[9:4]);
                    state <= S_PIXEL;
                end else begin
                    state <= S_DEPTH_READ;
                end
            end

            S_DEPTH_READ: begin
                rr_valid <= 1'b1;
                rr_bank  <= BANK_DEPTH;
                rr_row   <= depth_sdram_row(py, px[9]);
                rr_col   <= {px[8:4], read_first};
                rr_len   <= {1'b0, read_last} - {1'b0, read_first} + 4'd1;
                fill_word <= read_first;
                depth_first <= read_first;
                depth_last  <= read_last;
                state    <= S_DEPTH_WAIT;
            end
            S_DEPTH_WAIT: begin
                if (rr_valid && rr_ready) rr_valid <= 1'b0;
                if (rr_done) begin
                    depth_tile[32 * fill_word +: 32] <= rr_data;
                    fill_word <= fill_word + 1'b1;
                    if (fill_word == depth_last) begin
                        depth_valid <= 1'b1;
                        depth_row   <= py;
                        depth_col   <= px[9:4];
                        state       <= S_PIXEL;
                    end
                end
            end

            S_TEX_READ: begin
                rr_valid <= 1'b1;
                rr_bank  <= BANK_TEXTURE;
                rr_row   <= tex_row_now;
                rr_col   <= {2'b00, now_u[7:2]};
                rr_len   <= 4'd1;
                state    <= S_TEX_WAIT;
            end
            S_TEX_WAIT: begin
                if (rr_valid && rr_ready) rr_valid <= 1'b0;
                if (rr_done) begin
                    tex_word     <= rr_data;
                    tex_valid    <= 1'b1;
                    tex_held_row <= tex_row_now;
                    tex_held_col <= now_u[7:2];
                    state        <= S_PIXEL;
                end
            end

            S_COLOR_FLUSH: if (write_free) begin
                wr_bank  <= back_bank;
                wr_row   <= {1'b0, color_row};
                wr_col   <= color_col;
                wr_data  <= color_word;
                wr_be    <= color_be;
                wr_valid <= 1'b1;
                color_be <= 4'd0;
                state    <= S_DRAIN;
            end
            // Offers each changed word of the tile in turn, one per clock while memory keeps up.
            S_DEPTH_FLUSH: if (!wr_valid || wr_ready) begin
                if (flush_left == 8'd0) begin
                    wr_valid    <= 1'b0;
                    flush_word  <= 4'd0;
                    depth_dirty <= 16'd0;
                    state       <= finishing ? S_DRAIN : S_PIXEL;
                end else begin
                    wr_valid   <= 1'b1;
                    wr_bank    <= BANK_DEPTH;
                    wr_row     <= depth_sdram_row(depth_row, depth_col[5]);
                    wr_col     <= {depth_col[4:0], flush_next};
                    wr_data    <= depth_tile[32 * flush_next +: 32];
                    wr_be      <= {{2{flush_dirty[1]}}, {2{flush_dirty[0]}}};
                    flush_word <= {1'b0, flush_next} + 1'b1;
                end
            end

            // Nothing may stay held after the triangle: the next command could read or overwrite it.
            S_DRAIN: begin
                finishing <= 1'b1;
                if (color_be != 0)      state <= S_COLOR_FLUSH;
                else if (depth_dirty != 0) state <= S_DEPTH_FLUSH;
                else if (write_free)    state <= S_FINISH;
            end

            // Op 1: one word per row.
            S_FLAG_WALK: begin
                flag_write       <= 1'b1;
                flag_write_row   <= walk_row;
                flag_write_value <= {TILES_PER_ROW{1'b1}};
                walk_row         <= walk_row + 1'b1;
                if (walk_row == HEIGHT - 1) state <= S_FINISH;
            end

            // Op 2: every marked tile, a row at a time.
            S_RESOLVE_WAIT: state <= S_RESOLVE_TAKE;
            S_RESOLVE_TAKE: begin
                resolve_flags <= flag_q;
                resolve_tile  <= 6'd0;
                resolve_word  <= 4'd0;
                state         <= S_RESOLVE_TILE;
            end
            S_RESOLVE_TILE: if (write_free) begin
                wr_valid <= 1'b0;
                if (resolve_tile == TILES_PER_ROW) begin
                    // The marks can stay: clears_pending now hides them, and the next clear rewrites them all.
                    walk_row         <= walk_row + 1'b1;
                    if (walk_row == HEIGHT - 1) begin
                        clears_pending <= 1'b0;
                        state          <= S_FINISH;
                    end else begin
                        state <= S_RESOLVE_WAIT;
                    end
                end else if (!resolve_flags[resolve_tile] || resolve_word == 4'd8) begin
                    resolve_tile <= resolve_tile + 1'b1;
                    resolve_word <= 4'd0;
                end else begin
                    wr_valid <= resolve_col < DEPTH_WORDS_PER_ROW;
                    wr_bank  <= BANK_DEPTH;
                    wr_row   <= depth_sdram_row(walk_row, resolve_tile[5]);
                    wr_col   <= resolve_col[7:0];
                    wr_data  <= {2{depth_clear_value}};
                    wr_be    <= 4'b1111;
                    resolve_word <= resolve_word + 1'b1;
                end
            end

            // Every path here has already seen its last write taken.
            S_FINISH: begin
                busy  <= 1'b0;
                done  <= 1'b1;
                state <= S_IDLE;
            end

            default: state <= S_IDLE;
        endcase

        if (!rst && advance) begin
            if (inside) row_entered <= 1'b1;
            // A triangle crosses a row in one piece, so leaving it means the rest of the row is empty.
            if (last_in_row || (!inside && row_entered)) begin
                if (py == max_y) begin
                    state <= S_DRAIN;
                end else begin
                    px          <= min_x;
                    py          <= py + 1'b1;
                    row_entered <= 1'b0;
                    for (i = 0; i < 3; i = i + 1) begin
                        e[i]     <= e_row[i] + e_step_y[i];
                        e_row[i] <= e_row[i] + e_step_y[i];
                    end
                    for (i = 0; i < 6; i = i + 1) begin
                        value[i]     <= value_row[i] + grad_y[i];
                        value_row[i] <= value_row[i] + grad_y[i];
                    end
                end
            end else if (!inside && can_jump) begin
                px <= px + 10'd8;
                e[0] <= e_jump0;
                e[1] <= e_jump1;
                e[2] <= e_jump2;
                for (i = 0; i < 6; i = i + 1) value[i] <= value[i] + (grad_x[i] <<< 3);
            end else begin
                px <= px + 1'b1;
                for (i = 0; i < 3; i = i + 1) e[i] <= e[i] + e_step_x[i];
                for (i = 0; i < 6; i = i + 1) value[i] <= value[i] + grad_x[i];
            end
        end
    end

endmodule
