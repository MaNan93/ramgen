#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulation and Testbench Module

Generates testbench files, simulation support files (flist, makefile),
and related simulation infrastructure.
"""

from __future__ import print_function

import os

from .ram_generator import is_byte_enable_ram, get_param_names, get_param_defaults, ensure_dir


def build_param_value_maps(names, value_map):
    """Build parameter mapping strings with direct literal/expression values."""
    return ",\n".join(["        .{0}({1})".format(name, value_map[name]) for name in names])


def build_interface_port_maps(names, iface_name):
    """Build port mappings from a DUT to an interface instance."""
    mappings = ["        .{0}({1}.{0})".format(name, iface_name) for name in names]
    if not mappings:
        return ""
    return ",\n".join(mappings) + "\n        //E"


def infer_interface_name(item):
    """Infer the generated verification interface type for a RAM instance."""
    ram_type = item.get("type", "")
    reference = item.get("reference", ram_type)

    if "ram_2p_2c" in ram_type or "ram_2p_2c" in reference:
        return "ram_2p_2c_if"
    if "ram_2p_1c" in ram_type or "ram_2p_1c" in reference:
        return "ram_2p_1c_if"
    if is_byte_enable_ram(reference, item.get("params", {})):
        return "ram_1p_be_if"
    return "ram_1p_if"


def build_interface_template(iface_name, signal_lines, task_lines, include_wew=False):
    """Build a verification interface from shared signal and task templates."""
    defaults = {"RD_LATENCY": 1, "WD": 8, "PW": 4, "DP": 16, "WEW": 1}
    params = ["parameter real TP = 1.1"]
    params.extend(["parameter {} = {}".format(name, defaults[name]) for name in get_param_names(include_wew)])
    param_decl = ", ".join(
        params
    )

    lines = ["interface {} #({}) ();".format(iface_name, param_decl)]
    lines.extend(signal_lines)
    lines.append("    localparam [WD-1:0] TEST_DATA = {WD{1'b1}};")
    lines.append("")
    lines.extend(task_lines)
    lines.append("endinterface")
    return lines


def build_dual_port_interface(iface_name, dual_clock):
    """Build a single-clock or dual-clock dual-port RAM verification interface."""
    write_clk = "clka" if dual_clock else "clk"
    read_clk = "clkb" if dual_clock else "clk"
    signal_lines = [
        "    logic {};".format(write_clk),
        "    logic {};".format(read_clk) if dual_clock else None,
        "    logic [PW-1:0] addra;",
        "    logic [PW-1:0] addrb;",
        "    logic [WD-1:0] dina;",
        "    logic [WD-1:0] doutb;",
        "    logic ena;",
        "    logic enb;",
        "    logic wea;",
    ]
    signal_lines = [line for line in signal_lines if line is not None]

    task_lines = [
        "    task automatic run_test(input string inst_name);",
        "        reg [WD-1:0] exp_mem [0:DP-1];",
        "        reg [WD-1:0] wr_data;",
        "        integer idx;",
        "        integer rand_seed;",
        "        begin",
        "            addra <= #(TP) '0; addrb <= #(TP) '0; dina <= #(TP) '0; ena <= #(TP) 1'b0; enb <= #(TP) 1'b0; wea <= #(TP) 1'b0;",
        "            if (!$value$plusargs(\"SEED=%d\", rand_seed)) rand_seed = 32'h1A2B3C4D;",
        "            for (idx = 0; idx < DP; idx = idx + 1) exp_mem[idx] = 'x;",
        "            repeat (2) @(posedge {});".format(write_clk),
        "            for (idx = 0; idx < DP; idx = idx + 1) begin",
        "                ena <= #(TP) 1'b1; wea <= #(TP) 1'b1; addra <= #(TP) idx; dina <= #(TP) '0; exp_mem[idx] = '0;",
        "                @(posedge {});".format(write_clk),
        "            end",
        "            ena <= #(TP) 1'b0; wea <= #(TP) 1'b0;",
        "            repeat (5) @(posedge {});".format(read_clk),
        "            for (idx = 0; idx < DP; idx = idx + 1) begin",
        "                @(posedge {}); enb <= #(TP) 1'b1; addrb <= #(TP) idx; @(posedge {}); @(negedge {});".format(read_clk, read_clk, read_clk),
        "                if (doutb !== exp_mem[idx]) $error(\"%s all-0 test failed at depth %0d\", inst_name, idx);",
        "            end",
        "            enb <= #(TP) 1'b0;",
        "            repeat (5) @(posedge {});".format(write_clk),
        "            for (idx = 0; idx < DP; idx = idx + 1) begin",
        "                ena <= #(TP) 1'b1; wea <= #(TP) 1'b1; addra <= #(TP) idx; dina <= #(TP) TEST_DATA; exp_mem[idx] = TEST_DATA;",
        "                @(posedge {});".format(write_clk),
        "            end",
        "            ena <= #(TP) 1'b0; wea <= #(TP) 1'b0;",
        "            repeat (5) @(posedge {});".format(read_clk),
        "            for (idx = 0; idx < DP; idx = idx + 1) begin",
        "                @(posedge {}); enb <= #(TP) 1'b1; addrb <= #(TP) idx; @(posedge {}); @(negedge {});".format(read_clk, read_clk, read_clk),
        "                if (doutb !== exp_mem[idx]) $error(\"%s all-1 test failed at depth %0d\", inst_name, idx);",
        "            end",
        "            enb <= #(TP) 1'b0;",
        "            repeat (5) @(posedge {});".format(write_clk),
        "            for (idx = 0; idx < DP; idx = idx + 1) begin",
        "                wr_data = $random(rand_seed);",
        "                ena <= #(TP) 1'b1; wea <= #(TP) 1'b1; addra <= #(TP) idx; dina <= #(TP) wr_data; exp_mem[idx] = wr_data;",
        "                @(posedge {});".format(write_clk),
        "            end",
        "            ena <= #(TP) 1'b0; wea <= #(TP) 1'b0;",
        "            repeat (5) @(posedge {});".format(read_clk),
        "            for (idx = 0; idx < DP; idx = idx + 1) begin",
        "                @(posedge {}); enb <= #(TP) 1'b1; addrb <= #(TP) idx; @(posedge {}); @(negedge {});".format(read_clk, read_clk, read_clk),
        "                if (doutb !== exp_mem[idx]) $error(\"%s random test failed at depth %0d\", inst_name, idx);",
        "            end",
        "            ena <= #(TP) 1'b0; enb <= #(TP) 1'b0; wea <= #(TP) 1'b0;",
        "            $display(\"%s all depth tests passed\", inst_name);",
        "        end",
        "    endtask",
    ]
    return build_interface_template(iface_name, signal_lines, task_lines)


def build_single_port_interface(iface_name, include_wew=False):
    """Build a single-port RAM verification interface."""
    signal_lines = [
        "    logic clk;",
        "    logic [PW-1:0] addr;",
        "    logic [WD-1:0] din;",
        "    logic [WD-1:0] dout;",
        "    logic en;",
        "    logic [WEW-1:0] we;" if include_wew else "    logic we;",
    ]

    task_lines = [
        "    task automatic run_test(input string inst_name);",
        "        reg [WD-1:0] exp_mem [0:DP-1];",
    ]
    if include_wew:
        task_lines.extend([
            "        reg [WD-1:0] exp_data;",
            "        reg [WD-1:0] wr_data;",
            "        reg [WEW-1:0] we_mask;",
            "        integer lane;",
            "        integer bit_idx;",
            "        integer lane_w;",
            "        integer rand_seed;",
        ])
    task_lines.extend([
        "        integer idx;",
        "        reg [WD-1:0] wr_data;" if not include_wew else None,
        "        integer rand_seed;" if not include_wew else None,
        "        begin",
        "            addr <= #(TP) '0; din <= #(TP) '0; en <= #(TP) 1'b0; we <= #(TP) '0;" if include_wew else "            addr <= #(TP) '0; din <= #(TP) '0; en <= #(TP) 1'b0; we <= #(TP) 1'b0;",
            "            exp_data = 'x; lane_w = (WEW > 0) ? ((WD + WEW - 1) / WEW) : WD;" if include_wew else None,
        "            if (!$value$plusargs(\"SEED=%d\", rand_seed)) rand_seed = 32'h1A2B3C4D;",
            "            for (idx = 0; idx < DP; idx = idx + 1) exp_mem[idx] = 'x;",
        "            repeat (2) @(posedge clk);",
    ])

    if include_wew:
        task_lines.extend([
            "            for (idx = 0; idx < DP; idx = idx + 1) begin",
            "                wr_data = '0; we_mask = {WEW{1'b1}};",
            "                en <= #(TP) 1'b1; addr <= #(TP) idx; din <= #(TP) wr_data; we <= #(TP) we_mask;",
            "                for (lane = 0; lane < WEW; lane = lane + 1) begin",
            "                    if (we_mask[lane]) begin",
            "                        for (bit_idx = 0; bit_idx < lane_w; bit_idx = bit_idx + 1) begin",
            "                            if ((lane * lane_w + bit_idx) < WD) exp_mem[idx][lane * lane_w + bit_idx] = wr_data[lane * lane_w + bit_idx];",
            "                        end",
            "                    end",
            "                end",
            "                @(posedge clk);",
            "            end",
            "            we <= #(TP) '0;",
            "            repeat (5) @(posedge clk);",
            "            for (idx = 0; idx < DP; idx = idx + 1) begin",
            "                exp_data = exp_mem[idx]; @(posedge clk); en <= #(TP) 1'b1; we <= #(TP) '0; addr <= #(TP) idx; @(posedge clk); @(negedge clk);",
            "                if (dout !== exp_data) $error(\"%s all-0 test failed at depth %0d\", inst_name, idx);",
            "            end",
            "            repeat (5) @(posedge clk);",
            "            for (idx = 0; idx < DP; idx = idx + 1) begin",
            "                en <= #(TP) 1'b1; addr <= #(TP) idx; din <= #(TP) TEST_DATA; we <= #(TP) {WEW{1'b1}}; exp_mem[idx] = TEST_DATA;",
            "                @(posedge clk);",
            "            end",
            "            we <= #(TP) '0;",
            "            repeat (5) @(posedge clk);",
            "            for (idx = 0; idx < DP; idx = idx + 1) begin",
            "                exp_data = exp_mem[idx]; @(posedge clk); en <= #(TP) 1'b1; we <= #(TP) '0; addr <= #(TP) idx; @(posedge clk); @(negedge clk);",
            "                if (dout !== exp_data) $error(\"%s all-1 test failed at depth %0d\", inst_name, idx);",
            "            end",
            "            repeat (5) @(posedge clk);",
            "            for (idx = 0; idx < DP; idx = idx + 1) begin",
            "                wr_data = $random(rand_seed); we_mask = $random(rand_seed);",
            "                if (idx == 0) begin we_mask = '0; if (WEW > 0) we_mask[0] = 1'b1; end",
            "                en <= #(TP) 1'b1; addr <= #(TP) idx; din <= #(TP) wr_data; we <= #(TP) we_mask;",
            "                for (lane = 0; lane < WEW; lane = lane + 1) begin",
            "                    if (we_mask[lane]) begin",
            "                        for (bit_idx = 0; bit_idx < lane_w; bit_idx = bit_idx + 1) begin",
            "                            if ((lane * lane_w + bit_idx) < WD) exp_mem[idx][lane * lane_w + bit_idx] = wr_data[lane * lane_w + bit_idx];",
            "                        end",
            "                    end",
            "                end",
            "                @(posedge clk);",
            "            end",
            "            we <= #(TP) '0;",
            "            repeat (5) @(posedge clk);",
            "            for (idx = 0; idx < DP; idx = idx + 1) begin",
            "                exp_data = exp_mem[idx]; @(posedge clk); en <= #(TP) 1'b1; we <= #(TP) '0; addr <= #(TP) idx; @(posedge clk); @(negedge clk);",
            "                if (dout !== exp_data) $error(\"%s random test failed at depth %0d\", inst_name, idx);",
            "            end",
            "            en <= #(TP) 1'b0;",
        ])
    else:
        task_lines.extend([
            "            for (idx = 0; idx < DP; idx = idx + 1) begin",
            "                en <= #(TP) 1'b1; we <= #(TP) 1'b1; addr <= #(TP) idx; din <= #(TP) '0; exp_mem[idx] = '0;",
            "                @(posedge clk);",
            "            end",
            "            we <= #(TP) 1'b0;",
            "            repeat (5) @(posedge clk);",
            "            for (idx = 0; idx < DP; idx = idx + 1) begin",
            "                @(posedge clk); en <= #(TP) 1'b1; we <= #(TP) 1'b0; addr <= #(TP) idx; @(posedge clk); @(negedge clk);",
            "                if (dout !== exp_mem[idx]) $error(\"%s all-0 test failed at depth %0d\", inst_name, idx);",
            "            end",
            "            repeat (5) @(posedge clk);",
            "            for (idx = 0; idx < DP; idx = idx + 1) begin",
            "                en <= #(TP) 1'b1; we <= #(TP) 1'b1; addr <= #(TP) idx; din <= #(TP) TEST_DATA; exp_mem[idx] = TEST_DATA;",
            "                @(posedge clk);",
            "            end",
            "            we <= #(TP) 1'b0;",
            "            repeat (5) @(posedge clk);",
            "            for (idx = 0; idx < DP; idx = idx + 1) begin",
            "                @(posedge clk); en <= #(TP) 1'b1; we <= #(TP) 1'b0; addr <= #(TP) idx; @(posedge clk); @(negedge clk);",
            "                if (dout !== exp_mem[idx]) $error(\"%s all-1 test failed at depth %0d\", inst_name, idx);",
            "            end",
            "            repeat (5) @(posedge clk);",
            "            for (idx = 0; idx < DP; idx = idx + 1) begin",
            "                wr_data = $random(rand_seed);",
            "                en <= #(TP) 1'b1; we <= #(TP) 1'b1; addr <= #(TP) idx; din <= #(TP) wr_data; exp_mem[idx] = wr_data;",
            "                @(posedge clk);",
            "            end",
            "            we <= #(TP) 1'b0;",
            "            repeat (5) @(posedge clk);",
            "            for (idx = 0; idx < DP; idx = idx + 1) begin",
            "                @(posedge clk); en <= #(TP) 1'b1; we <= #(TP) 1'b0; addr <= #(TP) idx; @(posedge clk); @(negedge clk);",
            "                if (dout !== exp_mem[idx]) $error(\"%s random test failed at depth %0d\", inst_name, idx);",
            "            end",
            "            en <= #(TP) 1'b0;",
        ])

    task_lines.extend([
        "            $display(\"%s all depth tests passed\", inst_name);",
        "        end",
        "    endtask",
    ])
    task_lines = [line for line in task_lines if line is not None]
    return build_interface_template(iface_name, signal_lines, task_lines, include_wew=include_wew)


def build_interface_definition_lines(report):
    """Generate shared verification interfaces with built-in test tasks."""
    used = []
    for item in report.get("instances", []):
        iface = infer_interface_name(item)
        if iface not in used:
            used.append(iface)

    defs = []
    interface_builders = {
        "ram_2p_1c_if": lambda: build_dual_port_interface("ram_2p_1c_if", dual_clock=False),
        "ram_2p_2c_if": lambda: build_dual_port_interface("ram_2p_2c_if", dual_clock=True),
        "ram_1p_if": lambda: build_single_port_interface("ram_1p_if", include_wew=False),
        "ram_1p_be_if": lambda: build_single_port_interface("ram_1p_be_if", include_wew=True),
    }

    for iface in used:
        defs.extend(interface_builders[iface]())
        defs.append("")

    return defs


def build_tb_clock_lines(iface_name, dual_clock):
    """Generate clock generation code for an interface-driven testbench."""
    if dual_clock:
        return [
            "",
            "    initial {}.clka = 1'b0;".format(iface_name),
            "    initial {}.clkb = 1'b0;".format(iface_name),
            "    always #5 {}.clka = ~{}.clka;".format(iface_name, iface_name),
            "    always #7 {}.clkb = ~{}.clkb;".format(iface_name, iface_name),
            "",
        ]

    return [
        "",
        "    initial {}.clk = 1'b0;".format(iface_name),
        "    always #5 {}.clk = ~{}.clk;".format(iface_name, iface_name),
        "",
    ]


def build_dual_port_case_lines(sig_prefix, dual_clock):
    """Generate interface-based dual-port RAM clocking only; test run is controlled globally."""
    iface_name = "{}_if".format(sig_prefix)
    return build_tb_clock_lines(iface_name, dual_clock)


def build_single_port_case_lines(sig_prefix):
    """Generate interface-based single-port RAM clocking only; test run is controlled globally."""
    iface_name = "{}_if".format(sig_prefix)
    return build_tb_clock_lines(iface_name, False)


def build_tb_instance_preamble(item):
    """Build interface-driven testbench instance declaration and initialization code."""
    reference = item.get("reference", item["type"])
    inst_name = item["name"]
    sig_prefix = inst_name
    iface_name = "{}_if".format(sig_prefix)
    iface_type = infer_interface_name(item)
    params = item.get("params", {})
    port_names = list(item.get("ports", {}).keys())
    include_wew = is_byte_enable_ram(reference, params)
    param_defaults = get_param_defaults(params)
    param_names = get_param_names(include_wew)

    lines = ["    // Instance: {}".format(inst_name)]
    param_map = build_param_value_maps(param_names, param_defaults)
    port_map = build_interface_port_maps(port_names, iface_name)
    lines.append("    {} #(\n{}\n    ) {} ();".format(iface_type, param_map, iface_name))
    lines.append("")
    lines.append("    {} #(\n{}\n    ) {} (\n{}\n    );".format(reference, param_map, inst_name, port_map))

    return {
        "inst_name": inst_name,
        "sig_prefix": sig_prefix,
        "port_set": set(port_names),
        "lines": lines,
    }


def build_combined_testbench_text(report, tb_module_name="pcie_ram_tb"):
    """Generate complete merged testbench file."""
    lines = [
        "`timescale 1ns/1ps",
        "",
    ]
    lines.extend(build_interface_definition_lines(report))
    lines.extend([
        "module {};".format(tb_module_name),
        "",
    ])

    for item in report.get("instances", []):
        tb_info = build_tb_instance_preamble(item)
        sig_prefix = tb_info["sig_prefix"]
        port_set = tb_info["port_set"]

        lines.extend(tb_info["lines"])

        if "clka" in port_set and "clkb" in port_set:
            lines.extend(build_dual_port_case_lines(sig_prefix, True))
        elif "addra" in port_set and "addrb" in port_set:
            lines.extend(build_dual_port_case_lines(sig_prefix, False))
        else:
            lines.extend(build_single_port_case_lines(sig_prefix))

        lines.append("")

    if report.get("instances"):
        lines.extend([
            "    initial begin",
            "        fork",
        ])

        for item in report.get("instances", []):
            inst_name = item["name"]
            sig_prefix = inst_name
            iface_name = "{}_if".format(sig_prefix)
            lines.extend([
                "            begin",
                "                {}.run_test(\"{}\");".format(iface_name, inst_name),
                "            end",
            ])

        lines.extend([
            "        join",
            "        $display(\"All RAM instance tests completed.\");",
            "        #10;",
            "        $finish;",
            "    end",
        ])

    lines.extend([
        "",
        "    initial begin",
        "        $fsdbDumpfile(\"tb.fsdb\");",
        "        $fsdbDumpvars(0, {}, \"+all\");".format(tb_module_name),
        "        $fsdbDumpMDA;",
        "    end",
    ])

    lines.extend(["", "endmodule", ""])
    return "\n".join(lines)


def generate_testbenches(report, output_dir, tb_module_name="pcie_ram_tb"):
    """Generate testbench file(s)."""
    ensure_dir(output_dir)

    for name in os.listdir(output_dir):
        if name.endswith("_tb.sv"):
            try:
                os.remove(os.path.join(output_dir, name))
            except OSError:
                pass

    file_path = os.path.join(output_dir, tb_module_name + ".sv")
    with open(file_path, "w", encoding="utf-8") as handle:
        handle.write(build_combined_testbench_text(report, tb_module_name=tb_module_name))

    return [file_path]


def generate_flist(file_paths, flist_path):
    """Generate design-only file list."""
    flist_dir = os.path.dirname(os.path.abspath(flist_path))
    ensure_dir(flist_dir)

    seen = set()
    ordered_files = []
    for file_path in file_paths:
        norm_path = os.path.abspath(file_path)
        if norm_path not in seen:
            seen.add(norm_path)
            ordered_files.append(norm_path)

    with open(flist_path, "w", encoding="utf-8") as handle:
        for file_path in ordered_files:
            relative_path = os.path.relpath(file_path, flist_dir)
            handle.write(relative_path.replace("\\", "/") + "\n")

    return flist_path


def generate_tb_flist(design_flist_path, tb_files, tb_flist_path):
    """Generate testbench file list."""
    tb_dir = os.path.dirname(os.path.abspath(tb_flist_path))
    ensure_dir(tb_dir)

    with open(tb_flist_path, "w", encoding="utf-8") as handle:
        rel_design_flist = os.path.relpath(os.path.abspath(design_flist_path), tb_dir)
        handle.write("-F {}\n".format(rel_design_flist.replace("\\", "/")))
        for file_path in sorted(tb_files):
            relative_path = os.path.relpath(os.path.abspath(file_path), tb_dir)
            handle.write(relative_path.replace("\\", "/") + "\n")

    return tb_flist_path


def generate_makefile(makefile_path, flist_path, top_module_name="pcie_ram_tb"):
    """Generate VCS/Verdi makefile."""
    out_dir = os.path.dirname(os.path.abspath(makefile_path))
    ensure_dir(out_dir)

    flist_name = os.path.basename(flist_path)
    content = """SIM ?= vcs
WAVE ?= verdi
TOP ?= {top}
FLIST ?= {flist}
LOG ?= vcs.log
SEED ?= 439041101
RUN_PLUSARGS ?= +SEED=$(SEED)
DEFINES ?= +define+INNO_REG_RAM

.PHONY: all sim run verdi clean

all: sim

sim:
	$(SIM) \\
		-sverilog \\
		-F $(FLIST) \\
		-R \\
		-l $(LOG) \\
		-override_timescale=1ns/1ps \\
		-debug_access \\
		-debug_region+cell \\
        -full64 \
        $(RUN_PLUSARGS) $(DEFINES) \
		-top $(TOP)

run: sim

verdi:
	$(WAVE) -2012 $(DEFINES) -f $(FLIST) -top $(TOP) &

clean:
	-$(RM) csrc simv simv.daidir ucli.key *.vpd *.vcd $(LOG)
""".format(flist=flist_name, top=top_module_name)

    with open(makefile_path, "w", encoding="utf-8") as handle:
        handle.write(content)

    return makefile_path
