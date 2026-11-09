"""Contract validation independent of external parsers and proprietary inputs."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ramgen.ram_analyzer import analyze_sv_file
from ramgen.main import ramgen


def declaration(ram_type="ram_1p_be_wrapper", wd="131", wew="17", pw="1", dp="2"):
    params = ".WD({}),.PW({}),.DP({}),.RD_LATENCY(1)".format(wd, pw, dp)
    if wew is not None:
        params += ",.WEW({})".format(wew)
    if "2p" in ram_type:
        clocks = ".clka(write_clk),.clkb(read_clk)" if "2c" in ram_type else ".clk(core_clk)"
        ports = clocks + ",.addra(wa),.addrb(ra),.dina(data_from_host),.doutb(data_to_host),.ena(a_en),.enb(b_en),.wea(wr)"
    else:
        ports = ".clk(core_clk),.addr(a),.din(external_dout),.dout(external_din),.en(e),.we(w)"
    return "module top; {} #({}) u0({}); endmodule".format(ram_type, params, ports)


class InterfaceAnalysisTests(unittest.TestCase):
    def analyze(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.sv"
            path.write_text(source)
            return analyze_sv_file(path)

    def test_four_supported_interfaces(self):
        for ram_type in ("ram_1p_wrapper", "ram_1p_be_wrapper", "ram_2p_1c_wrapper", "ram_2p_2c_wrapper"):
            with self.subTest(ram_type=ram_type):
                report = self.analyze(declaration(ram_type, wew="17" if "_be_" in ram_type else None))
                self.assertEqual(report["diagnostics"], [])
                iface = report["instances"][0]["interface"]
                self.assertEqual(iface["byte_enable"], "_be_" in ram_type)
                self.assertEqual(iface["ports"]["dina" if "2p" in ram_type else "din"]["width"], 131)
                self.assertEqual(iface["ports"]["doutb" if "2p" in ram_type else "dout"]["direction"], "output")

    def test_be_byte_boundaries(self):
        for wd, wew, last in ((64, 8, 8), (131, 17, 3), (17, 3, 1)):
            iface = self.analyze(declaration(wd=str(wd), wew=str(wew)))["instances"][0]["interface"]
            self.assertEqual(iface["ports"]["we"]["width"], wew)
            self.assertEqual(iface["byte_lane_width"], 8)
            self.assertEqual(iface["last_lane_width"], last)

    def test_dual_clock_connections_remain_distinct(self):
        iface = self.analyze(declaration("ram_2p_2c_wrapper", wew=None))["instances"][0]["interface"]
        self.assertEqual((iface["write_clock"], iface["read_clock"]), ("clka", "clkb"))
        self.assertEqual(iface["ports"]["clka"]["connection"], "write_clk")
        self.assertEqual(iface["ports"]["clkb"]["connection"], "read_clk")

    def test_invalid_contracts_have_actionable_codes(self):
        cases = [
            (declaration(wew="16"), "byte_enable_width"),
            (declaration(dp="3"), "address_capacity"),
            (declaration(wd="0"), "invalid_parameter"),
            (declaration(wew=None), "missing_parameter"),
            (declaration("ram_1p_wrapper"), "unexpected_parameter"),
            (declaration().replace(".en(e)", ".en()"), "unconnected_input"),
            (declaration().replace(",.en(e)", ""), "missing_port"),
            (declaration().replace(".en(e)", ".enable(e)"), "unknown_port"),
        ]
        for source, code in cases:
            with self.subTest(code=code):
                report = self.analyze(source)
                self.assertFalse(report["validation_passed"])
                self.assertIn(code, [entry["code"] for entry in report["diagnostics"]])

    def test_unresolved_width_is_reported_without_inventing_a_value(self):
        report = self.analyze(declaration(wd="WIDTH", wew="MASK_WIDTH"))
        self.assertIsNone(report["instances"][0]["interface"]["ports"]["we"]["width"])
        self.assertIn("unresolved_parameter", [entry["code"] for entry in report["diagnostics"]])

    def test_unknown_type_is_not_assigned_a_guessed_contract(self):
        report = self.analyze("module top; custom_ram u0(.we(w)); endmodule")
        self.assertIsNone(report["instances"][0]["interface"])
        self.assertEqual(report["diagnostics"][0]["code"], "unknown_ram_type")

    def test_generation_leaves_no_artifacts_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "input.sv", Path(tmp) / "generated"
            source.write_text(declaration(wew="1"))
            with self.assertRaises(ValueError):
                ramgen(str(source), str(output), verbose=False)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
