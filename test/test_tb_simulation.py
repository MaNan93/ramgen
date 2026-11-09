"""Run generated SV, including deliberately broken DUTs, when VCS is available."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ramgen import ramgen


def sample_source():
    declarations = []
    for number, (kind, wd, wew) in enumerate([
        ('ram_1p_wrapper', 65, None),
        ('ram_2p_1c_wrapper', 65, None),
        ('ram_2p_2c_wrapper', 65, None),
        ('ram_1p_be_wrapper', 131, 17),
        ('ram_1p_be_wrapper', 17, 3),
    ]):
        params = '.WD({}),.PW(2),.DP(3),.RD_LATENCY(1)'.format(wd)
        if wew is not None:
            params += ',.WEW({})'.format(wew)
        if '2p' in kind:
            ports = ['clka', 'clkb'] if '2c' in kind else ['clk']
            ports += ['addra', 'addrb', 'dina', 'doutb', 'ena', 'enb', 'wea']
        else:
            ports = ['clk', 'addr', 'din', 'dout', 'en', 'we']
        declarations.append('{} #({}) u{} ({});'.format(
            kind, params, number, ','.join('.{}(s{}_{})'.format(p, number, p) for p in ports)))
    return 'module top;\n' + '\n'.join(declarations) + '\nendmodule\n'


@unittest.skipUnless(shutil.which('vcs'), 'VCS is needed for generated HDL regression')
class TestbenchSimulationTests(unittest.TestCase):
    def simulate(self, mutation=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'input.sv'
            source.write_text(sample_source())
            result = ramgen(str(source), str(root / 'out'), verbose=False)
            if mutation:
                for filename in result['wrapper_files']:
                    path = Path(filename)
                    path.write_text(mutation(path.read_text()))
            run = subprocess.run(['make', 'sim'], cwd=root / 'out' / 'tb',
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, timeout=60)
            return run.returncode, run.stdout

    def test_all_interfaces_and_short_byte_lanes(self):
        code, log = self.simulate()
        self.assertEqual(code, 0, log[-6000:])
        self.assertNotIn('FAIL ', log)
        self.assertEqual(log.count('all depth tests passed'), 5)

    def test_disabled_write_fault_is_detected(self):
        code, log = self.simulate(lambda text: text.replace('assign wen = ena && wea;', 'assign wen = wea;'))
        self.assertNotEqual(code, 0, log[-6000:])
        self.assertIn('write gating', log)
        self.assertNotIn('All RAM instance tests completed.', log)

    def test_byte_mask_fault_is_detected(self):
        code, log = self.simulate(lambda text: text.replace('if (we[i])', 'if (we[0])'))
        self.assertNotEqual(code, 0, log[-6000:])
        self.assertIn('byte mask', log)
        self.assertNotIn('All RAM instance tests completed.', log)

    def test_upper_data_bit_fault_is_detected(self):
        code, log = self.simulate(lambda text: text.replace(
            'mem[addra] <= dina;',
            "mem[addra] <= {{(WD-32){dina[31]}}, dina[31:0]};"))
        self.assertNotEqual(code, 0, log[-6000:])
        self.assertIn('random test failed', log)
        self.assertNotIn('All RAM instance tests completed.', log)


if __name__ == '__main__':
    unittest.main()
