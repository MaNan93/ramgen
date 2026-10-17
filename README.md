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

## Notes

- The report is generated automatically as an Excel .xls file in the output directory.
- No external xlwt dependency is required.
- RAM information is exported to `output_dir/raminfo.csv`.
- Example input file is located in `examples/pcie_iip_rams.sv`.
