#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAM Generator - Main Orchestration Module

Coordinates analysis, code generation, and simulation setup for SystemVerilog RAM wrappers.

Supported Python: >= 3.6.8

Examples:
    python ramgen.py
    python ramgen.py your_file.sv --output-dir ./output

Python API:
    from ramgen import ramgen

    result = ramgen(
        sv_file="pcie_iip_rams.sv",
        output_dir="output",
        module_prefix="demo",
        file_prefix="gen",
        verbose=True,
    )

    print(result["excel_path"])
    print(result["wrapper_files"])

Notes:
    - output_dir is the generation directory, defaulting to ./output
    - a .xls report is always written into that directory
    - module_prefix changes generated module names
    - file_prefix changes generated file names

Module Structure:
    - ram_analyzer: SV file parsing and RAM instance analysis
    - ram_generator: SystemVerilog code generation (wrappers, top-level)
    - ram_simulation: Testbench and simulation infrastructure generation
"""

from __future__ import print_function

import argparse
import os
import sys

from .ram_analyzer import analyze_sv_file, print_human_readable
from .ram_generator import (
    export_excel,
    export_raminfo_csv,
    default_excel_path,
    generate_output_sv,
    generate_reference_modules,
)
from .ram_simulation import generate_testbenches, generate_flist, generate_tb_flist, generate_makefile


DEFAULT_SV_FILE_NAME = "pcie_iip_rams.sv"
DEFAULT_OUTPUT_DIR = os.path.join(".", "output")
DEFAULT_OUTPUT_SV_NAME = "pcie_ram.sv"


def build_default_input_not_found_message(missing_path):
    """Build a user-friendly error when the default SV input file is missing."""
    return (
        "default input file not found under current directory: {}\n"
        "tip: run from a directory tree containing {} or pass an explicit file path, "
        "for example: ramgen your_file.sv --output-dir ./output"
    ).format(missing_path, DEFAULT_SV_FILE_NAME)


def build_default_input_ambiguous_message(matches):
    """Build a user-friendly error for multiple default SV candidates."""
    lines = [
        "multiple default input files found under current directory:",
    ]
    for path in matches[:10]:
        lines.append("- {}".format(path))
    if len(matches) > 10:
        lines.append("- ... ({} more)".format(len(matches) - 10))
    lines.append("tip: pass an explicit file path, for example: ramgen your_file.sv --output-dir ./output")
    return "\n".join(lines)


def resolve_default_sv_file(default_name=DEFAULT_SV_FILE_NAME):
    """Resolve default SV file path from user-facing locations.

    Search recursively under the current working directory.

    Returns:
        Absolute path to the single matched file.

    Raises:
        FileNotFoundError: no match or ambiguous matches.
    """
    root_dir = os.path.abspath(os.getcwd())
    matches = []
    for walk_root, _, file_names in os.walk(root_dir):
        if default_name in file_names:
            matches.append(os.path.join(walk_root, default_name))

    matches = sorted(os.path.abspath(path) for path in matches)
    if not matches:
        raise FileNotFoundError(build_default_input_not_found_message(root_dir))
    if len(matches) > 1:
        raise FileNotFoundError(build_default_input_ambiguous_message(matches))
    return matches[0]


def normalize_name_prefix(prefix_value):
    """Normalize a prefix so non-empty values end with an underscore."""
    if not prefix_value:
        return ""
    return prefix_value if prefix_value.endswith("_") else prefix_value + "_"


def apply_file_prefix_to_name(name, file_prefix):
    """Add a normalized file prefix to a base file name without duplicating it."""
    normalized_file_prefix = normalize_name_prefix(file_prefix)
    if not normalized_file_prefix:
        return name
    return name if name.startswith(normalized_file_prefix) else normalized_file_prefix + name


def apply_module_prefix(report, module_prefix):
    """Return a copy of the report with prefixed generated module names."""
    normalized_module_prefix = normalize_name_prefix(module_prefix)
    copied_report = dict(report)
    copied_report["instances"] = []

    for item in report.get("instances", []):
        new_item = dict(item)
        reference = item.get("reference", item["type"])
        new_item["reference"] = normalized_module_prefix + reference if normalized_module_prefix else reference
        copied_report["instances"].append(new_item)

    copied_report["generated_top_module"] = normalized_module_prefix + "pcie_ram" if normalized_module_prefix else "pcie_ram"
    return copied_report


def build_output_layout(output_dir, sv_file, file_prefix=""):
    """Build the directory and file layout for generated artifacts."""
    output_dir = os.path.abspath(output_dir or DEFAULT_OUTPUT_DIR)
    tb_dir = os.path.join(output_dir, "tb")
    wrapper_dir = os.path.join(output_dir, "wrapper")
    return {
        "output_dir": output_dir,
        "wrapper_dir": wrapper_dir,
        "tb_dir": tb_dir,
        "excel": default_excel_path(sv_file, output_dir),
        "raminfo_csv": os.path.join(output_dir, "raminfo.csv"),
        "output_sv": os.path.join(output_dir, apply_file_prefix_to_name(DEFAULT_OUTPUT_SV_NAME, file_prefix)),
        "flist": os.path.join(output_dir, "flist.f"),
        "tb_flist": os.path.join(tb_dir, "flist.f"),
        "tb_module_name": "pcie_ram_tb",
        "makefile": os.path.join(tb_dir, "makefile"),
    }


def build_arg_parser():
    """Build command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Analyze a SystemVerilog RAM file and generate outputs."
    )
    parser.add_argument(
        "sv_file",
        nargs="?",
        default=None,
        help="Input SV file. Default: ./{} (current working directory preferred).".format(DEFAULT_SV_FILE_NAME),
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory. Default: ./output",
    )
    parser.add_argument(
        "--module-prefix",
        default="",
        help="Prefix for generated module names.",
    )
    parser.add_argument(
        "--file-prefix",
        default="",
        help="Prefix for generated file names.",
    )
    return parser


