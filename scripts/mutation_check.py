#!/usr/bin/env python3
"""Usage: python scripts/mutation_check.py [--seeds N] [--only TEXT]

Tests the tests. Plants one bug at a time in a copy of the Verilog and checks that a direct testbench
or the comparison against the emulator notices it. Exits non-zero if any planted bug gets through.
With DTGC_PICTURE=960x540 in the environment it plants the bugs only a picture that large can show.
"""
import argparse
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sw.dtgc import protocol as p  # noqa: E402
from sw.tests import test_rtl_match as match  # noqa: E402
from sw.tests import test_shade_rtl as shade_test  # noqa: E402
from sw.tests.streams import make_stream  # noqa: E402

ROOT = Path("build/sim/mutants")
match.SIM_TIMEOUT = 600  # a planted bug can hang the design, and a normal run takes far less

# name: (file, text to find, replacement)
BUGS = {
    "vertices past last slot": ("rtl/cmd_exec.v", "end else if (vertex_end > 9'd256) begin", "end else if (1'b0) begin"),
    "vertex slot off by one": ("rtl/cmd_exec.v", "store_slot <= arg[0];", "store_slot <= arg[0] + 1'b1;"),
    "vertex byte order wrong": ("rtl/cmd_exec.v", "if (store_byte == 3'd5) begin", "if (store_byte == 3'd4) begin"),
    "vertex length unchecked": ("rtl/cmd_exec.v", "T_VERTICES: begin\n                    store_slot <= arg[0];\n                    store_byte <= 3'd0;\n                    pay_pos    <= 11'd2;\n                    if (pkt_len != list_length) begin",
                                "T_VERTICES: begin\n                    store_slot <= arg[0];\n                    store_byte <= 3'd0;\n                    pay_pos    <= 11'd2;\n                    if (1'b0) begin"),
    "list length unchecked": ("rtl/cmd_exec.v", "arg_index <= 4'd2;\n                    pay_pos   <= 11'd2;\n                    if (pkt_len != list_length) begin",
                              "arg_index <= 4'd2;\n                    pay_pos   <= 11'd2;\n                    if (1'b0) begin"),
    "list stops after first": ("rtl/cmd_exec.v", "state     <= (pay_pos == pkt_len) ? S_REPLY_OK : S_LIST_WAIT;", "state     <= S_REPLY_OK;"),
    "list ignores bad triangle": ("rtl/cmd_exec.v", "if (raster_bad_value) ack_status <= STATUS_BAD_VALUE;\n                arg_index", "arg_index"),
    "list stops at bad triangle": ("rtl/cmd_exec.v", "state     <= (pay_pos == pkt_len) ? S_REPLY_OK : S_LIST_WAIT;", "state     <= (pay_pos == pkt_len || raster_bad_value) ? S_REPLY_OK : S_LIST_WAIT;"),
    "list record starts wrong": ("rtl/cmd_exec.v", "arg_index <= 4'd2;\n                state     <=", "arg_index <= 4'd3;\n                state     <="),
    "list colours swapped": ("rtl/vertex_store.v", "4'd6:    direct <= color[7:0];", "4'd6:    direct <= color[15:8];"),
    "list corner wrong slot": ("rtl/vertex_store.v", "corner_slot = slots[15:8];", "corner_slot = slots[7:0];"),
    "list last corner wrong": ("rtl/vertex_store.v", "place       = addr[3:0] - 4'd10;", "place       = addr[3:0] - 4'd9;"),
    "list mode ignored": ("rtl/vertex_store.v", "(addr == 10'd0) ? mode : 8'd0", "8'd0"),
    "list header not zero": ("rtl/vertex_store.v", "(addr == 10'd0) ? mode : 8'd0", "mode"),
    "raster reads payload": ("rtl/cmd_exec.v", "assign raster_from_store = pkt_type == T_TRIANGLE_LIST;", "assign raster_from_store = 1'b0;"),
    "span clip off by one": ("rtl/cmd_exec.v", "cur_x < WIDTH && cur_y < HEIGHT", "cur_x <= WIDTH && cur_y < HEIGHT"),
    "span reads wrong byte": ("rtl/cmd_exec.v", "buf_addr <= 10'd4;", "buf_addr <= 10'd3;"),
    "rect word past the end": ("rtl/cmd_exec.v", "x + 17'd4 <= x_end", "x + 17'd3 <= x_end"),
    "rect word off alignment": ("rtl/cmd_exec.v", "x[1:0] == 2'd0 && x + 17'd4", "x[0] == 1'b0 && x + 17'd4"),
    # A step of 3 would only rewrite one pixel with the same colour, so it can't change the picture. A step of 5 skips one.
    "rect step wrong": ("rtl/cmd_exec.v", "rect_step <= 3'd4;", "rect_step <= 3'd5;"),
    "depth rect wrong half": ("rtl/cmd_exec.v", "x[0] ? 4'b1100 : 4'b0011", "x[0] ? 4'b0011 : 4'b1100"),
    "depth rect wide past end": ("rtl/cmd_exec.v", "x + 17'd2 <= x_end", "x + 17'd1 <= x_end"),
    "depth rect wrong column": ("rtl/cmd_exec.v", "wr_col  <= x[8:1];", "wr_col  <= x[9:2];"),
    "depth rect hits picture": ("rtl/cmd_exec.v", "if (pkt_type == T_DEPTH_RECT) target <= BANK_DEPTH;", ""),
    "depth rect not clipped": ("rtl/cmd_exec.v", "(rect_x_end > WIDTH) ? WIDTH : rect_x_end", "rect_x_end"),
    "rect clip wrong": ("rtl/cmd_exec.v", "(rect_y_end > HEIGHT) ? HEIGHT", "(rect_y_end > HEIGHT) ? HEIGHT - 1"),
    "palette wraps past 255": ("rtl/cmd_exec.v", "pal_we    <= !pal_index[8];", "pal_we    <= 1'b1;"),
    "repeated packet redone": ("rtl/cmd_exec.v", "pkt_seq == expected - 1'b1", "1'b0"),
    "byte lanes swapped": ("rtl/cmd_exec.v", "byte_enable = 4'b0001 << lane;", "byte_enable = 4'b1000 >> lane;"),
    "bad length accepted": ("rtl/cmd_exec.v", "T_CLEAR: length_ok = len == 11'd1;", "T_CLEAR: length_ok = 1'b1;"),
    "body checksum ignored": ("rtl/pkt_parser.v", "pkt_crc_ok <= {in_data, crc_low} == body_crc;", "pkt_crc_ok <= 1'b1;"),
    "header checksum ignored": ("rtl/pkt_parser.v", "in_data != header_crc || ", ""),
    "length limit off by one": ("rtl/pkt_parser.v", "length > MAX_PAYLOAD", "length > MAX_PAYLOAD + 1"),
    "no idle timeout": ("rtl/pkt_parser.v", "if (idle_count == IDLE_TIMEOUT) begin", "if (1'b0) begin"),
    "tile row wraps early": ("rtl/cmd_exec.v", "wire row_ends  = cur_x + 1'b1 == rect_x_end;", "wire row_ends  = cur_x + 2'd2 == rect_x_end;"),
    "tile area never full": ("rtl/cmd_exec.v", "wire area_full = row_ends && cur_y + 1'b1 == rect_y_end;", "wire area_full = 1'b0;"),
    "tile not clipped": ("rtl/cmd_exec.v", "// Pixels off the picture are skipped, and still use up their place in the area.\n            S_PIXEL: begin\n                if (cur_x < WIDTH && cur_y < HEIGHT) begin", "S_PIXEL: begin\n                if (cur_y < HEIGHT) begin"),
    "run one pixel short": ("rtl/cmd_exec.v", "run_left <= buf_q;", "run_left <= (buf_q == 0) ? buf_q : buf_q - 1'b1;"),
    "run payload end ignored": ("rtl/cmd_exec.v", "end else if (pay_pos == pkt_len) begin", "end else if (1'b0) begin"),
    "odd run length accepted": ("rtl/cmd_exec.v", "T_RLE:   length_ok = len >= 11'd8 && !len[0];", "T_RLE:   length_ok = len >= 11'd8;"),
    "empty tile not skipped": ("rtl/cmd_exec.v", "if (arg_w == 0 || arg_h == 0 || pkt_len == 11'd8) state", "if (pkt_len == 11'd8) state"),
    "edge rule ignored": ("rtl/raster.v", "wire top_left = edge_dy < 0 || (edge_dy == 0 && edge_dx > 0);", "wire top_left = 1'b1;"),
    "winding not fixed": ("rtl/raster.v", "                    state <= S_SWAP;", "                    state <= S_BOX;"),
    "plane rounding wrong": ("rtl/raster.v", "plane = c0_fixed + (sum >>> 4);", "plane = c0_fixed + (sum >>> 3);"),
    "gradient limit missing": ("rtl/raster.v", "(div_q >= 56'h80000000) ? 32'h7FFFFFFF : div_q[31:0]", "div_q[31:0]"),
    "depth test reversed": ("rtl/raster.v", "use_depth && now_z >= stored_z", "use_depth && now_z < stored_z"),
    "depth equal passes": ("rtl/raster.v", "use_depth && now_z >= stored_z", "use_depth && now_z > stored_z"),
    "depth not written": ("rtl/raster.v", "depth_dirty[px[3:0]] <= 1'b1;", "depth_dirty[px[3:0]] <= 1'b0;"),
    "depth half lost": ("rtl/raster.v", "{{2{flush_dirty[1]}}, {2{flush_dirty[0]}}}", "{{2{flush_dirty[0]}}, {2{flush_dirty[0]}}}"),
    "depth halves swapped in flush": ("rtl/raster.v", "{{2{flush_dirty[1]}}, {2{flush_dirty[0]}}}", "{{2{flush_dirty[0]}}, {2{flush_dirty[1]}}}"),
    "depth flush stops early": ("rtl/raster.v", "flush_word[3] ? 8'd0 :", "(flush_word >= 4'd7) ? 8'd0 :"),
    "depth flush sends clean words": ("rtl/raster.v", "dirty_words & (8'hFF << flush_word[2:0])", "8'hFF << flush_word[2:0]"),
    "depth flush wrong column": ("rtl/raster.v", "wr_col     <= {depth_col[4:0], flush_next};", "wr_col     <= {depth_col[4:0], 3'd0};"),
    "depth flush skips waiting": ("rtl/raster.v", "S_DEPTH_FLUSH: if (!wr_valid || wr_ready) begin", "S_DEPTH_FLUSH: begin"),
    "depth flush wrong word": ("rtl/raster.v", "wr_data    <= depth_tile[32 * flush_next +: 32];", "wr_data    <= depth_tile[31:0];"),
    "depth fill stops early": ("rtl/raster.v", "if (fill_word == depth_last) begin", "if (fill_word == depth_first) begin"),
    "depth fill wrong start": ("rtl/raster.v", "rr_col   <= {px[8:4], read_first};", "rr_col   <= {px[8:4], read_first ^ 3'd1};"),
    "depth burst too short": ("rtl/raster.v", "{1'b0, read_first} + 4'd1;", "{1'b0, read_first};"),
    "texture read too long": ("rtl/raster.v", "rr_len   <= 4'd1;", "rr_len   <= 4'd2;"),
    "burst repeats one column": ("rtl/sdram_ctrl.v", "write_col  <= write_col + 1'b1;", "write_col  <= write_col;"),
    "burst hit starts wrong": ("rtl/sdram_ctrl.v", "write_col  <= rr_col + 1'b1;", "write_col  <= rr_col;"),
    "burst hit one word short": ("rtl/sdram_ctrl.v", "words_left <= rr_len - 1'b1;", "words_left <= rr_len - 2'd2;"),
    "burst miss one word short": ("rtl/sdram_ctrl.v", "words_left <= rr_len;", "words_left <= rr_len - 1'b1;"),
    "burst leaves no gap": ("rtl/sdram_ctrl.v", "if (words_left == 1) begin\n                        wait_cnt <= READ_GAP;", "if (words_left == 1) begin\n                        wait_cnt <= 13'd0;"),
    "depth stored in wrong half": ("rtl/raster.v", "depth_tile[16 * px[3:0] +: 16] <= now_z;", "depth_tile[16 * (px[3:0] ^ 4'd1) +: 16] <= now_z;"),
    "colour stored in wrong byte": ("rtl/raster.v", "color_word[8 * px[1:0] +: 8] <= pixel_color;", "color_word[8 * (px[1:0] ^ 2'd1) +: 8] <= pixel_color;"),
    "colour hit ignores row": ("rtl/raster.v", "wire       color_hit = color_row == py && color_col == px[9:2];", "wire       color_hit = color_col == px[9:2];"),
    "colour hit ignores column": ("rtl/raster.v", "wire       color_hit = color_row == py && color_col == px[9:2];", "wire       color_hit = color_row == py;"),
    "depth hit ignores row": ("rtl/raster.v", "depth_valid && depth_row == py && depth_col == px[9:4]", "depth_valid && depth_col == px[9:4]"),
    "depth hit ignores column": ("rtl/raster.v", "depth_valid && depth_row == py && depth_col == px[9:4]", "depth_valid && depth_row == py"),
    "texture hit ignores row": ("rtl/raster.v", "tex_valid && tex_held_row == tex_row_now && tex_held_col == now_u[7:2];", "tex_valid && tex_held_col == now_u[7:2];"),
    "texture hit ignores column": ("rtl/raster.v", "tex_valid && tex_held_row == tex_row_now && tex_held_col == now_u[7:2];", "tex_valid && tex_held_row == tex_row_now;"),
    "held depth kept between triangles": ("rtl/raster.v", "                bad_value  <= 1'b0;\n                depth_valid <= 1'b0;\n", "                bad_value  <= 1'b0;\n"),
    "cleared tile mark never removed": ("rtl/raster.v", "flag_write_value <= flag_q & ~({{TILES_PER_ROW-1{1'b0}}, 1'b1} << px[9:4]);", "flag_write_value <= flag_q;"),
    "cleared tile not written whole": ("rtl/raster.v", "depth_dirty <= (px[9:4] == TILES_PER_ROW - 1) ? LAST_TILE_PIXELS : 16'hFFFF;", "depth_dirty <= 16'd0;"),
    "cleared tile gets wrong value": ("rtl/raster.v", "depth_tile  <= {16{depth_clear_value}};", "depth_tile  <= {16{16'd0}};"),
    "cleared tile wrong flag": ("rtl/raster.v", "if (flag_q[px[9:4]]) begin", "if (flag_q[px[8:3]]) begin"),
    "cleared marks ignored": ("rtl/raster.v", "clears_pending ? S_FLAG_WAIT : S_DEPTH_READ;", "S_DEPTH_READ;"),
    "rect does not resolve": ("rtl/cmd_exec.v", "(pkt_type == T_DEPTH_RECT) ? S_DEPTH_RESOLVE : S_RECT", "S_RECT"),
    "resolve skips last tile": ("rtl/raster.v", "if (resolve_tile == TILES_PER_ROW) begin", "if (resolve_tile == TILES_PER_ROW - 1) begin"),
    "resolve short": ("rtl/raster.v", "resolve_word == 4'd8) begin", "resolve_word == 4'd7) begin"),
    "resolve past the row end": ("rtl/raster.v", "wr_valid <= resolve_col < DEPTH_WORDS_PER_ROW;", "wr_valid <= 1'b1;"),
    "resolve ignores marks": ("rtl/raster.v", "!resolve_flags[resolve_tile] || resolve_word", "resolve_word"),
    "clear value kept old": ("rtl/raster.v", "depth_clear_value <= clear_value;", ""),
    "flat skip keeps old slope": ("rtl/raster.v", "                    grad_x[attr_index]    <= 32'sd0;\n", ""),
    "flat skip wrong test": ("rtl/raster.v", "end else if (dc1 == 0 && dc2 == 0) begin", "end else if (dc1 == 0) begin"),
    "flat skip wrong start": ("rtl/raster.v", "value_row[attr_index] <= c0_fixed;", "value_row[attr_index] <= 48'sd0;"),
    "jump any negative edge": ("rtl/raster.v", "(e[0][36] && e_jump0[36])", "(e[0][36])"),
    "jump past the box": ("rtl/raster.v", "({1'b0, px} + 11'd8 <= {1'b0, max_x}) &&", ""),
    "jump forgets values": ("rtl/raster.v", "value[i] <= value[i] + (grad_x[i] <<< 3);", "value[i] <= value[i] + grad_x[i];"),
    "posted word loses old byte marks": ("rtl/raster.v", "color_be <= 4'b0001 << px[1:0];", "color_be <= 4'b1111;"),
    "posted write ignores busy port": ("rtl/raster.v", "end else if (!color_miss || write_free) begin", "end else begin"),
    "colour flush overwrites": ("rtl/raster.v", "S_COLOR_FLUSH: if (write_free) begin", "S_COLOR_FLUSH: begin"),
    "held texture kept between triangles": ("rtl/raster.v", "                tex_valid   <= 1'b0;\n", ""),
    "colour not flushed at end": ("rtl/raster.v", "if (color_be != 0)      state <= S_COLOR_FLUSH;\n                else if (depth_dirty != 0)", "if (depth_dirty != 0)"),
    "depth not flushed at end": ("rtl/raster.v", "else if (depth_dirty != 0) state <= S_DEPTH_FLUSH;\n                else if (write_free)    state <= S_FINISH;", "else state <= S_FINISH;"),
    "depth not flushed on move": ("rtl/raster.v", "state <= (depth_dirty != 0) ? S_DEPTH_FLUSH : clears_pending ? S_FLAG_WAIT : S_DEPTH_READ;", "state <= clears_pending ? S_FLAG_WAIT : S_DEPTH_READ;"),
    "row left on first outside pixel": ("rtl/raster.v", "if (last_in_row || (!inside && row_entered)) begin", "if (last_in_row || !inside) begin"),
    "row flag not cleared": ("rtl/raster.v", "                    row_entered <= 1'b0;\n                    for (i = 0; i < 3", "                    for (i = 0; i < 3"),
    "depth wrong half": ("rtl/raster.v", "wire [15:0] stored_z = depth_tile[16 * px[3:0] +: 16];", "wire [15:0] stored_z = depth_tile[16 * (px[3:0] ^ 4'd1) +: 16];"),
    "texture byte wrong": ("rtl/raster.v", "2'd1: tex_byte = tex_word[15:8];", "2'd1: tex_byte = tex_word[7:0];"),
    "texture mask missing": ("rtl/raster.v", "wire [7:0]  now_u = clamp8(value[4]) & tex_mask;", "wire [7:0]  now_u = clamp8(value[4]);"),
    "colour clamp missing": ("rtl/raster.v", "clamp8 = v[47] ? 8'd0 : (v[46:24] != 0) ? 8'd255 : v[23:16];", "clamp8 = v[23:16];"),
    "box not limited": ("rtl/raster.v", "wire signed [11:0] box_max_y = (high_py > HEIGHT - 1) ? HEIGHT - 1 : high_py;", "wire signed [11:0] box_max_y = high_py;"),
    "range check missing": ("rtl/raster.v", "in_range = value[15] == value[14];", "in_range = 1'b1;"),
    "texture size unchecked": ("rtl/raster.v", "if (tex_size > 8'd8 || ", "if ("),
    "dither ignored": ("rtl/raster.v", "wire use_dither  = mode[2];", "wire use_dither  = 1'b0;"),
    "dither always on": ("rtl/raster.v", "wire use_dither  = mode[2];", "wire use_dither  = 1'b1;"),
    "dither pattern wrong": ("rtl/raster.v", "4'd5:  bayer = 4'd4;", "4'd5:  bayer = 4'd5;"),
    "dither blue too weak": ("rtl/raster.v", "(now_b >> 2) + {bayer, 2'b00}", "(now_b >> 2) + {bayer, 1'b0}"),
    "dither red not scaled": ("rtl/raster.v", "now_r - (now_r >> 3) + {bayer", "now_r + {bayer"),
    "dither green not scaled": ("rtl/raster.v", "now_g - (now_g >> 3) + {bayer", "now_g + {bayer"),
    "dither blue not scaled": ("rtl/raster.v", "now_b - (now_b >> 2) + {bayer", "now_b + {bayer"),
    "write hit ignores the row": ("rtl/sdram_ctrl.v", "wire write_hit = open_valid[wr_bank] && open_row[wr_bank] == wr_row;", "wire write_hit = open_valid[wr_bank];"),
    "read hit ignores the row": ("rtl/sdram_ctrl.v", "wire read_hit  = open_valid[rr_bank] && open_row[rr_bank] == rr_row;", "wire read_hit  = open_valid[rr_bank];"),
    "write hit mask wrong": ("rtl/sdram_ctrl.v", "sdram_dqm    <= ~wr_be;", "sdram_dqm    <= 4'b0000;"),
    "closed without write recovery": ("rtl/sdram_ctrl.v", "S_CLOSE_ROW: if (recover == 0) begin", "S_CLOSE_ROW: begin"),
    "refresh without write recovery": ("rtl/sdram_ctrl.v", "end else if (recover == 0) begin", "end else begin"),
    "refresh with rows open": ("rtl/sdram_ctrl.v", "if (open_valid == 4'b0000) begin", "if (1'b1) begin"),
    "word read marked as line": ("rtl/sdram_ctrl.v", "rd_valid <= !word_read;", "rd_valid <= 1'b1;"),
    "texture span past row": ("rtl/cmd_exec.v", " || cur_x[7:0] == 8'd255) ? S_REPLY_OK : S_TEX_WAIT;", ") ? S_REPLY_OK : S_TEX_WAIT;"),
    "texture row limit": ("rtl/cmd_exec.v", "{arg[1], arg[0]} >= 16'd2048", "1'b0"),
    "depth clear too short": ("rtl/raster.v", "if (walk_row == HEIGHT - 1) state <= S_FINISH;", "if (walk_row == HEIGHT - 2) state <= S_FINISH;"),
    "reply checksum wrong": ("rtl/reply_tx.v", "index <= 4'd8) body_crc", "index <= 4'd7) body_crc"),
    "read wrong buffer": ("rtl/cmd_exec.v", "assign read_bank    = arg[8][0] ? {1'b0, ~front} : {1'b0, front};", "assign read_bank    = {1'b0, front};"),
    "read which unchecked": ("rtl/cmd_exec.v", "if (arg[8] > 8'd1) begin", "if (1'b0) begin"),
    "read not clipped": ("rtl/cmd_exec.v", "x_end <= (rect_x_end > WIDTH) ? WIDTH : rect_x_end;\n                    y_end <= (rect_y_end > HEIGHT) ? HEIGHT : rect_y_end;\n                    if (arg[8]", "x_end <= rect_x_end;\n                    y_end <= (rect_y_end > HEIGHT) ? HEIGHT : rect_y_end;\n                    if (arg[8]"),
    "read cuts into a reply": ("rtl/cmd_exec.v", "S_READ_START: if (!reply_busy) begin", "S_READ_START: begin"),
    "read row number wrong": ("rtl/frame_reader.v", "4'd7:    tx_data = cur_y[7:0];", "4'd7:    tx_data = cur_x[7:0];"),
    "read row high byte": ("rtl/frame_reader.v", "default: tx_data = {6'd0, cur_y[9:8]};", "default: tx_data = 8'd0;"),
    "read length wrong": ("rtl/frame_reader.v", "{1'b0, x_first} + 11'd2;", "{1'b0, x_first} + 11'd1;"),
    "read checksum skips row": ("rtl/frame_reader.v", "if (index >= 4'd1) body_crc <= crc16_next(body_crc, tx_data);", "if (index >= 4'd1 && index <= 4'd6) body_crc <= crc16_next(body_crc, tx_data);"),
    "read checksum not reset": ("rtl/frame_reader.v", "index      <= 4'd0;\n                    header_crc <= 8'h00;\n                    body_crc   <= 16'hFFFF;\n                    state      <= S_HEADER;\n                end\n            end\n\n            default", "index      <= 4'd0;\n                    header_crc <= 8'h00;\n                    state      <= S_HEADER;\n                end\n            end\n\n            default"),
    "read burst too long": ("rtl/frame_reader.v", "(cols_to_end > 9'd8) ? 4'd8", "(cols_to_end > 9'd8) ? 4'd9"),
    "read ignores row end word": ("rtl/frame_reader.v", "+ (x_stop[1:0] != 2'd0);", ";"),
    "read pixel order": ("rtl/frame_reader.v", "2'd1:    tx_data = word_now[15:8];", "2'd1:    tx_data = word_now[7:0];"),
    "read skips waiting": ("rtl/frame_reader.v", "S_PIXEL: if (tx_ready) begin", "S_PIXEL: begin"),
    "read stops a word early": ("rtl/frame_reader.v", "if (rr_done && words_left == 4'd1) state <= S_PIXEL;", "if (rr_done && words_left == 4'd2) state <= S_PIXEL;"),
    "read keeps old words": ("rtl/frame_reader.v", "else if (out_of_words) state <= S_FETCH;", ""),
    "read starts rows wrong": ("rtl/frame_reader.v", "cur_x      <= x_first;", "cur_x      <= 10'd0;"),
    "reply mixed with read": ("rtl/gpu_core.v", "assign tx_valid = reader_busy ? reader_tx_valid : reply_tx_valid;", "assign tx_valid = reply_tx_valid;"),
    "pixel order on screen": ("rtl/fb_scanout.v", "(byte_sel == 2'd0) ? line_word[7:0]", "(byte_sel == 2'd0) ? line_word[15:8]"),
    "default palette wrong": ("rtl/fb_scanout.v", "boot_b, boot_b, boot_b, boot_b}", "boot_b, boot_b, boot_b, 2'b00}"),
    "write mask wrong": ("rtl/sdram_ctrl.v", "sdram_dqm    <= ~write_be;", "sdram_dqm    <= 4'b0000;"),
    "FT pins start driven": ("rtl/ft_bus.v", "ft_oe_n = 1'b1;", "ft_oe_n = 1'b0;"),
    "FT no read turnaround": ("rtl/ft_bus.v", "state   <= S_READ_TURN;", "ft_rd_n <= 1'b0; state <= S_READ;"),
    "FT write pins not driven": ("rtl/ft_bus.v", "ft_d_oe <= 1'b1;", "ft_d_oe <= 1'b0;"),
    "FT refused byte lost": ("rtl/ft_bus.v", "wire can_load = !holding || write_done;", "wire can_load = !holding || !ft_wr_n;"),
    "FT read ignores RXF": ("rtl/ft_bus.v", "wire read_done  = !ft_rd_n && !ft_rxf_n;", "wire read_done  = !ft_rd_n;"),
    "FT write ignores TXE": ("rtl/ft_bus.v", "wire write_done = !ft_wr_n && !ft_txe_n;", "wire write_done = !ft_wr_n;"),
    "FT reads with no room": ("rtl/ft_bus.v", "if (!rx_room || (tx_valid && !ft_txe_n)) begin", "if (tx_valid && !ft_txe_n) begin"),
    "FT starts read with no room": ("rtl/ft_bus.v", "wire want_read  = !ft_rxf_n && rx_room;", "wire want_read  = !ft_rxf_n;"),
    "FT replies starved": ("rtl/ft_bus.v", "if (!rx_room || (tx_valid && !ft_txe_n)) begin", "if (!rx_room) begin"),
    "FT no spare room": ("rtl/ft_link.v", ".SPARE(4)", ".SPARE(0)"),
    "FT ignores GPU not ready": ("rtl/ft_link.v", "assign rx_valid = rx_out_valid && rx_ready;", "assign rx_valid = rx_out_valid;"),
    "FT replies overrun": ("rtl/ft_link.v", "assign tx_ready = !tx_full;", "assign tx_ready = 1'b1;"),
    "FIFO full test wrong": ("rtl/async_fifo.v", "{~rd_gray_sync2[ADDR_BITS:ADDR_BITS - 1], rd_gray_sync2[ADDR_BITS - 2:0]}", "{rd_gray_sync2[ADDR_BITS:ADDR_BITS - 1], rd_gray_sync2[ADDR_BITS - 2:0]}"),
    "FIFO write pointer not Gray": ("rtl/async_fifo.v", "wr_gray <= wr_bin_next ^ (wr_bin_next >> 1);", "wr_gray <= wr_bin_next;"),
    "FIFO read pointer not Gray": ("rtl/async_fifo.v", "rd_gray  <= rd_bin_next ^ (rd_bin_next >> 1);", "rd_gray  <= rd_bin_next;"),
    "FIFO fill level wrong": ("rtl/async_fifo.v", "gray_to_binary[i + 1] ^ gray[i]", "gray[i]"),
}

