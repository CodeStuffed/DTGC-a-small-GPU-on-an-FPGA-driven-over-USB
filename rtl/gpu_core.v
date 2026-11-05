// The GPU with no vendor parts and no particular link: bytes in, reply bytes out, SDRAM and video.
// Top levels add the clocks, HDMI output, and a link (UART now, FT2232H FIFO later).
`timescale 1ns / 1ps

module gpu_core #(
    parameter IDLE_TIMEOUT = 65535,
    parameter SCANOUT = 1,          // 1 plain 640x480. 0 the USB-output version: no lines are read, only refresh goes on.
                                    // 2 the HD version, using clk_video and the settings below.
    parameter SCALE = 2,
    parameter EDGE = 0,             // edge-directed scaling instead of bilinear, scale 2 only
    parameter WIDTH = 340,          // the picture drawn. Over 340 needs the HD version or no video at all.
    parameter HEIGHT = 340,
    parameter LINE_WORDS = 85,      // WIDTH / 4, rounded up
    parameter H_VISIBLE = 1280,
    parameter H_FRONT = 110,
    parameter H_SYNC = 40,
    parameter H_BACK = 220,
    parameter V_VISIBLE = 720,
    parameter V_FRONT = 5,
    parameter V_SYNC = 5,
    parameter V_BACK = 20
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        clk_video,   // only used by the HD version
    input  wire        rst_video,

    input  wire        rx_valid,
    input  wire [7:0]  rx_data,
    output wire [10:0] rx_used,     // bytes waiting; the PC's flow control keeps this from filling
    output wire        rx_overflow, // sticky

    output wire        tx_valid,
    output wire [7:0]  tx_data,
    input  wire        tx_ready,

    output wire        hsync,
    output wire        vsync,
    output wire        de,
    output wire [7:0]  red,
    output wire [7:0]  green,
    output wire [7:0]  blue,
    output wire        underrun,

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
        .clk(clk), .rst(rst), .x(x), .y(y), .hsync(raw_hsync), .vsync(raw_vsync),
        .visible(visible), .frame_start()
    );

    wire        init_done, line_req, line_read, rd_valid;
    wire [1:0]  line_bank, wr_bank;
    wire [10:0] line_row, wr_row;
    wire [31:0] rd_data, wr_data;
    wire        wr_valid, wr_ready;
    wire [7:0]  wr_col;
    wire [3:0]  wr_be;
    wire        rr_ready, rr_done;

    // Read port users. The executor waits for each one to finish, so they never overlap.
    wire        reader_busy, reader_rr_valid, raster_rr_valid;
    wire [1:0]  reader_rr_bank, raster_rr_bank;
    wire [10:0] reader_rr_row, raster_rr_row;
    wire [7:0]  reader_rr_col, raster_rr_col;
    wire [3:0]  reader_rr_len, raster_rr_len;
    wire        rr_valid = reader_busy ? reader_rr_valid : raster_rr_valid;
    wire [1:0]  rr_bank  = reader_busy ? reader_rr_bank : raster_rr_bank;
    wire [10:0] rr_row   = reader_busy ? reader_rr_row : raster_rr_row;
    wire [7:0]  rr_col   = reader_busy ? reader_rr_col : raster_rr_col;
    wire [3:0]  rr_len   = reader_busy ? reader_rr_len : raster_rr_len;

    sdram_ctrl #(.LINE_WORDS(LINE_WORDS)) memory (
        .clk(clk), .rst(rst), .init_done(init_done),
        .line_req(line_req), .line_read(line_read && SCANOUT != 0), .line_bank(line_bank), .line_row(line_row),
        .rd_valid(rd_valid), .rd_data(rd_data),
        .wr_valid(wr_valid && init_done), .wr_ready(wr_ready), .wr_bank(wr_bank), .wr_row(wr_row),
        .wr_col(wr_col), .wr_data(wr_data), .wr_be(wr_be),
        .rr_valid(rr_valid), .rr_ready(rr_ready), .rr_bank(rr_bank), .rr_row(rr_row), .rr_col(rr_col), .rr_len(rr_len),
        .rr_done(rr_done),
        .sdram_cke(sdram_cke), .sdram_cs_n(sdram_cs_n), .sdram_ras_n(sdram_ras_n),
        .sdram_cas_n(sdram_cas_n), .sdram_we_n(sdram_we_n), .sdram_ba(sdram_ba),
        .sdram_addr(sdram_addr), .sdram_dqm(sdram_dqm), .sdram_dq_out(sdram_dq_out),
        .sdram_dq_oe(sdram_dq_oe), .sdram_dq_in(sdram_dq_in)
    );

    wire        swap_req, swap_done, front, pal_we;
    wire [7:0]  pal_addr;
    wire [23:0] pal_data;

    generate
        if (SCANOUT == 2) begin : hd
            fb_scanout_hd #(
                .SCALE(SCALE), .EDGE(EDGE), .WIDTH(WIDTH), .HEIGHT(HEIGHT), .LINE_WORDS(LINE_WORDS), .H_VISIBLE(H_VISIBLE), .H_FRONT(H_FRONT), .H_SYNC(H_SYNC), .H_BACK(H_BACK),
                .V_VISIBLE(V_VISIBLE), .V_FRONT(V_FRONT), .V_SYNC(V_SYNC), .V_BACK(V_BACK)
            ) scanout (
                .clk(clk), .rst(rst), .mem_ready(init_done), .x(x),
                .swap_req(swap_req), .swap_done(swap_done), .front(front),
                .line_req(line_req), .line_read(line_read), .line_bank(line_bank), .line_row(line_row),
                .rd_valid(rd_valid), .rd_data(rd_data),
                .pal_we(pal_we), .pal_addr(pal_addr), .pal_data(pal_data), .underrun(underrun),
                .clk_video(clk_video), .rst_video(rst_video), .hsync_out(hsync), .vsync_out(vsync), .de_out(de),
                .red(red), .green(green), .blue(blue)
            );
        end else begin : sd
            fb_scanout scanout (
                .clk(clk), .rst(rst), .mem_ready(init_done),
                .x(x), .y(y), .hsync(raw_hsync), .vsync(raw_vsync), .visible(visible),
                .swap_req(swap_req), .swap_done(swap_done), .front(front),
                .line_req(line_req), .line_read(line_read), .line_bank(line_bank), .line_row(line_row),
                .rd_valid(rd_valid), .rd_data(rd_data),
                .pal_we(pal_we), .pal_addr(pal_addr), .pal_data(pal_data),
                .hsync_out(hsync), .vsync_out(vsync), .de_out(de),
                .red(red), .green(green), .blue(blue), .underrun(underrun)
            );
        end
    endgenerate

    wire       fifo_valid, fifo_pop;
    wire [7:0] fifo_data;

    byte_fifo rx_fifo (
        .clk(clk), .rst(rst), .in_valid(rx_valid), .in_data(rx_data),
        .out_valid(fifo_valid), .out_data(fifo_data), .out_pop(fifo_pop),
        .used(rx_used), .overflow(rx_overflow)
    );

    wire        pkt_valid, pkt_crc_ok, pkt_ack;
    wire [7:0]  pkt_type, pkt_seq, buf_q;
    wire [10:0] pkt_len;
    wire [9:0]  buf_addr;

    pkt_parser #(.IDLE_TIMEOUT(IDLE_TIMEOUT)) parser (
        .clk(clk), .rst(rst), .in_valid(fifo_valid), .in_data(fifo_data), .in_pop(fifo_pop),
        .pkt_valid(pkt_valid), .pkt_crc_ok(pkt_crc_ok), .pkt_type(pkt_type), .pkt_seq(pkt_seq),
        .pkt_len(pkt_len), .pkt_ack(pkt_ack), .buf_addr(buf_addr), .buf_q(buf_q)
    );

    wire       reply_start, reply_busy;
    wire [7:0] reply_type, reply_arg0, reply_arg1;

    // The executor waits while the rasterizer runs, so only one of them uses memory at a time.
    wire        exec_wr_valid, raster_wr_valid, raster_start, raster_done, raster_bad, raster_busy;
    wire [1:0]  raster_op;
    wire [15:0] raster_value;
    wire [1:0]  exec_wr_bank, raster_wr_bank;
    wire [10:0] exec_wr_row, raster_wr_row;
    wire [7:0]  exec_wr_col, raster_wr_col;
    wire [31:0] exec_wr_data, raster_wr_data;
    wire [3:0]  exec_wr_be, raster_wr_be;
    wire [9:0]  exec_buf_addr, raster_buf_addr;

    wire        store_we, raster_from_store;
    wire [7:0]  store_slot, store_data, list_mode, store_q;
    wire [2:0]  store_byte;
    wire [23:0] list_slots, list_color;
    wire [7:0]  raster_buf_q = raster_from_store ? store_q : buf_q;

    wire        read_start, read_done, reader_tx_valid, reply_tx_valid;
    wire [1:0]  read_bank;
    wire [9:0]  read_x_start, read_x_end, read_y_start, read_y_end;
    wire [7:0]  reader_tx_data, reply_tx_data;
    assign tx_valid = reader_busy ? reader_tx_valid : reply_tx_valid;
    assign tx_data  = reader_busy ? reader_tx_data : reply_tx_data;

    assign wr_valid = raster_busy ? raster_wr_valid : exec_wr_valid;
    assign wr_bank  = raster_busy ? raster_wr_bank : exec_wr_bank;
    assign wr_row   = raster_busy ? raster_wr_row : exec_wr_row;
    assign wr_col   = raster_busy ? raster_wr_col : exec_wr_col;
    assign wr_data  = raster_busy ? raster_wr_data : exec_wr_data;
    assign wr_be    = raster_busy ? raster_wr_be : exec_wr_be;
    assign buf_addr = raster_busy ? raster_buf_addr : exec_buf_addr;

    cmd_exec #(.WIDTH(WIDTH), .HEIGHT(HEIGHT), .LINE_WORDS(LINE_WORDS)) exec (
        .clk(clk), .rst(rst),
        .pkt_valid(pkt_valid), .pkt_crc_ok(pkt_crc_ok), .pkt_type(pkt_type), .pkt_seq(pkt_seq),
        .pkt_len(pkt_len), .pkt_ack(pkt_ack), .buf_addr(exec_buf_addr), .buf_q(buf_q),
        .front(front), .swap_req(swap_req), .swap_done(swap_done),
        .wr_valid(exec_wr_valid), .wr_ready(wr_ready), .wr_bank(exec_wr_bank), .wr_row(exec_wr_row),
        .wr_col(exec_wr_col), .wr_data(exec_wr_data), .wr_be(exec_wr_be),
        .pal_we(pal_we), .pal_addr(pal_addr), .pal_data(pal_data),
        .reply_start(reply_start), .reply_type(reply_type), .reply_arg0(reply_arg0),
        .reply_arg1(reply_arg1), .reply_busy(reply_busy),
        .raster_start(raster_start), .raster_op(raster_op), .raster_value(raster_value),
        .raster_done(raster_done), .raster_bad_value(raster_bad),
        .store_we(store_we), .store_slot(store_slot), .store_byte(store_byte), .store_data(store_data),
        .raster_from_store(raster_from_store), .list_mode(list_mode), .list_slots(list_slots), .list_color(list_color),
        .read_start(read_start), .read_bank(read_bank), .read_x_start(read_x_start), .read_x_end(read_x_end),
        .read_y_start(read_y_start), .read_y_end(read_y_end), .read_done(read_done)
    );

    vertex_store vertices (
        .clk(clk), .we(store_we), .wr_slot(store_slot), .wr_byte(store_byte), .wr_data(store_data),
        .mode(list_mode), .slots(list_slots), .color(list_color), .addr(raster_buf_addr), .q(store_q)
    );

    frame_reader reader (
        .clk(clk), .rst(rst), .start(read_start), .seq(pkt_seq), .bank(read_bank),
        .x_start(read_x_start), .x_end(read_x_end), .y_start(read_y_start), .y_end(read_y_end),
        .busy(reader_busy), .done(read_done),
        .rr_valid(reader_rr_valid), .rr_ready(rr_ready), .rr_bank(reader_rr_bank), .rr_row(reader_rr_row),
        .rr_col(reader_rr_col), .rr_len(reader_rr_len), .rr_done(rr_done), .rr_data(rd_data),
        .tx_valid(reader_tx_valid), .tx_data(reader_tx_data), .tx_ready(tx_ready)
    );

    raster #(.WIDTH(WIDTH), .HEIGHT(HEIGHT)) triangles (
        .clk(clk), .rst(rst), .start(raster_start), .op(raster_op), .clear_value(raster_value),
        .done(raster_done), .bad_value(raster_bad),
        .busy(raster_busy), .buf_addr(raster_buf_addr), .buf_q(raster_buf_q), .back_bank({1'b0, ~front}),
        .wr_valid(raster_wr_valid), .wr_ready(wr_ready), .wr_bank(raster_wr_bank),
        .wr_row(raster_wr_row), .wr_col(raster_wr_col), .wr_data(raster_wr_data), .wr_be(raster_wr_be),
        .rr_valid(raster_rr_valid), .rr_ready(rr_ready), .rr_bank(raster_rr_bank), .rr_row(raster_rr_row),
        .rr_col(raster_rr_col), .rr_len(raster_rr_len), .rr_done(rr_done), .rr_data(rd_data)
    );

    reply_tx replies (
        .clk(clk), .rst(rst), .start(reply_start), .reply_type(reply_type), .arg0(reply_arg0),
        .arg1(reply_arg1), .busy(reply_busy), .tx_valid(reply_tx_valid), .tx_data(reply_tx_data),
        .tx_ready(tx_ready && !reader_busy)
    );

endmodule
