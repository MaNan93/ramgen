"""Regression coverage for one-pass RAM type rewriting."""
import re
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ramgen import ram_generator as generator


class OutputRewriteTests(unittest.TestCase):
    def rewrite(self, source, instances):
        with tempfile.TemporaryDirectory() as temp:
            original = Path(temp) / "input.sv"
            output = Path(temp) / "output.sv"
            original.write_text(source, encoding="utf-8")
            generator.generate_output_sv(original, output, {"module": "top", "instances": instances}, "pcie_ram")
            self.assertEqual(original.read_text(encoding="utf-8"), source)
            return output.read_text(encoding="utf-8")

    def test_large_rewrite_matches_previous_output(self):
        for count in (1, 1000):
            source = "module top(input clk);\n" + "".join(
                "ram_wrapper #(.WD(8), .DP(16)) u{}(.clk(clk), .dout());\n".format(i) for i in range(count)) + "endmodule\n"
            instances = [{"type": "ram_wrapper", "name": "u{}".format(i),
                          "reference": "my_ram_{}".format(i % 3)} for i in range(count)]
            previous = re.sub(r"\bmodule\s+top\b", "module pcie_ram", source, count=1)
            for item in instances:
                previous = re.sub(r"\bram_wrapper\b(?=\s*(?:#\s*\(.*?\))?\s*{}\b)".format(item["name"]),
                                  item["reference"], previous, count=1, flags=re.DOTALL)
            self.assertEqual(self.rewrite(source, instances), previous)

    def test_comments_strings_nested_parameters_and_arrays(self):
        source = '''// module top; ram_wrapper u0();
module top;
  string label = "ram_wrapper u0(); ( [ module top;";
  /* ram_wrapper #(.N(4)) u0(); */
  ram_wrapper /* type comment */ #(.N(fn(2, 3)), .S("( ]"))
      u0 [3:0] (.a(fn(a, b)), .b());
endmodule
'''
        output = self.rewrite(source, [{"type": "ram_wrapper", "name": "u0", "reference": "my_ram"}])
        self.assertEqual(output, source.replace("\nmodule top;", "\nmodule pcie_ram;")
                         .replace("ram_wrapper /* type comment */", "my_ram /* type comment */"))

    def test_type_and_instance_names_are_matched_exactly(self):
        source = "module top; ram_wrapper u1(); ram_wrapper u10(); other_ram u1(); endmodule"
        output = self.rewrite(source, [{"type": "ram_wrapper", "name": "u1", "reference": "changed"}])
        self.assertEqual(output, "module pcie_ram; changed u1(); ram_wrapper u10(); other_ram u1(); endmodule")

    def test_repeated_instance_names_in_different_modules(self):
        source = "module top; ram_wrapper u0(); endmodule\nmodule helper; ram_wrapper u0(); endmodule"
        output = self.rewrite(source, [{"type": "ram_wrapper", "name": "u0", "reference": "ram_a"},
                                      {"type": "ram_wrapper", "name": "u0", "reference": "ram_b"}])
        self.assertEqual(output, "module pcie_ram; ram_a u0(); endmodule\nmodule helper; ram_b u0(); endmodule")

    def test_no_instances_and_unchanged_reference(self):
        self.assertEqual(self.rewrite("module top; endmodule", []), "module pcie_ram; endmodule")
        self.assertEqual(self.rewrite("module top; ram_wrapper u0(); endmodule",
                                     [{"type": "ram_wrapper", "name": "u0"}]),
                         "module pcie_ram; ram_wrapper u0(); endmodule")


if __name__ == "__main__":
    unittest.main()