BUGS.update({
    "edge brightness wrong": ("rtl/upscale_edge.v", "sum = pixel[23:16] + {pixel[15:8], 1'b0} + pixel[7:0];", "sum = pixel[23:16] + {pixel[15:8], 1'b0} + pixel[23:16];"),
    "edge ties other diagonal": ("rtl/upscale_edge.v", "weights(main_gap <= other_gap,", "weights(main_gap < other_gap,"),
    "edge diagonals swapped": ("rtl/upscale_edge.v", "weights(main_gap <= other_gap,", "weights(main_gap > other_gap,"),
    "edge gap one way": ("rtl/upscale_edge.v", "gap = (x > y) ? x - y : y - x;", "gap = x - y;"),
    "edge weights wrong": ("rtl/upscale_edge.v", "3'b110: weights = {2'd1, 2'd2, 2'd0, 2'd1};", "3'b110: weights = {2'd1, 2'd0, 2'd2, 2'd1};"),
    "edge weights wrong far": ("rtl/upscale_edge.v", "default: weights = {2'd0, 2'd1, 2'd1, 2'd2};", "default: weights = {2'd2, 2'd1, 2'd1, 2'd0};"),
    "edge x and y swapped": ("rtl/upscale_edge.v", "right1 <= weight_x[1];", "right1 <= weight_y[1];"),
    "edge no rounding": ("rtl/upscale_edge.v", "sum_ab + sum_cd + 12'd2;", "sum_ab + sum_cd;"),
    "edge times two wrong": ("rtl/upscale_edge.v", "2'd2: times = {1'b0, x, 1'b0};", "2'd2: times = {2'b00, x};"),
    "shade dot loses part": ("rtl/shade_pipe.v", "dot2   <= part_x + part_y + part_z;", "dot2   <= part_x + part_y;"),
    "shade dark side lights": ("rtl/shade_pipe.v", "dot2[33] ? 18'sd0 : dot2[33:16]", "dot2[33:16]"),
    "shade light not limited": ("rtl/shade_pipe.v", "light_sum > 20'sd256 ? 9'd256 : light_sum[8:0]", "light_sum[8:0]"),
    "shade light can go negative": ("rtl/shade_pipe.v", "light_sum < 0 ? 9'd0 : light_sum", "light_sum"),
    "shade noise unsigned": ("rtl/shade_pipe.v", "$signed({1'b0, hash3[15:8]}) - 9'sd128", "$signed({1'b0, hash3[15:8]})"),
    "shade noise shift logical": ("rtl/shade_pipe.v", "(noise2 >>> 8)", "$signed({8'd0, noise2[17:8]})"),
    "shade hash wrong": ("rtl/shade_pipe.v", "hash2 = hash1 ^ (hash1 >> 9)", "hash2 = hash1 ^ (hash1 >> 8)"),
    "shade lit no rounding": ("rtl/shade_pipe.v", "colour * light + 17'd128", "colour * light"),
    "shade blend no rounding": ("rtl/shade_pipe.v", "$signed({1'b0, amount}) + 20'sd128", "$signed({1'b0, amount})"),
    "shade alpha late": ("rtl/shade_pipe.v", "blend_channel(lit4[7:0], dst4[7:0], alpha4)", "blend_channel(lit4[7:0], dst4[7:0], alpha3)"),
    "shade valid short": ("rtl/shade_pipe.v", "out_valid <= valid[4];", "out_valid <= valid[3];"),
})

