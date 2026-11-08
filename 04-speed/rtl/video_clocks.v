// Makes the video clocks from the 27 MHz board clock using Gowin's PLL and clock divider.
// clk_serial = 27 x (FBDIV_SEL + 1) / (IDIV_SEL + 1), clk_pixel = clk_serial / 5.
// The defaults give 27 x 14 / 3 = 126 MHz and 25.2 MHz. clk_slow = clk_serial / SDIV_SEL, for the HD version's core.
// Settings come from Apicula's examples/DVI/pll480.v, with DEVICE changed for this chip.
// VERIFY on hardware: formula and VCO range against Gowin UG286 (see docs/verify.md).
`timescale 1ns / 1ps

module video_clocks #(
    parameter IDIV_SEL  = 2,
    parameter FBDIV_SEL = 13,
    parameter ODIV_SEL  = 4,
    parameter SDIV_SEL  = 2
) (
    input  wire clk_27,
    output wire clk_serial,
    output wire clk_pixel,
    output wire clk_slow,
    output wire locked
);

    wire gnd = 1'b0;

    rPLL #(
        .FCLKIN("27"),
        .DYN_IDIV_SEL("false"),
        .IDIV_SEL(IDIV_SEL),
        .DYN_FBDIV_SEL("false"),
        .FBDIV_SEL(FBDIV_SEL),
        .DYN_ODIV_SEL("false"),
        .ODIV_SEL(ODIV_SEL),
        .PSDA_SEL("0000"),
        .DYN_DA_EN("true"),
        .DUTYDA_SEL("1000"),
        .CLKOUT_FT_DIR(1'b1),
        .CLKOUTP_FT_DIR(1'b1),
        .CLKOUT_DLY_STEP(0),
        .CLKOUTP_DLY_STEP(0),
        .CLKFB_SEL("internal"),
        .CLKOUT_BYPASS("false"),
        .CLKOUTP_BYPASS("false"),
        .CLKOUTD_BYPASS("false"),
        .DYN_SDIV_SEL(SDIV_SEL),
        .CLKOUTD_SRC("CLKOUT"),
        .CLKOUTD3_SRC("CLKOUT"),
        .DEVICE("GW2A-18")
    ) pll (
        .CLKOUT(clk_serial),
        .LOCK(locked),
        .CLKOUTP(),
        .CLKOUTD(clk_slow),
        .CLKOUTD3(),
        .RESET(gnd),
        .RESET_P(gnd),
        .CLKIN(clk_27),
        .CLKFB(gnd),
        .FBDSEL({6{gnd}}),
        .IDSEL({6{gnd}}),
        .ODSEL({6{gnd}}),
        .PSDA({4{gnd}}),
        .DUTYDA({4{gnd}}),
        .FDLY({4{gnd}})
    );

    CLKDIV #(.DIV_MODE("5")) divider (
        .CLKOUT(clk_pixel),
        .HCLKIN(clk_serial),
        .RESETN(locked),
        .CALIB(1'b1)
    );

endmodule
