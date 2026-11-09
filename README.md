# ramgen

A lightweight Python package for analyzing SystemVerilog RAM instances and generating wrapper modules, reports, and testbenches.

## Project Layout

```text
ramgen/
    src/ramgen/               # package source code
        main.py                 # CLI entry + public ramgen() API
        ram_analyzer.py         # SV parsing and analysis
        ram_generator.py        # wrapper/top/report generation
        ram_simulation.py       # tb/flist/makefile generation
    examples/                 # user-facing example inputs
    output/                   # default generated outputs (runtime)
    dist/                     # wheel artifacts (build output)
    pyproject.toml
```

## Run with uv

Run from this repository. `.python-version` selects Python 3.12 and uv installs the locked dependencies:

```powershell
uv run ramgen --help
uv run ramgen examples/pcie_iip_rams.sv --output-dir output
```

Use `uv sync --locked` to prepare the environment ahead of time.

## Install

From this folder:

```bash
pip install . --no-build-isolation
```

If pip reports a setuptools build-dependency error, run this once first:

```bash
python -m pip install setuptools wheel
```

## Python API

```python
from ramgen import ramgen

result = ramgen(
    sv_file="pcie_iip_rams.sv",
    output_dir="output/",
    module_prefix="demo",
    file_prefix="gen",
    verbose=False,
)

print(result["output_dir"])
print(result["output_sv_path"])
```

## CLI

```bash
ramgen pcie_iip_rams.sv --output-dir ./output
```

For supported PCIe wrappers, validate the interface before generating artifacts:

```bash
ramgen /path/to/pcie_iip_rams.sv --output-dir ./output
```

Analysis recognizes `ram_1p_wrapper`, `ram_1p_be_wrapper`,
`ram_2p_1c_wrapper`, and `ram_2p_2c_wrapper` explicitly. Each instance has an
`interface` entry describing clock roles, port directions, width expressions,
resolved widths, and connections. BE interfaces use 8-bit lanes with a possibly
short final lane and require `WEW == ceil(WD / 8)`.

The analyzer checks required parameters and ports, positive dimensions and read
latency, address capacity, unexpected ports, and unconnected inputs. Diagnostics
are returned both per instance and in `report["diagnostics"]`. `analyze_sv_file(...)` returns diagnostics for inspection. The CLI and
`ramgen(...)` stop on validation errors before writing generated artifacts. `validation_passed` means no detected errors, not full SV
elaboration: unknown RAM types and unresolved parameter expressions produce
warnings. Connected expression widths and memory collision behavior are not
validated. Read latency metadata does not change the generated model's current
fixed one-cycle read implementation.

## Generated testbench

The combined testbench checks every address with zero, one, and full-width
seeded random data. It also checks disabled writes (both write controls for
dual-port RAMs), and output hold while the dual-port read enable is low.
BE cases exercise each byte-enable bit and its inverse mask at every address,
including a short final byte. The directed BE scoreboard indexes data bits by
`bit / 8` independently of the generated model's lane loops.

Failures accumulate per instance and end with `$fatal` instead of a PASS message.
A depth/lane-based watchdog catches stalled tests. The generated VCS makefile
also requires the final completion marker so simulator fatal errors propagate
as a failed `make` even if the simulator itself returns zero.

These tests target the generated one-cycle behavioral wrappers directly;
top-level connectivity, variable read latency, and simultaneous read/write
collision semantics are not covered. Run `python -m unittest discover -s test -v`
for regressions; HDL tests, including injected write-enable, mask, and upper-data
faults, run when VCS is available.

## Notes

- The report is generated automatically as an Excel .xls file in the output directory.
- No external xlwt dependency is required.
- RAM information is exported to `output_dir/raminfo.csv`.
- Example input file is located in `examples/pcie_iip_rams.sv`.