# Bugs only a picture over 512 pixels wide can show.
# Left out because they cannot change any result. Held depth is dropped at the start of each triangle, and within a
# triangle a row is crossed once, left to right and without gaps, so these never apply: ignoring depth_first or
# depth_last in depth_hit, leaving depth_first alone for a marked tile (a miss there only costs time), and comparing
# 5 bits of the tile number on a wide picture (every tile between two aliases is read first).
LARGE_BUGS = {
    "depth read wrong row": ("rtl/raster.v", "depth_sdram_row(py, px[9])", "depth_sdram_row(py, 1'b0)"),
    "depth flush wrong row": ("rtl/raster.v", "depth_sdram_row(depth_row, depth_col[5])", "depth_sdram_row(depth_row, 1'b0)"),
    "depth resolve wrong row": ("rtl/raster.v", "depth_sdram_row(walk_row, resolve_tile[5])", "depth_sdram_row(walk_row, 1'b0)"),
    "depth rect wrong row": ("rtl/cmd_exec.v", "if (TWO_DEPTH_ROWS) wr_row <= {y[9:0], x[9]};", ""),
    "last tile mask wrong": ("rtl/raster.v", "(WIDTH % 16 == 0) ? 16'hFFFF :", "(WIDTH % 16 == 0) ? 16'h00FF :"),
    "colour column too narrow": ("rtl/raster.v", "color_col == px[9:2]", "color_col[6:0] == px[8:2]"),
    "row flags too few": ("rtl/raster.v", ".ROWS((HEIGHT > 512) ? 1024 : 512)", ".ROWS(512)"),
    "two rows never used": ("rtl/raster.v", "localparam TWO_DEPTH_ROWS = WIDTH > 512;", "localparam TWO_DEPTH_ROWS = 1'b0;"),
}

