#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAM Analyzer Module

Parses SystemVerilog files and extracts RAM instance information.
Provides analysis and reporting of RAM wrapper instances.
"""

from __future__ import print_function

import ast
import os
import re
from collections import OrderedDict


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
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*", "", text)
    return text


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

    for match in re.finditer(r"\.\s*(\w+)\s*\(\s*(.*?)\s*\)", block, flags=re.DOTALL):
        key = match.group(1)
        value = " ".join(match.group(2).split())
        params[key] = value
    return params


def parse_port_block(block):
    """Extract port connections from a port block."""
    ports = OrderedDict()
    if not block:
        return ports

    for match in re.finditer(r"\.\s*(\w+)\s*\(\s*(.*?)\s*\)", block, flags=re.DOTALL):
        port = match.group(1)
        signal = " ".join(match.group(2).split())
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
        return reference_name.replace("wrapper", "{}wx{}".format(dp, wd))
    return reference_name


def analyze_sv_file(file_path):
    """Analyze a SystemVerilog file and extract RAM instance information."""
    with open(file_path, "r", encoding="utf-8") as handle:
        raw_text = handle.read()

    normalized = normalize_sv_text(raw_text)
    clean_text = remove_comments(normalized)

    module_match = re.search(r"\bmodule\s+(\w+)\b", clean_text)
    module_name = module_match.group(1) if module_match else "<unknown>"

    instance_pattern = re.compile(
        r"(?P<type>\b\w+(?:_wrapper|_ram|ram\w*)\b)\s*"
        r"(?:#\s*\((?P<params>.*?)\))?\s*"
        r"(?P<name>\b\w+\b)\s*"
        r"(?P<array>\[[^\]]+\])?\s*"
        r"\((?P<ports>.*?)\)\s*;",
        flags=re.DOTALL,
    )

    instances = []
    for match in instance_pattern.finditer(clean_text):
        inst_type = match.group("type")
        inst_name = match.group("name")

        if inst_type == "module" or inst_name == module_name:
            continue

        params = parse_param_block(match.group("params"))
        ports = parse_port_block(match.group("ports"))
        array_range = match.group("array") or ""
        array_size = parse_array_size(array_range)
        bits_per_ram = estimate_bits(params)

        base_reference = build_reference_name(inst_type, params)
        instances.append(
            {
                "type": inst_type,
                "name": inst_name,
                "reference": base_reference,
                "base_reference": base_reference,
                "array_range": array_range,
                "array_size": array_size,
                "params": params,
                "ports": ports,
                "unconnected_ports": [k for k, v in ports.items() if not v],
                "bits_per_ram": bits_per_ram,
                "total_bits": (bits_per_ram * array_size) if bits_per_ram is not None else None,
            }
        )

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
    }


def print_human_readable(report):
    """Print a compact human-readable report of the analysis results."""
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
