#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAM Analyzer Module

Parses SystemVerilog files and extracts RAM instance information.
Provides analysis and reporting of RAM wrapper instances.
"""

from __future__ import print_function

import ast
import hashlib
import os
import re
from collections import OrderedDict
from .sv_scan import instance_declarations, mask_comments, matching_delimiters, module_headers, named_connections, tokenize


# Explicit contracts for the supported PCIe wrappers. Widths are expressions in
# the wrapper's parameters, not guesses based on the connected signal's name.
RAM_INTERFACES = {
    "ram_1p_wrapper": ("single_port", False, ("clk",)),
    "ram_1p_be_wrapper": ("single_port", True, ("clk",)),
    "ram_2p_1c_wrapper": ("simple_dual_port", False, ("clk",)),
    "ram_2p_2c_wrapper": ("simple_dual_port", False, ("clka", "clkb")),
}


def analyze_interface(item):
    """Attach a supported interface contract and actionable diagnostics.

    This validates the wrapper call, not arbitrary SV expression widths or
    collision/read-during-write behavior of the underlying memory cell.
    """
    diagnostics = []

    def issue(severity, code, message):
        diagnostics.append(dict(severity=severity, code=code,
                                instance=item["name"], message=message))

    contract = RAM_INTERFACES.get(item["type"])
    if contract is None:
        issue("warning", "unknown_ram_type", "No interface contract for {}".format(item["type"]))
        return None, diagnostics

    kind, byte_enable, clocks = contract
    widths = OrderedDict((clock, "1") for clock in clocks)
    if kind == "single_port":
        widths.update(addr="PW", din="WD", dout="WD", en="1",
                      we="WEW" if byte_enable else "1")
    else:
        widths.update(addra="PW", addrb="PW", dina="WD", doutb="WD",
                      ena="1", enb="1", wea="1")
    params = item["params"]
    required = ("WD", "PW", "DP", "RD_LATENCY") + (("WEW",) if byte_enable else ())
    values = {name: safe_eval_int(params.get(name)) for name in required}
    for name in required:
        if name not in params:
            issue("error", "missing_parameter", "Missing parameter {}".format(name))
        elif values[name] is None:
            issue("warning", "unresolved_parameter", "Cannot resolve {}={}".format(name, params[name]))
        elif values[name] <= 0:
            issue("error", "invalid_parameter", "{} must be positive".format(name))
    pw, dp = values["PW"], values["DP"]
    if pw is not None and dp is not None and pw > 0 and dp > 0 and (dp - 1).bit_length() > pw:
        issue("error", "address_capacity", "DP exceeds the address capacity of PW")
    if byte_enable:
        wd, wew = values["WD"], values["WEW"]
        if wd is not None and wd > 0 and wew is not None and wew != (wd + 7) // 8:
            issue("error", "byte_enable_width", "WEW must equal ceil(WD / 8)")
    elif "WEW" in params:
        issue("error", "unexpected_parameter", "WEW is only supported by ram_1p_be_wrapper")

    ports = item["ports"]
    for name in widths:
        if name not in ports:
            issue("error", "missing_port", "Missing port {}".format(name))
        elif not ports[name] and not name.startswith("dout"):
            issue("error", "unconnected_input", "Input {} is unconnected".format(name))
    for name in ports:
        if name not in widths:
            issue("error", "unknown_port", "Unknown port {}".format(name))

    interface = {
        "kind": kind, "byte_enable": byte_enable, "clocks": list(clocks),
        "write_clock": clocks[0], "read_clock": clocks[-1],
        "read_latency": values["RD_LATENCY"],
        "ports": OrderedDict((name, {
            "direction": "output" if name.startswith("dout") else "input",
            "width_expression": width,
            "width": 1 if width == "1" else values.get(width),
            "connection": ports.get(name),
        }) for name, width in widths.items()),
    }
    if byte_enable:
        wd = values["WD"]
        interface["byte_lane_width"] = 8
        interface["last_lane_width"] = ((wd - 1) % 8 + 1) if wd is not None and wd > 0 else None
    return interface, diagnostics


class SafeExpressionEvaluator(ast.NodeVisitor):
    """Safely evaluate simple arithmetic expressions used in SV parameters."""

    ALLOWED_BINOPS = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.Div: lambda a, b: a // b,
        ast.Mod: lambda a, b: a % b,
        ast.LShift: lambda a, b: a << b,
        ast.RShift: lambda a, b: a >> b,
        ast.BitOr: lambda a, b: a | b,
        ast.BitAnd: lambda a, b: a & b,
        ast.BitXor: lambda a, b: a ^ b,
        ast.Pow: lambda a, b: a ** b,
    }

    ALLOWED_UNARYOPS = {
        ast.UAdd: lambda a: +a,
        ast.USub: lambda a: -a,
        ast.Invert: lambda a: ~a,
    }

    def visit(self, node):
        if isinstance(node, ast.Expression):
            return self.visit(node.body)

        num_node = getattr(ast, "Num", None)
        if num_node is not None and isinstance(node, num_node):
            return int(node.n)

        if hasattr(ast, "Constant") and isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return int(node.value)
            raise ValueError("Unsupported constant: {!r}".format(node.value))
        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in self.ALLOWED_BINOPS:
                raise ValueError("Unsupported operator: {}".format(op_type.__name__))
            left = self.visit(node.left)
            right = self.visit(node.right)
            return self.ALLOWED_BINOPS[op_type](left, right)
        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in self.ALLOWED_UNARYOPS:
                raise ValueError("Unsupported unary operator: {}".format(op_type.__name__))
            operand = self.visit(node.operand)
            return self.ALLOWED_UNARYOPS[op_type](operand)
        raise ValueError("Unsupported expression node: {}".format(type(node).__name__))


def normalize_sv_text(text):
    """Normalize full-width punctuation and line endings."""
    replacements = {
        u"，": ",",
        u"（": "(",
        u"）": ")",
        u"；": ";",
        u"：": ":",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def remove_comments(text):
    """Remove Verilog block and line comments."""
    return mask_comments(text)


def convert_verilog_literals(expr):
    """Convert common Verilog literals like 8'd15 or 4'hF to integers."""

    def _replace(match):
        base_char = match.group(2).lower()
        value = match.group(3).replace("_", "")
        value = re.sub(r"[xzXZ]", "0", value)
        base_map = {"d": 10, "h": 16, "b": 2, "o": 8}
        try:
            return str(int(value, base_map[base_char]))
        except Exception:
            return match.group(0)

    pattern = re.compile(r"(\d+)\s*'\s*([dDhHbBoO])\s*([0-9a-fA-F_xXzZ]+)")
    return pattern.sub(_replace, expr)


def safe_eval_int(expr):
    """Evaluate an integer expression safely. Returns None on failure."""
    if expr is None:
        return None

    expr = expr.strip()
    if not expr:
        return None

    expr = convert_verilog_literals(expr)
    expr = expr.replace(" ", "")

    if re.search(r"[^0-9\+\-\*\/\(\)%<>&\|\^~]", expr):
        return None

    try:
        parsed = ast.parse(expr, mode="eval")
        return SafeExpressionEvaluator().visit(parsed)
    except Exception:
        return None


def parse_param_block(block):
    """Extract parameters from a parameter block."""
    params = OrderedDict()
    if not block:
        return params

    block = remove_comments(block)
    for key, expression in named_connections(block):
        value = " ".join(expression.split())
        params[key] = value
    return params


def parse_port_block(block):
    """Extract port connections from a port block."""
    ports = OrderedDict()
    if not block:
        return ports

    block = remove_comments(block)
    for port, expression in named_connections(block):
        signal = " ".join(expression.split())
        ports[port] = signal
    return ports


def parse_array_size(array_range):
    """Parse array size from range string like [N-1:0]."""
    if not array_range:
        return 1

    text = array_range.strip()[1:-1]
    if ":" not in text:
        value = safe_eval_int(text)
        return value if value is not None else 1

    msb_text, lsb_text = [part.strip() for part in text.split(":", 1)]
    msb = safe_eval_int(msb_text)
    lsb = safe_eval_int(lsb_text)
    if msb is None or lsb is None:
        return 1
    return abs(msb - lsb) + 1


def estimate_bits(params):
    """Estimate total bits for a RAM instance."""
    width = safe_eval_int(params.get("WD", ""))
    depth = safe_eval_int(params.get("DP", ""))
    if width is None or depth is None:
        return None
    return width * depth


def build_reference_name(reference_name, params):
    """Build normalized reference name with DP and WD dimensions."""
    dp = str(params.get("DP", "")).strip()
    wd = str(params.get("WD", "")).strip()

    if "wrapper" in reference_name and dp and wd:
        # Expressions/literals cannot be inserted verbatim into identifiers.
        values = [safe_eval_int(value) for value in (dp, wd)]
        dimensions = [str(value) if value is not None else expression
                      for value, expression in zip(values, (dp, wd))]
        # Unresolved expressions remain intact in the source/parameter maps.
        # Only the derived module/file identifier needs an opaque safe spelling.
        dimensions = [value if re.fullmatch(r"[A-Za-z0-9_$]+", value) else
                      "expr_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
                      for value in dimensions]
        return reference_name.replace("wrapper", "{}wx{}".format(*dimensions))
    return reference_name


def analyze_sv_file(file_path):
    """Analyze a SystemVerilog file and extract RAM instance information."""
    with open(file_path, "r", encoding="utf-8") as handle:
        raw_text = handle.read()

    normalized = normalize_sv_text(raw_text)
    # Tokenization already skips comments and keeps strings opaque. Mask only
    # the small extracted expression blocks instead of scanning the file twice.
    clean_text = normalized

    tokens = tokenize(clean_text)
    closing = matching_delimiters(tokens)
    header = next(module_headers(tokens), None)
    module_name = tokens[header[1]].group() if header else "<unknown>"
    ram_type = re.compile(r"[A-Za-z_$][\w$]*(?:_wrapper|_ram|ram[\w$]*)\Z")

    instances = []
    for declaration in instance_declarations(clean_text, tokens, closing, ram_type.fullmatch):
        inst_type = declaration["type"]
        params = parse_param_block(declaration["params"])
        bits_per_ram = estimate_bits(params)
        base_reference = build_reference_name(inst_type, params)
        for instance in declaration["instances"]:
            ports = parse_port_block(instance["ports"])
            array_range = "".join(instance["arrays"])
            array_size = 1
            for dimension in instance["arrays"]:
                array_size *= parse_array_size(dimension)
            instances.append(
                {
                    "type": inst_type,
                    "name": instance["name"],
                    "reference": base_reference,
                    "base_reference": base_reference,
                    "array_range": array_range,
                    "array_size": array_size,
                    "params": OrderedDict(params),
                    "ports": ports,
                    "unconnected_ports": [k for k, v in ports.items() if not v],
                    "bits_per_ram": bits_per_ram,
                    "total_bits": (bits_per_ram * array_size) if bits_per_ram is not None else None,
                }
            )

    diagnostics = []
    for item in instances:
        item["interface"], item["diagnostics"] = analyze_interface(item)
        diagnostics.extend(item["diagnostics"])
    errors = [entry for entry in diagnostics if entry["severity"] == "error"]

    type_summary = OrderedDict()
    total_blocks = 0
    total_bits = 0
    total_bits_known = True

    for item in instances:
        total_blocks += item["array_size"]
        if item["total_bits"] is None:
            total_bits_known = False
        else:
            total_bits += item["total_bits"]

        bucket = type_summary.setdefault(item["type"], {"instances": 0, "logical_blocks": 0})
        bucket["instances"] += 1
        bucket["logical_blocks"] += item["array_size"]

    return {
        "file": os.path.abspath(file_path),
        "module": module_name,
        "instance_count": len(instances),
        "logical_ram_blocks": total_blocks,
        "total_bits": total_bits if total_bits_known else None,
        "type_summary": type_summary,
        "instances": instances,
        "diagnostics": diagnostics,
        "validation_passed": not errors,
    }


def print_human_readable(report):
    """Print a compact human-readable report of the analysis results."""
    for entry in report.get("diagnostics", []):
        print("{} | {} | {}".format(entry["severity"].upper(), entry["instance"], entry["message"]))
    print("RAM {} | {} | {} inst".format(
        report["module"],
        os.path.basename(report["file"]),
        report["instance_count"],
    ))

    header = "{:<4} {:<24} {:<20} {:>6} {:>6} {:>4} {:>10}".format(
        "NO.", "INST", "TYPE", "DP", "WD", "BE", "BITS"
    )
    print(header)
    print("-" * len(header))

    for idx, item in enumerate(report["instances"], 1):
        params = item.get("params", {})
        be_flag = "Y" if ("WEW" in params or "_be_" in item.get("type", "")) else "-"
        dp = params.get("DP", "?")
        wd = params.get("WD", "?")
        bits = item["total_bits"] if item["total_bits"] is not None else "unknown"

        print(
            "{:<4} {:<24.24} {:<20.20} {:>6} {:>6} {:>4} {:>10}".format(
                idx,
                item.get("name", ""),
                item.get("type", ""),
                dp,
                wd,
                be_flag,
                bits,
            )
        )
