"""Real analyzer/generator reproductions: strings, nesting and shared types."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ramgen.ram_analyzer import analyze_sv_file
from ramgen.ram_generator import generate_output_sv
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vutils/src"))
from vutils.vparser import VeribleParser


class AnalysisRegressionTests(unittest.TestCase):
    def analyze(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.sv"
            path.write_text(source, encoding="utf-8")
            report = analyze_sv_file(path)
            output = Path(tmp) / "output.sv"
            generate_output_sv(path, output, report, "pcie_ram")
            text = output.read_text(encoding="utf-8")
            self.assertFalse(VeribleParser().parse_string(text, {"gen_tree": False}).errors)
            return report, text

    def test_nested_parameter_and_connection_expressions(self):
        source = "module top; ram_wrapper #(.WD((4+4)), .DP(16)) u0(.din(fn(a,b)),.dout()); endmodule"
        report, output = self.analyze(source)
        self.assertEqual(report["instance_count"], 1)
        instance = report["instances"][0]
        self.assertEqual(instance["params"]["WD"], "(4+4)")
        self.assertEqual(instance["ports"]["din"], "fn(a,b)")
        self.assertEqual(instance["total_bits"], 128)
        self.assertEqual(instance["reference"], "ram_16wx8")
        self.assertIn("ram_16wx8", output)

    def test_multiple_instances_share_parameter_declaration(self):
        source = "module top; ram_wrapper #(.WD(8),.DP(16)) u0(.din(a)), u1(.din(b)); endmodule"
        report, output = self.analyze(source)
        self.assertEqual([i["name"] for i in report["instances"]], ["u0", "u1"])
        self.assertEqual(report["total_bits"], 256)
        self.assertIn("ram_16wx8 #(.WD(8),.DP(16)) u0(.din(a)), u1(.din(b));", output)

    def test_strings_and_comments_cannot_create_fake_instances(self):
        source = ('// module bogus; ram_wrapper ghost();\nmodule top; '
                  'string s="ram_wrapper u_fake(); // not comment"; '
                  'ram_wrapper #(.WD(8),.DP(16)) u0(.din(a)); endmodule')
        report, output = self.analyze(source)
        self.assertEqual(report["module"], "top")
        self.assertEqual([i["name"] for i in report["instances"]], ["u0"])
        self.assertIn('string s="ram_wrapper u_fake(); // not comment";', output)

    def test_comment_between_tokens_and_multidimensional_array(self):
        source = "module top; ram_wrapper /* detail */ #(.WD(8),.DP(16)) u0[1:0][2:0](.din(a)); endmodule"
        report, output = self.analyze(source)
        self.assertEqual(report["instance_count"], 1)
        self.assertEqual(report["instances"][0]["array_size"], 6)
        self.assertEqual(report["total_bits"], 768)
        self.assertIn("ram_16wx8 /* detail */", output)

    def test_macro_definitions_do_not_create_instances(self):
        definition = ("`define SAMPLE ram_wrapper ghost(); \\\n"
                      "  ram_wrapper ghost2();\n")
        report, output = self.analyze(definition + "module top; ram_wrapper u0(); endmodule")
        self.assertEqual([i["name"] for i in report["instances"]], ["u0"])
        self.assertTrue(output.startswith(definition))

    def test_module_lifetime_and_end_label_rename(self):
        report, output = self.analyze("module automatic top; ram_wrapper u0(); endmodule : top")
        self.assertEqual(report["module"], "top")
        self.assertIn("module automatic pcie_ram;", output)
        self.assertIn("endmodule : pcie_ram", output)

    def test_comments_inside_parameter_and_port_expressions(self):
        report, output = self.analyze(
            "module top; ram_wrapper #(.WD(4 /* width */ + 4), .DP(16)) "
            "u0(.din(fn(a /* signal */, b)), .dout()); endmodule")
        self.assertEqual(report["instances"][0]["total_bits"], 128)
        self.assertIn("ram_16wx8", output)

    def test_unresolved_complex_dimensions_keep_original_expression(self):
        report, output = self.analyze("module top #(parameter DP=16); ram_wrapper #(.WD(8),.DP(DP/2)) u0(); endmodule")
        self.assertIn(".DP(DP/2)", output)
        self.assertRegex(report["instances"][0]["reference"], r"^ram_expr_[0-9a-f]{12}wx8$")

    def test_shared_declaration_can_be_split_for_different_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, output = Path(tmp) / "in.sv", Path(tmp) / "out.sv"
            path.write_text("module top; ram_wrapper #(.WD(8)) u0(.a(a)), u1(.a(b)); endmodule")
            report = {"module": "top", "instances": [
                {"type": "ram_wrapper", "name": "u0", "reference": "ram_a"},
                {"type": "ram_wrapper", "name": "u1", "reference": "ram_b"}]}
            generate_output_sv(path, output, report)
            text = output.read_text()
            self.assertIn("ram_a #(.WD(8)) u0(.a(a));", text)
            self.assertIn("ram_b #(.WD(8))", text)
            self.assertFalse(VeribleParser().parse_string(text, {"gen_tree": False}).errors)


if __name__ == "__main__":
    unittest.main()
