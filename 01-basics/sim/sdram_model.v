// Behavioural model of a 2M x 32 SDR SDRAM with rule checks, for simulation only.
// It stops being kind to the design on purpose: read data is only valid for the window a real chip
// would give (X outside it), unwritten memory reads as X, and bad command sequences are errors.
// Timing limits are typical values for this class of chip, not from the real part's datasheet,
// which is not known (docs/verify.md).
`timescale 1ns / 1ps

module sdram_model #(
    parameter real T_AC = 6.0,        // clock to read data valid
    parameter real T_OH = 2.5,        // read data hold after the next clock
    parameter real T_RCD_NS = 20.0,
    parameter real T_RP_NS = 20.0,
    parameter real T_RAS_NS = 42.0,
    parameter real T_RC_NS = 63.0,
    parameter real T_RRD_NS = 14.0,
    parameter real T_WR_NS = 15.0,
    parameter T_WR_CLOCKS = 3,        // the margin the controller promises, as chips also state this in clocks
    parameter real T_INIT_NS = 100000.0,
    parameter REFRESH_ROWS = 4096,
    parameter real REFRESH_WINDOW_NS = 64000000.0,
    parameter MAX_MESSAGES = 20
) (
    input  wire        clk,
    input  wire        cke,
    input  wire        cs_n,
    input  wire        ras_n,
    input  wire        cas_n,
    input  wire        we_n,
    input  wire [1:0]  ba,
    input  wire [10:0] addr,
    input  wire [3:0]  dqm,
    inout  wire [31:0] dq
);

    reg [31:0] mem [0:(1 << 21) - 1];

    integer errors = 0;
    integer reads = 0, writes = 0, refreshes = 0;
    integer init_refreshes = 0;
    integer max_refresh_window_us = 0;

    reg        mode_set = 1'b0;
    reg        active [0:3];
    reg [10:0] open_row [0:3];
    realtime   t_active [0:3];
    realtime   t_precharge [0:3];
    realtime   t_last_write [0:3];
    integer    clock_count = 0;
    integer    clock_last_write [0:3];
    realtime   t_last_refresh = -1.0e9;
    realtime   t_last_active = -1.0e9;
    realtime   refresh_ring [0:REFRESH_ROWS - 1];
    integer    ring_pos = 0;
    integer    bank_i;

    reg        pending = 1'b0;
    reg [31:0] pending_data;
    reg        drive = 1'b0;
    reg [31:0] drive_data;
    assign dq = drive ? drive_data : 32'bz;

    initial begin
        for (bank_i = 0; bank_i < 4; bank_i = bank_i + 1) begin
            active[bank_i] = 1'b0;
            open_row[bank_i] = 11'd0;
            t_active[bank_i] = -1.0e9;
            t_precharge[bank_i] = -1.0e9;
            t_last_write[bank_i] = -1.0e9;
            clock_last_write[bank_i] = -1000;
        end
    end

    task rule_error(input [8*48-1:0] message);
        begin
            if (errors < MAX_MESSAGES) $display("SDRAM ERROR at %0t ns: %0s", $realtime, message);
            errors = errors + 1;
        end
    endtask

    wire [20:0] access_addr = {ba, open_row[ba], addr[7:0]};
    wire [3:0]  command = {cs_n, ras_n, cas_n, we_n};

    task precharge_bank(input integer b);
        begin
            if (active[b]) begin
                if ($realtime - t_active[b] < T_RAS_NS) rule_error("tRAS: precharge too soon");
                if ($realtime - t_last_write[b] < T_WR_NS) rule_error("tWR: precharge after write");
                if (clock_count - clock_last_write[b] < T_WR_CLOCKS) rule_error("tWR: too few clocks after write");
                active[b] = 1'b0;
            end
            t_precharge[b] = $realtime;
        end
    endtask

    always @(posedge clk) begin
        clock_count = clock_count + 1;
        // Read data: last word holds until T_OH after this clock, the next arrives T_AC after it.
        drive_data <= #(T_OH) 32'bx;
        drive      <= #(T_OH) pending;
        if (pending) drive_data <= #(T_AC) pending_data;
        pending = 1'b0;

        if (cke !== 1'b1 && $realtime > 200.0) rule_error("CKE not high");

        if (^command === 1'bx) begin
            if ($realtime > 200.0) rule_error("command pins are X");
        end else if ($realtime < T_INIT_NS) begin
            if (command != 4'b0111 && command[3] == 1'b0) rule_error("command during power-up wait");
        end else case (command)
            4'b0011: begin  // ACTIVE
                if (!mode_set) rule_error("ACTIVE before mode set");
                if (active[ba]) rule_error("ACTIVE on an open bank");
                if ($realtime - t_precharge[ba] < T_RP_NS) rule_error("tRP: active after precharge");
                if ($realtime - t_active[ba] < T_RC_NS) rule_error("tRC: active to active");
                if ($realtime - t_last_refresh < T_RC_NS) rule_error("tRC: active after refresh");
                if ($realtime - t_last_active < T_RRD_NS) rule_error("tRRD: active after active");
                t_last_active = $realtime;
                if (^addr === 1'bx || ^ba === 1'bx) rule_error("ACTIVE address is X");
                active[ba] = 1'b1;
                open_row[ba] = addr;
                t_active[ba] = $realtime;
            end
            4'b0101: begin  // READ
                if (!active[ba]) rule_error("READ on a closed bank");
                if ($realtime - t_active[ba] < T_RCD_NS) rule_error("tRCD: read after active");
                if (addr[10] !== 1'b0) rule_error("READ with auto-precharge");
                if (dqm !== 4'b0000) rule_error("READ with DQM set");
                pending_data = mem[access_addr];
                pending = 1'b1;
                reads = reads + 1;
            end
            4'b0100: begin  // WRITE
                if (!active[ba]) rule_error("WRITE on a closed bank");
                if ($realtime - t_active[ba] < T_RCD_NS) rule_error("tRCD: write after active");
                if (addr[10] !== 1'b0) rule_error("WRITE with auto-precharge");
                if (^dqm === 1'bx) rule_error("WRITE with DQM X");
                if (drive === 1'b1) rule_error("WRITE while read data is on the pins");
                if (!dqm[0]) begin
                    if (^dq[7:0] === 1'bx) rule_error("WRITE data byte 0 is X or Z");
                    mem[access_addr][7:0] = dq[7:0];
                end
                if (!dqm[1]) begin
                    if (^dq[15:8] === 1'bx) rule_error("WRITE data byte 1 is X or Z");
                    mem[access_addr][15:8] = dq[15:8];
                end
                if (!dqm[2]) begin
                    if (^dq[23:16] === 1'bx) rule_error("WRITE data byte 2 is X or Z");
                    mem[access_addr][23:16] = dq[23:16];
                end
                if (!dqm[3]) begin
                    if (^dq[31:24] === 1'bx) rule_error("WRITE data byte 3 is X or Z");
                    mem[access_addr][31:24] = dq[31:24];
                end
                t_last_write[ba] = $realtime;
                clock_last_write[ba] = clock_count;
                writes = writes + 1;
            end
            4'b0010: begin  // PRECHARGE
                if (addr[10]) begin
                    for (bank_i = 0; bank_i < 4; bank_i = bank_i + 1) precharge_bank(bank_i);
                end else begin
                    precharge_bank(ba);
                end
            end
            4'b0001: begin  // REFRESH
                for (bank_i = 0; bank_i < 4; bank_i = bank_i + 1) begin
                    if (active[bank_i]) rule_error("REFRESH with a bank open");
                    if ($realtime - t_precharge[bank_i] < T_RP_NS) rule_error("tRP: refresh after precharge");
                end
                if ($realtime - t_last_refresh < T_RC_NS) rule_error("tRC: refresh to refresh");
                t_last_refresh = $realtime;
                if (!mode_set) init_refreshes = init_refreshes + 1;
                refreshes = refreshes + 1;
                // Each row is refreshed once every REFRESH_ROWS commands: that gap must fit the window.
                if (refreshes > REFRESH_ROWS) begin
                    if ($realtime - refresh_ring[ring_pos] > REFRESH_WINDOW_NS)
                        rule_error("refresh rate: a row went stale");
                    if (($realtime - refresh_ring[ring_pos]) / 1000.0 > max_refresh_window_us)
                        max_refresh_window_us = ($realtime - refresh_ring[ring_pos]) / 1000.0;
                end
                refresh_ring[ring_pos] = $realtime;
                ring_pos = (ring_pos + 1) % REFRESH_ROWS;
            end
            4'b0000: begin  // MODE REGISTER SET
                for (bank_i = 0; bank_i < 4; bank_i = bank_i + 1)
                    if (active[bank_i]) rule_error("MODE SET with a bank open");
                if (init_refreshes < 2) rule_error("MODE SET before 2 refreshes");
                if (addr[6:4] !== 3'b010) rule_error("CAS latency is not 2");
                if (addr[2:0] !== 3'b000) rule_error("burst length is not 1");
                mode_set = 1'b1;
            end
            4'b0111: ;      // NOP
            default: if (!cs_n) rule_error("unknown command");
        endcase
    end

endmodule
