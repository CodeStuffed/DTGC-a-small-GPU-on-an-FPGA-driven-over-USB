# The HD version's slow clock for the core and SDRAM. Everything else follows --freq, the video clock.
create_clock -period 20.83 -name clk_core [get_nets {clk_core}]
