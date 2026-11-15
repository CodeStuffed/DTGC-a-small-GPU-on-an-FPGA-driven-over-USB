# The HD version's slow clock for the core and SDRAM, and the FT2232H's clock. Everything else follows --freq, the video clock.
create_clock -period 20.83 -name clk_core [get_nets {clk_core}]
# After synthesis the port's net is called link.ft_clk. A constraint on the port itself is accepted but not applied.
create_clock -period 16.667 -name ft_clk [get_nets {link.ft_clk}]