# Testbenches that drive one part directly, for bugs the whole-GPU comparison can miss.
DIRECT_TESTS = (
    (["sim/upscale_edge_tb.v", "rtl/upscale_edge.v"], (("+seed=1",),)),
    (["sim/sdram_ctrl_tb.v", "sim/sdram_model.v", "rtl/sdram_ctrl.v"], (("+seed=1", "+ops=8000"),)),
    (["sim/ft_link_tb.v", "sim/ft2232h_model.v", "rtl/ft_link.v", "rtl/ft_bus.v", "rtl/async_fifo.v"],
     (("+seed=1", "+bytes=4000"), ("+seed=1", "+bytes=4000", "+gpustall=95"),
      ("+seed=2", "+bytes=4000", "+rxstall=50", "+txstall=50", "+gpustall=50"),
      ("+seed=3", "+bytes=4000", "+rxstall=20", "+txstall=20", "+gpustall=20", "+clockgaps=5"))),
)


def direct_test_notices(path, mutant, folder):
    """Runs each direct testbench that uses the planted file. Returns what it reported, or None if all passed."""
    vvp = folder / "direct.vvp"
    for sources, runs in DIRECT_TESTS:
        if path not in sources:
            continue
        subprocess.run(["iverilog", "-g2005", "-o", str(vvp), *[str(mutant) if s == path else s for s in sources]],
                       check=True, capture_output=True)
        for plusargs in runs:
            lines = subprocess.run(["vvp", str(vvp), *plusargs], capture_output=True, text=True).stdout.splitlines()
            if not any(l.startswith("PASS") for l in lines) or any(l.startswith("FAIL") for l in lines):
                return next((l for l in lines if l.startswith("FAIL")), "no PASS printed")
    return None


