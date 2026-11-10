// Holds the corners sent by VERTICES, and shows one TRIANGLE_LIST record to the rasterizer as if it were
// a TRIANGLE payload, so the rasterizer does not change. One clock of read delay, like the payload RAM.
`timescale 1ns / 1ps

module vertex_store (
    input  wire        clk,

    input  wire        we,
    input  wire [7:0]  wr_slot,
    input  wire [2:0]  wr_byte,      // x, y, z: 2 bytes each
    input  wire [7:0]  wr_data,

    input  wire [7:0]  mode,
    input  wire [23:0] slots,        // third corner, second, first
    input  wire [23:0] color,        // blue, green, red

    input  wire [9:0]  addr,
    output wire [7:0]  q
);

    reg [7:0] store [0:2047];
    reg [7:0] stored, direct;
    reg       use_store;

    // A TRIANGLE payload: mode, texture row (2 bytes), texture size, then 3 corners of 11 bytes each,
    // which are x, y, z (2 bytes each), red, green, blue, u, v.
    reg [7:0] corner_slot;
    reg [3:0] place;
    reg       on_corner;
    always @* begin
        on_corner   = 1'b1;
        corner_slot = slots[7:0];
        place       = 4'd0;
        if (addr >= 10'd26) begin
            corner_slot = slots[23:16];
            place       = addr[3:0] - 4'd10;  // 26 is 10 in its low 4 bits, and 36 is the last address
        end else if (addr >= 10'd15) begin
            corner_slot = slots[15:8];
            place       = addr - 10'd15;
        end else if (addr >= 10'd4) begin
            place       = addr - 10'd4;
        end else begin
            on_corner   = 1'b0;
        end
    end

    assign q = use_store ? stored : direct;

    always @(posedge clk) begin
        if (we) store[{wr_slot, wr_byte}] <= wr_data;
        stored    <= store[{corner_slot, place[2:0]}];
        use_store <= on_corner && place < 4'd6;
        if (!on_corner) direct <= (addr == 10'd0) ? mode : 8'd0;
        else case (place)
            4'd6:    direct <= color[7:0];
            4'd7:    direct <= color[15:8];
            4'd8:    direct <= color[23:16];
            default: direct <= 8'd0;
        endcase
    end

endmodule
