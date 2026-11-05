# Usage: run through run_cocotb.py (cocotb test for counter.v).
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge


async def tick(dut):
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)


@cocotb.test()
async def counts_holds_wraps_and_resets(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    dut.rst.value = 1
    dut.en.value = 0
    await tick(dut)
    assert int(dut.count.value) == 0

    dut.rst.value = 0
    await tick(dut)
    assert int(dut.count.value) == 0, "should hold while en is low"

    dut.en.value = 1
    for i in range(1, 17):
        await tick(dut)
        assert int(dut.count.value) == i % 16

    dut.rst.value = 1
    await tick(dut)
    assert int(dut.count.value) == 0, "reset should win over en"
