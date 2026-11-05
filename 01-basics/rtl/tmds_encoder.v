// TMDS encoder for one DVI lane: 8 data bits or 2 control bits become 10 bits.
// Follows the encoding algorithm in the DVI 1.0 specification. Output is LATENCY = 4 clocks late, which all three
// lanes share, and split into stages so it can keep up with the video clock of the HD modes.
`timescale 1ns / 1ps

module tmds_encoder (
    input  wire       clk,
    input  wire       rst,      // synchronous, active high
    input  wire       de,       // 1 = send data, 0 = send control
    input  wire [1:0] ctrl,
    input  wire [7:0] data,
    output reg  [9:0] tmds
);

    function [3:0] ones8(input [7:0] v);
        ones8 = v[0] + v[1] + v[2] + v[3] + v[4] + v[5] + v[6] + v[7];
    endfunction

    // Stage 1: pick XOR or XNOR so the output has fewer transitions.
    reg  [7:0] data1;
    reg        use_xnor1;
    wire [3:0] data_ones = ones8(data);

    // Stage 2: the first 9 bits.
    reg  [8:0] q_m;
    reg  [8:0] q_m2;
    integer    i;
    always @* begin
        q_m[0] = data1[0];
        for (i = 1; i < 8; i = i + 1)
            q_m[i] = use_xnor1 ? ~(q_m[i-1] ^ data1[i]) : (q_m[i-1] ^ data1[i]);
        q_m[8] = ~use_xnor1;
    end

    // Stage 3: how far those bits lean towards ones or zeros. balance is half of (ones - zeros).
    reg  [8:0]        q_m3;
    reg  signed [5:0] balance;
    wire [3:0]        q_ones = ones8(q_m2[7:0]);

    // de and ctrl travel along with the data.
    reg  [3:1] de_d;
    reg  [1:0] ctrl_d [1:3];

    always @(posedge clk) begin
        data1     <= data;
        use_xnor1 <= (data_ones > 4'd4) || (data_ones == 4'd4 && data[0] == 1'b0);
        q_m2      <= q_m;
        q_m3      <= q_m2;
        balance   <= $signed({2'b00, q_ones}) - 6'sd4;
        de_d      <= rst ? 3'b000 : {de_d[2:1], de};
        ctrl_d[1] <= rst ? 2'b00 : ctrl;
        ctrl_d[2] <= rst ? 2'b00 : ctrl_d[1];
        ctrl_d[3] <= rst ? 2'b00 : ctrl_d[2];
    end

    // Stage 4: choose whether to invert so the line stays DC balanced.
    // disparity is the running count of ones minus zeros.
    reg  signed [5:0] disparity = 6'sd0;

    wire signed [5:0] q8_term  = q_m3[8] ? 6'sd1 : 6'sd0;
    wire signed [5:0] nq8_term = q_m3[8] ? 6'sd0 : 6'sd1;

    always @(posedge clk) begin
        if (rst) begin
            tmds      <= 10'b1101010100;
            disparity <= 6'sd0;
        end else if (!de_d[3]) begin
            disparity <= 6'sd0;
            case (ctrl_d[3])
                2'b00: tmds <= 10'b1101010100;
                2'b01: tmds <= 10'b0010101011;
                2'b10: tmds <= 10'b0101010100;
                2'b11: tmds <= 10'b1010101011;
            endcase
        end else if (disparity == 0 || balance == 0) begin
            tmds[9]   <= ~q_m3[8];
            tmds[8]   <= q_m3[8];
            tmds[7:0] <= q_m3[8] ? q_m3[7:0] : ~q_m3[7:0];
            disparity <= q_m3[8] ? disparity + 2 * balance : disparity - 2 * balance;
        end else if ((disparity > 0 && balance > 0) || (disparity < 0 && balance < 0)) begin
            tmds[9]   <= 1'b1;
            tmds[8]   <= q_m3[8];
            tmds[7:0] <= ~q_m3[7:0];
            disparity <= disparity + 2 * q8_term - 2 * balance;
        end else begin
            tmds[9]   <= 1'b0;
            tmds[8]   <= q_m3[8];
            tmds[7:0] <= q_m3[7:0];
            disparity <= disparity - 2 * nq8_term + 2 * balance;
        end
    end

endmodule
