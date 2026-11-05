// CRC functions for the packet protocol (docs/protocol.md), one byte at a time.
// Include inside a module. sw/dtgc/protocol.py has the same two functions.

// CRC-8, polynomial 0x07, start value 0x00.
function [7:0] crc8_next(input [7:0] crc, input [7:0] data);
    integer i;
    reg [7:0] c;
    begin
        c = crc ^ data;
        for (i = 0; i < 8; i = i + 1)
            c = c[7] ? ((c << 1) ^ 8'h07) : (c << 1);
        crc8_next = c;
    end
endfunction

// CRC-16-CCITT, polynomial 0x1021, start value 0xFFFF.
function [15:0] crc16_next(input [15:0] crc, input [7:0] data);
    integer i;
    reg [15:0] c;
    begin
        c = crc ^ {data, 8'h00};
        for (i = 0; i < 8; i = i + 1)
            c = c[15] ? ((c << 1) ^ 16'h1021) : (c << 1);
        crc16_next = c;
    end
endfunction
