// Drives the FT2232H's synchronous FIFO pins (FT245 style), everything on the chip's own 60 MHz clock.
// A byte moves at a clock edge where the chip's flag and our strobe are both low: RXF# with RD#, or
// TXE# with WR#. Timing numbers and the order of signals are VERIFY items in docs/verify.md.
//
// Reading: OE# goes low first so the chip drives the data pins, and RD# follows one clock later.
// Writing: we drive the data pins only after OE# has been high for a clock, so that nobody fights.
// Replies go first, because the PC stops sending when it is waiting for them.
`timescale 1ns / 1ps

module ft_bus (
    input  wire       clk,
    input  wire       rst,

    input  wire       ft_rxf_n,
    input  wire       ft_txe_n,
    output reg        ft_oe_n,
    output reg        ft_rd_n,
    output reg        ft_wr_n,
    input  wire [7:0] ft_d_in,
    output reg  [7:0] ft_d_out,
    output reg        ft_d_oe,

    output reg        rx_valid,       // one clock per byte read from the chip
    output reg  [7:0] rx_data,
    input  wire       rx_room,        // low: read no more. There must be room for 2 bytes still to arrive

    input  wire       tx_valid,       // the next byte to send
    input  wire [7:0] tx_data,
    output wire       tx_pop
);

    localparam S_IDLE = 2'd0, S_READ_TURN = 2'd1, S_READ = 2'd2, S_WRITE = 2'd3;
    reg [1:0] state;

    // With no clock from the chip, reset cannot take effect, so these starting values are all that keeps
    // the FPGA off the chip's pins until the PC software starts the clock.
    initial begin
        ft_oe_n = 1'b1;
        ft_rd_n = 1'b1;
        ft_wr_n = 1'b1;
        ft_d_oe = 1'b0;
    end

    wire read_done  = !ft_rd_n && !ft_rxf_n;
    wire write_done = !ft_wr_n && !ft_txe_n;
    wire want_read  = !ft_rxf_n && rx_room;

    // A byte offered while TXE# is high was not taken, so it stays in the output register to offer again.
    reg  holding;
    wire can_load = !holding || write_done;
    wire loading  = state == S_WRITE && can_load && tx_valid;
    assign tx_pop = loading;

    always @(posedge clk) begin
        rx_valid <= 1'b0;
        if (rst) begin
            state    <= S_IDLE;
            ft_oe_n  <= 1'b1;
            ft_rd_n  <= 1'b1;
            ft_wr_n  <= 1'b1;
            ft_d_oe  <= 1'b0;
            ft_d_out <= 8'd0;
            holding  <= 1'b0;
        end else begin
            if (read_done) begin
                rx_valid <= 1'b1;
                rx_data  <= ft_d_in;
            end

            case (state)
                S_IDLE: begin
                    // Every way into this state has just released the pins, which gives the turnaround clock.
                    if (tx_valid && !ft_txe_n) begin
                        ft_d_oe <= 1'b1;
                        state   <= S_WRITE;
                    end else if (want_read) begin
                        ft_oe_n <= 1'b0;
                        state   <= S_READ_TURN;
                    end
                end

                S_READ_TURN: begin
                    ft_rd_n <= !want_read;
                    state   <= S_READ;
                end

                S_READ: begin
                    // A gap in the data keeps OE# low, because turning the bus round again costs clocks.
                    if (!rx_room || (tx_valid && !ft_txe_n)) begin
                        ft_rd_n <= 1'b1;
                        ft_oe_n <= 1'b1;
                        state   <= S_IDLE;
                    end else begin
                        ft_rd_n <= ft_rxf_n;
                    end
                end

                S_WRITE: begin
                    if (write_done) holding <= 1'b0;
                    if (loading) begin
                        ft_d_out <= tx_data;
                        holding  <= 1'b1;
                    end
                    if (loading || (holding && !write_done)) begin
                        // Offer the byte only when the chip said it has room. A refused byte is held.
                        ft_wr_n <= ft_txe_n;
                    end else begin
                        ft_wr_n <= 1'b1;
                        if (!holding || write_done) begin
                            ft_d_oe <= 1'b0;
                            state   <= S_IDLE;
                        end
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
