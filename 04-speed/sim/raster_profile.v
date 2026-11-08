// A second top module for the testbench named by PROFILE_TB: counts the clocks the rasterizer spends in each state, to show where the
// time goes. Usage: scripts/profile_raster.py. Rewrites the file named by +profile= after every triangle.
`timescale 1ns / 1ps
`ifndef PROFILE_TB
`define PROFILE_TB gpu_core_tb
`endif

module raster_profile;
    integer counts [0:31];
    integer inside_pixels = 0, outside_pixels = 0, depth_fails = 0, triangles = 0;
    integer i, fd;
    reg [1023:0] path;
    reg have_path;

    initial begin
        for (i = 0; i < 32; i = i + 1) counts[i] = 0;
        have_path = $value$plusargs("profile=%s", path);
    end

    always @(posedge `PROFILE_TB.clk) begin
        counts[`PROFILE_TB.dut.triangles.state] = counts[`PROFILE_TB.dut.triangles.state] + 1;
        if (`PROFILE_TB.dut.triangles.state == 5'd15) begin  // S_PIXEL
            if (!`PROFILE_TB.dut.triangles.inside) outside_pixels = outside_pixels + 1;
        end
        if (`PROFILE_TB.dut.triangles.state == 5'd23 && have_path) begin  // S_FINISH
            triangles = triangles + 1;
            fd = $fopen(path, "w");
            $fdisplay(fd, "triangles %0d", triangles);
            $fdisplay(fd, "outside_pixels %0d", outside_pixels);
            for (i = 0; i < 32; i = i + 1) if (counts[i] != 0) $fdisplay(fd, "state%0d %0d", i, counts[i]);
            $fclose(fd);
        end
    end
endmodule
