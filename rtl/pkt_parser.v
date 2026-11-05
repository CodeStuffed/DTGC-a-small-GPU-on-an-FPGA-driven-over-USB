// Packet parser: finds packets in the byte stream and checks both checksums. The payload goes into
// block RAM first, so nothing is drawn from a packet until the whole of it has been checked.
// Format: docs/protocol.md. The resynchronising rules must stay the same as sw/dtgc/protocol.py.
`timescale 1ns / 1ps

module pkt_parser #(
    parameter MAX_PAYLOAD = 1024,
    parameter IDLE_TIMEOUT = 65535   // clocks with no byte before a half-received packet is dropped
) (
    input  wire        clk,
    input  wire        rst,

    input  wire        in_valid,
    input  wire [7:0]  in_data,
    output wire        in_pop,

    output reg         pkt_valid,    // holds until pkt_ack
    output reg         pkt_crc_ok,
    output reg  [7:0]  pkt_type,
    output reg  [7:0]  pkt_seq,
    output reg  [10:0] pkt_len,
    input  wire        pkt_ack,

    input  wire [9:0]  buf_addr,     // payload read port, one clock of delay
    output reg  [7:0]  buf_q
);

    `include "rtl/crc.vh"

    localparam SYNC_BYTE = 8'hD7;
    localparam VERSION   = 8'd1;

    localparam S_SYNC = 3'd0, S_HEADER = 3'd1, S_PAYLOAD = 3'd2, S_CRC0 = 3'd3, S_CRC1 = 3'd4, S_DONE = 3'd5;

    reg [2:0]  state;
    reg [2:0]  header_index;
    reg [7:0]  version, len_low, len_high;
    reg [7:0]  header_crc;
    reg [15:0] body_crc;
    reg [7:0]  crc_low;
    reg [10:0] pay_index;
    reg [15:0] idle_count;

    wire [15:0] length = {len_high, len_low};

    reg [7:0] mem [0:MAX_PAYLOAD - 1];

    assign in_pop = in_valid && state != S_DONE;

    always @(posedge clk) begin
        if (in_pop && state == S_PAYLOAD) mem[pay_index[9:0]] <= in_data;
        buf_q <= mem[buf_addr];
    end

    always @(posedge clk) begin
        if (rst) begin
            state      <= S_SYNC;
            pkt_valid  <= 1'b0;
            idle_count <= 16'd0;
        end else if (state == S_DONE) begin
            if (pkt_ack) begin
                pkt_valid <= 1'b0;
                state     <= S_SYNC;
            end
        end else if (in_pop) begin
            idle_count <= 16'd0;
            case (state)
                S_SYNC: if (in_data == SYNC_BYTE) begin
                    state        <= S_HEADER;
                    header_index <= 3'd0;
                    header_crc   <= 8'h00;
                    body_crc     <= 16'hFFFF;
                end
                S_HEADER: begin
                    header_crc   <= crc8_next(header_crc, in_data);
                    body_crc     <= crc16_next(body_crc, in_data);
                    header_index <= header_index + 1'b1;
                    case (header_index)
                        3'd0: version  <= in_data;
                        3'd1: pkt_type <= in_data;
                        3'd2: pkt_seq  <= in_data;
                        3'd3: len_low  <= in_data;
                        3'd4: len_high <= in_data;
                        default: begin  // the header CRC byte
                            pkt_len   <= length[10:0];
                            pay_index <= 11'd0;
                            if (in_data != header_crc || version != VERSION || length > MAX_PAYLOAD)
                                state <= S_SYNC;
                            else
                                state <= (length == 0) ? S_CRC0 : S_PAYLOAD;
                        end
                    endcase
                end
                S_PAYLOAD: begin
                    body_crc  <= crc16_next(body_crc, in_data);
                    pay_index <= pay_index + 1'b1;
                    if (pay_index + 1'b1 == pkt_len) state <= S_CRC0;
                end
                S_CRC0: begin
                    crc_low <= in_data;
                    state   <= S_CRC1;
                end
                S_CRC1: begin
                    pkt_crc_ok <= {in_data, crc_low} == body_crc;
                    pkt_valid  <= 1'b1;
                    state      <= S_DONE;
                end
                default: state <= S_SYNC;
            endcase
        end else if (state != S_SYNC) begin
            // A cable pulled mid-packet must not swallow the start of the next one.
            idle_count <= idle_count + 1'b1;
            if (idle_count == IDLE_TIMEOUT) begin
                state      <= S_SYNC;
                idle_count <= 16'd0;
            end
        end
    end

endmodule
