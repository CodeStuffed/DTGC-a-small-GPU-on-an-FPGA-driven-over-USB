# Usage: python sim/smoke/run_cocotb.py <build_dir>  (build_dir should be outside the project)
import sys
from pathlib import Path

from cocotb_tools.check_results import get_results
from cocotb_tools.runner import get_runner

here = Path(__file__).resolve().parent
build_dir = Path(sys.argv[1]).resolve()

sys.path.insert(0, str(here))
runner = get_runner("icarus")
runner.build(
    sources=[here / "counter.v"],
    hdl_toplevel="counter",
    build_dir=build_dir,
    always=True,
)
results = runner.test(
    hdl_toplevel="counter",
    test_module="test_counter",
    build_dir=build_dir,
    test_dir=build_dir,
)

# Outside pytest the runner does not check results itself, so a failed test would still exit 0.
num_tests, num_failed = get_results(results)
print(f"cocotb results: {num_tests} tests, {num_failed} failed")
sys.exit(1 if num_failed or num_tests == 0 else 0)