def try_bug(name, seeds, streams):
    path, find, replace = {**BUGS, **LARGE_BUGS}[name]
    source = Path(path).read_text()
    if find not in source:
        return name, "TEXT NOT FOUND: update this script"
    folder = ROOT / re.sub(r"\W+", "_", name)
    folder.mkdir(parents=True, exist_ok=True)
    mutant = folder / Path(path).name
    mutant.write_text(source.replace(find, replace))
    noticed = direct_test_notices(path, mutant, folder)
    if noticed:
        return name, f"caught, direct test: {noticed[:60]}"
    if path == "rtl/shade_pipe.v":
        noticed = shade_test.difference(["sim/shade_pipe_tb.v", str(mutant)], folder)
        return name, f"caught: {noticed[:60]}" if noticed else "NOT CAUGHT"
    if path not in match.SOURCES:
        return name, "NOT CAUGHT"
    sources = [str(mutant) if s == path else s for s in match.SOURCES]
    vvp = folder / "tb.vvp"
    size = [] if p.WIDTH == 340 else ["-Pgpu_core_tb.SCANOUT=0", f"-Pgpu_core_tb.WIDTH={p.WIDTH}", f"-Pgpu_core_tb.HEIGHT={p.HEIGHT}"]
    subprocess.run(["iverilog", "-g2005", *size, "-o", str(vvp), *sources], check=True, capture_output=True)
    for seed in seeds:
        try:
            problems = match.compare(seed, streams[seed], vvp, folder, video=p.WIDTH == 340)
        except subprocess.TimeoutExpired:
            return name, f"caught, seed {seed}: the simulation never finished"
        if problems:
            return name, f"caught, seed {seed}: {problems[0][:60]}"
    return name, "NOT CAUGHT"


def main():
    parser = argparse.ArgumentParser(description="Check that the tests notice planted bugs.")
    parser.add_argument("--seeds", type=int, default=12)
    parser.add_argument("--only", help="try just the planted bugs whose name contains this")
    args = parser.parse_args()
    seeds = list(range(1, args.seeds + 1))
    streams = {seed: make_stream(seed) for seed in seeds}
    names = [n for n in (BUGS if p.WIDTH == 340 else LARGE_BUGS) if not args.only or args.only in n]
    with ThreadPoolExecutor() as pool:
        results = list(pool.map(lambda n: try_bug(n, seeds, streams), names))
    for name, result in results:
        print(f"{name:26s} {result}")
    missed = [n for n, r in results if not r.startswith("caught")]
    print(f"\n{len(results) - len(missed)} of {len(results)} planted bugs caught")
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
