# The FT2232H's 60 MHz clock. Everything else follows --freq on the build command.
# After synthesis the port's net is called link.ft_clk. A constraint on the port itself is accepted but not applied.
create_clock -period 16.667 -name ft_clk [get_nets {link.ft_clk}]
