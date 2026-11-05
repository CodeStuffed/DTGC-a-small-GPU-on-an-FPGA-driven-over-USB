// Builds one reply packet (always a 2-byte payload) and sends it a byte at a time.
`timescale 1ns / 1ps

module reply_tx (
    input  wire       clk,
    input  wire       rst,
    input  wire       start,      // pulse, only while busy is low
    input  wire [7:0] reply_type,
    input  wire [7:0] arg0,
    input  wire [7:0] arg1,
    output wire       busy,
    output wire       tx_valid,
    output reg  [7:0] tx_data,
    input  wire       tx_ready
);

    `include "rtl/crc.vh"

    reg [3:0]  index;       // bytes sent so far; 11 means idle
    reg [7:0]  type_reg, arg0_reg, arg1_reg;
    reg [7:0]  header_crc;
    reg [15:0] body_crc;

    assign busy = index != 4'd11;
    assign tx_valid = busy;

    always @* begin
        case (index)
            4'd0:    tx_data = 8'hD7;
            4'd1:    tx_data = 8'd1;
            4'd2:    tx_data = type_reg;
            4'd3:    tx_data = 8'd0;   // replies carry no sequence number of their own
            4'd4:    tx_data = 8'd2;
            4'd5:    tx_data = 8'd0;
            4'd6:    tx_data = header_crc;
            4'd7:    tx_data = arg0_reg;
            4'd8:    tx_data = arg1_reg;
            4'd9:    tx_data = body_crc[7:0];
            default: tx_data = body_crc[15:8];
        endcase
    end

    always @(posedge clk) begin
        if (rst) begin
            index <= 4'd11;
        end else if (!busy) begin
            if (start) begin
                index      <= 4'd0;
                type_reg   <= reply_type;
                arg0_reg   <= arg0;
                arg1_reg   <= arg1;
                header_crc <= 8'h00;
                body_crc   <= 16'hFFFF;
            end
        end else if (tx_ready) begin
            index <= index + 1'b1;
            if (index >= 4'd1 && index <= 4'd5) header_crc <= crc8_next(header_crc, tx_data);
            if (index >= 4'd1 && index <= 4'd8) body_crc <= crc16_next(body_crc, tx_data);
        end
    end

endmodule