def ramgen(sv_file=None, output_dir=DEFAULT_OUTPUT_DIR, module_prefix="", file_prefix="", verbose=True):
    """Run RAM analysis and generation for direct Python reuse.

    Args:
        sv_file: Input SystemVerilog file path.
        output_dir: Output directory for generated Excel, SV, wrapper, tb, flist, and makefile files.
        module_prefix: Optional prefix added to all generated module names, for example prefix_.
        file_prefix: Optional prefix added to generated file names, for example gen_.
        verbose: Whether to print the analysis/generation log.

    Returns:
        A dict containing report data and generated file paths.
    """
    use_default_sv = not sv_file
    if use_default_sv:
        sv_file = resolve_default_sv_file()
    else:
        sv_file = os.path.abspath(sv_file)

    if not os.path.exists(sv_file):
        raise FileNotFoundError("file not found: {}".format(sv_file))

    normalized_module_prefix = normalize_name_prefix(module_prefix)
    normalized_file_prefix = normalize_name_prefix(file_prefix)
    report = analyze_sv_file(sv_file)
    generated_report = apply_module_prefix(report, normalized_module_prefix)
    layout = build_output_layout(output_dir, sv_file, file_prefix=normalized_file_prefix)

    if verbose:
        print_human_readable(report)

    export_excel(generated_report, layout["excel"])
    export_raminfo_csv(generated_report, layout["raminfo_csv"])
    output_sv_path = generate_output_sv(
        sv_file,
        layout["output_sv"],
        generated_report,
        top_module_name=generated_report.get("generated_top_module", "pcie_ram"),
    )
    written_files = generate_reference_modules(
        generated_report,
        layout["wrapper_dir"],
        file_prefix=normalized_file_prefix,
    )
    tb_files = generate_testbenches(
        generated_report,
        layout["tb_dir"],
        tb_module_name=layout["tb_module_name"],
    )
    design_files = [output_sv_path] + sorted(written_files)
    flist_path = generate_flist(design_files, layout["flist"])
    tb_flist_path = generate_tb_flist(flist_path, tb_files, layout["tb_flist"])
    makefile_path = generate_makefile(
        layout["makefile"],
        tb_flist_path,
        top_module_name=layout["tb_module_name"],
    )

    result = {
        "report": generated_report,
        "module_prefix": normalized_module_prefix,
        "file_prefix": normalized_file_prefix,
        "output_dir": layout["output_dir"],
        "top_module_name": generated_report.get("generated_top_module"),
        "excel_path": layout["excel"],
        "raminfo_csv_path": layout["raminfo_csv"],
        "output_sv_path": output_sv_path,
        "wrapper_files": written_files,
        "tb_files": tb_files,
        "flist_path": flist_path,
        "tb_flist_path": tb_flist_path,
        "makefile_path": makefile_path,
    }

    if verbose:
        print(
            "OK | out={} | wrappers={} | tb={} | xls={}".format(
                layout["output_dir"],
                len(written_files),
                len(tb_files),
                os.path.basename(layout["excel"]),
            )
        )

    return result


def main(argv=None):
    """CLI wrapper around ramgen."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    output_dir = os.path.abspath(args.output_dir or DEFAULT_OUTPUT_DIR)

    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        ramgen(
            sv_file=args.sv_file,
            output_dir=output_dir,
            module_prefix=args.module_prefix,
            file_prefix=args.file_prefix,
            verbose=True,
        )
        return 0
    except Exception as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())