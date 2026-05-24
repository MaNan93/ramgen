#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Code Generation Module

Generates SystemVerilog wrapper modules, testbenches, and related files
for RAM instances.
"""

from __future__ import print_function

import os
import re
from xml.sax.saxutils import escape


COMMON_PARAM_NAMES = ["RD_LATENCY", "WD", "PW", "DP"]
DEFAULT_PARAM_VALUES = {"RD_LATENCY": 1, "WD": 8, "PW": 4, "DP": 16, "WEW": 1}
EXCEL_HEADERS = [
    "instance_name",
    "ram_type",
    "reference",
    "array_range",
    "array_size",
    "bits_per_ram",
    "total_bits",
    "param_RD_LATENCY",
    "param_WD",
    "param_PW",
    "param_DP",
    "param_WEW",
    "ports",
    "unconnected_ports",
]


def ensure_dir(path):
    """Ensure directory exists, create if needed."""
    if path and not os.path.exists(path):
        os.makedirs(path)


def is_byte_enable_ram(reference, params):
    """Check if RAM has byte-enable capability."""
    return ("WEW" in params) or ("_be_" in reference)


def get_param_names(include_wew):
    """Get list of parameter names for this RAM type."""
    names = list(COMMON_PARAM_NAMES)
    if include_wew:
        names.append("WEW")
    return names


def get_param_defaults(params):
    """Get parameter values with defaults."""
    defaults = {}
    for name, fallback in DEFAULT_PARAM_VALUES.items():
        defaults[name] = str(params.get(name, fallback) or fallback)
    return defaults


def default_excel_path(sv_file, output_dir):
    """Generate default Excel report path under the target output directory."""
    return os.path.join(os.path.abspath(output_dir), "report.xls")


def export_raminfo_csv(report, csv_path):
    """Export RAM report rows to CSV with header and RAM information only."""
    ensure_dir(os.path.dirname(os.path.abspath(csv_path)))
    rows = [["NO.", "INST", "TYPE", "DP", "WD", "BE", "BITS"]]
    for idx, item in enumerate(report.get("instances", []), 1):
        params = item.get("params", {})
        be_flag = "Y" if ("WEW" in params or "_be_" in item.get("type", "")) else "-"
        dp = params.get("DP", "?")
        wd = params.get("WD", "?")
        bits = item.get("total_bits") if item.get("total_bits") is not None else "unknown"
        rows.append([idx, item.get("name", ""), item.get("type", ""), dp, wd, be_flag, bits])

    # Keep CSV structure while padding columns so plain-text viewing is aligned.
    text_rows = [[str(cell) for cell in row] for row in rows]
    col_count = len(text_rows[0]) if text_rows else 0
    widths = [0] * col_count
    for row in text_rows:
        for col, value in enumerate(row):
            widths[col] = max(widths[col], len(value))

    right_align_cols = {0, 3, 4, 6}
    lines = []
    for row in text_rows:
        padded = []
        for col, value in enumerate(row):
            if col in right_align_cols:
                padded.append(value.rjust(widths[col]))
            else:
                padded.append(value.ljust(widths[col]))
        lines.append(", ".join(padded))

    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def normalize_ram_type_name(value):
    """Normalize RAM type names for reporting."""
    text = str(value or "")
    if "ram_1p_be" in text:
        return "ram_1p_be"
    if "ram_2p_1c" in text:
        return "ram_2p_1c"
    if "ram_2p_2c" in text:
        return "ram_2p_2c"
    if "ram_1p" in text:
        return "ram_1p"
    return text


def build_excel_row(item):
    """Build one Excel row from an analyzed RAM instance."""
    params = item.get("params", {})
    return [
        item["name"],
        normalize_ram_type_name(item.get("type", item.get("reference", ""))),
        item.get("reference", item["type"]),
        item["array_range"] or "scalar",
        item["array_size"],
        item["bits_per_ram"] if item["bits_per_ram"] is not None else "unknown",
        item["total_bits"] if item["total_bits"] is not None else "unknown",
        params.get("RD_LATENCY", ""),
        params.get("WD", ""),
        params.get("PW", ""),
        params.get("DP", ""),
        params.get("WEW", ""),
        ", ".join(item.get("ports", {}).keys()),
        ", ".join(item.get("unconnected_ports", [])),
    ]


def export_excel(report, excel_path):
    """Export the RAM analysis report as a dependency-free Excel .xls document."""
    ensure_dir(os.path.dirname(os.path.abspath(excel_path)))

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"',
        ' xmlns:o="urn:schemas-microsoft-com:office:office"',
        ' xmlns:x="urn:schemas-microsoft-com:office:excel"',
        ' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">',
        ' <Worksheet ss:Name="RAM Report">',
        '  <Table>',
    ]

    rows = [EXCEL_HEADERS] + [build_excel_row(item) for item in report.get("instances", [])]
    for row in rows:
        lines.append('   <Row>')
        for value in row:
            cell_text = escape(str(value))
            lines.append('    <Cell><Data ss:Type="String">{}</Data></Cell>'.format(cell_text))
        lines.append('   </Row>')

    lines.extend([
        '  </Table>',
        ' </Worksheet>',
        '</Workbook>',
    ])

    with open(excel_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def generate_output_sv(source_sv_path, output_sv_path, report, top_module_name="pcie_ram"):
    """Generate transformed top-level SystemVerilog file."""
    with open(source_sv_path, "r", encoding="utf-8") as handle:
        text = handle.read()

    text = re.sub(
        r"\bmodule\s+{}\b".format(re.escape(report["module"])),
        "module {}".format(top_module_name),
        text,
        count=1,
    )

    for item in report["instances"]:
        old_ref = item["type"]
        new_ref = item.get("reference", old_ref)
        inst_name = item["name"]
        pattern = re.compile(
            r"\b{}\b(?=\s*(?:#\s*\(.*?\))?\s*{}\b)".format(
                re.escape(old_ref), re.escape(inst_name)
            ),
            flags=re.DOTALL,
        )
        text = pattern.sub(new_ref, text, count=1)

    output_dir = os.path.dirname(os.path.abspath(output_sv_path))
    ensure_dir(output_dir)

    with open(output_sv_path, "w", encoding="utf-8") as handle:
        handle.write(text)

    return output_sv_path


def infer_port_decl(port_name, reference, include_wew):
    """Infer SystemVerilog port declaration from port name."""
    direction = "output logic" if port_name.startswith("dout") else "input"
    width = ""

    if port_name in ("addr", "addra", "addrb"):
        width = " [PW-1:0]"
    elif port_name in ("din", "dina", "dinb", "dout", "douta", "doutb"):
        width = " [WD-1:0]"
    elif port_name in ("we", "wea", "web") and include_wew:
        width = " [WEW-1:0]"

    return "    {}{} {}".format(direction, width, port_name)


def build_simple_ram_body(write_clock, read_clock, wen_expr, ren_expr, write_addr, read_addr, write_data, read_data):
    """Build basic dual-clock RAM behavioral model."""
    return """    reg [WD-1:0] mem [0:DP-1];
    wire wen;
    wire ren;

    assign wen = {wen_expr};
    assign ren = {ren_expr};

    always @(posedge {write_clock}) begin
        if (wen) begin
            mem[{write_addr}] <= {write_data};
        end
    end

    always @(posedge {read_clock}) begin
        if (ren) begin
            {read_data} <= mem[{read_addr}];
        end
    end""".format(
        write_clock=write_clock,
        read_clock=read_clock,
        wen_expr=wen_expr,
        ren_expr=ren_expr,
        write_addr=write_addr,
        read_addr=read_addr,
        write_data=write_data,
        read_data=read_data,
    )


def build_simulation_body(item):
    """Build RAM behavioral model body based on port types."""
    port_names = set(item.get("ports", {}).keys())
    include_wew = is_byte_enable_ram(item.get("reference", ""), item.get("params", {}))

    if "clka" in port_names and "clkb" in port_names:
        return build_simple_ram_body("clka", "clkb", "ena && wea", "enb", "addra", "addrb", "dina", "doutb")

    if "addra" in port_names and "addrb" in port_names:
        return build_simple_ram_body("clk", "clk", "ena && wea", "enb", "addra", "addrb", "dina", "doutb")

    if include_wew:
        return """    reg [WD-1:0] mem [0:DP-1];
    wire wen;
    wire ren;
    integer i;
    integer j;
    localparam integer LANE_W = (WEW > 0) ? ((WD + WEW - 1) / WEW) : WD;

    assign wen = en && (|we);
    assign ren = en && ~(|we);

    always @(posedge clk) begin
        if (wen) begin
            for (i = 0; i < WEW; i = i + 1) begin
                if (we[i]) begin
                    for (j = 0; j < LANE_W; j = j + 1) begin
                        if ((i * LANE_W + j) < WD) begin
                            mem[addr][i * LANE_W + j] <= din[i * LANE_W + j];
                        end
                    end
                end
            end
        end
    end

    always @(posedge clk) begin
        if (ren) begin
            dout <= mem[addr];
        end
    end"""

    return build_simple_ram_body("clk", "clk", "en && we", "en && ~we", "addr", "addr", "din", "dout")


def order_port_names_output_last(port_names):
    """Keep original order while moving dout* ports to the tail."""
    non_output_ports = [name for name in port_names if not name.startswith("dout")]
    output_ports = [name for name in port_names if name.startswith("dout")]
    return non_output_ports + output_ports


def build_reference_module_text(item):
    """Generate complete RAM module definition."""
    reference = item.get("reference", item["type"])
    params = item.get("params", {})
    include_wew = is_byte_enable_ram(reference, params)

    param_names = get_param_names(include_wew)

    param_lines = []
    for name in param_names:
        param_lines.append("    parameter {} = -1".format(name))

    port_names = list(item.get("ports", {}).keys())
    port_names = order_port_names_output_last(port_names)
    port_lines = [infer_port_decl(port_name, reference, include_wew) for port_name in port_names]
    port_block = ""
    if port_lines:
        if len(port_lines) == 1:
            port_block = "{}\n    //E".format(port_lines[0])
        else:
            port_block = "{},\n{}\n    //E".format(
                ",\n".join(port_lines[:-1]),
                port_lines[-1],
            )
    sim_body = build_simulation_body(item)

    return "module {} #(\n{}\n) (\n{}\n);\n\n`ifdef INNO_REG_RAM\n{}\n`else\n    // instantiate memory cell\n`endif\n\nendmodule\n".format(
        reference,
        ",\n".join(param_lines),
        port_block,
        sim_body,
    )


def generate_reference_modules(report, output_dir, file_prefix=""):
    """Generate behavioral wrapper modules for all unique RAM references."""
    ensure_dir(output_dir)

    written_files = []
    seen = set()
    normalized_file_prefix = file_prefix if not file_prefix or file_prefix.endswith("_") else file_prefix + "_"

    for item in report.get("instances", []):
        reference = item.get("reference", item["type"])
        base_reference = item.get("base_reference", item.get("reference", item["type"]))
        if base_reference in seen:
            continue
        seen.add(base_reference)

        file_name = "{}{}.sv".format(normalized_file_prefix, base_reference)
        file_path = os.path.join(output_dir, file_name)
        content = build_reference_module_text(item)
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        written_files.append(file_path)

    return written_files
