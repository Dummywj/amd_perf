import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "audit_disassembly.py"
SPEC = importlib.util.spec_from_file_location("audit_disassembly", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AuditDisassemblyTest(unittest.TestCase):
    @staticmethod
    def valid_disassembly():
        lines = []
        address = 0
        for name in (*MODULE.KERNEL_SYMBOLS, *MODULE.MICROBENCH_SYMBOLS):
            lines.append(f"{address:04x} <{name}>:")
            form, count = MODULE.INDEPENDENT_FMA_CHAINS.get(name, (None, 0))
            for register in range(count):
                lines.append(
                    f"  {address + register + 1:04x}: vfmacc.{form} "
                    f"v{register}, v16, v17"
                )
            same_vd = MODULE.SAME_VD_STREAMS.get(name)
            if same_vd:
                mnemonic, _, count = same_vd
                mnemonic_text = mnemonic.replace("\\", "")
                operands = "v0, v16" if "vfcvt" in mnemonic else "v0, v16, v17"
                for index in range(count):
                    lines.append(
                        f"  {address + index + 1:04x}: "
                        f"{mnemonic_text} {operands}"
                    )
            memory_stream = MODULE.MEMORY_STREAMS.get(name)
            if memory_stream:
                mnemonic, base, unique_registers = memory_stream
                lines.append(f"  {address + 1:04x}: li t2, 2047")
                lines.append(f"  {address + 1:04x}: add t1, {base}, t0")
                for index in range(16):
                    register = index if unique_registers == 16 else 0
                    lines.append(
                        f"  {address + index + 2:04x}: "
                        f"{mnemonic} v{register}, (t1)"
                    )
                    if index != 15:
                        lines.append(
                            f"  {address + index + 3:04x}: addi t1, t1, 16"
                        )
                lines.append(f"  {address + 0x30:04x}: addi t0, t0, 256")
                lines.append(f"  {address + 0x34:04x}: and t0, t0, t2")
            dependency_chain = MODULE.ORDINARY_VD_MEMORY_CHAINS.get(name)
            if dependency_chain:
                for pattern, count in dependency_chain:
                    if "vle32" in pattern:
                        instruction = "vle32.v v8, (a0)"
                    elif "vfmacc" in pattern:
                        instruction = "vfmacc.vv v8, v16, v17"
                    elif "vadd" in pattern:
                        instruction = "vadd.vv v8, v8, v16"
                    else:
                        instruction = "vse32.v v8, (a1)"
                    lines.extend(
                        f"  {address + index + 0x40:04x}: {instruction}"
                        for index in range(count)
                    )
            address += 0x100
        lines.append("  vsetvli a0, a1, e32, m1, ta, ma")
        return "\n".join(lines)

    def test_accepts_rvv_kernel_symbols(self):
        text = self.valid_disassembly()
        self.assertEqual(MODULE.audit(text)["status"], "PASS")

    def test_rejects_matrix_instruction(self):
        text = self.valid_disassembly() + "\n  msettilem a0\n"
        result = MODULE.audit(text)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["matrix_mnemonics"], ["msettilem"])

    def test_rejects_dependency_limited_fma_throughput(self):
        text = self.valid_disassembly()
        body = MODULE.symbol_body(text, "xsai_mb_fma_throughput")
        shortened = "\n".join(
            line
            for line in body.splitlines()
            if not any(f"v{register}," in line for register in range(8, 16))
        )
        text = text.replace(body, shortened + "\n", 1)

        result = MODULE.audit(text)

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(
            result["insufficient_fma_chains"]["xsai_mb_fma_throughput"],
            {"found": 8, "required": 16},
        )

    def test_rejects_same_vd_stream_with_a_distinct_destination(self):
        text = self.valid_disassembly().replace(
            "vfadd.vv v0, v16, v17", "vfadd.vv v1, v16, v17", 1
        )

        result = MODULE.audit(text)

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(
            result["invalid_same_vd_streams"]["xsai_mb_fp_add_same_vd"],
            {"found": 16, "exact": 15, "required": 16},
        )

    def test_rejects_memory_stream_with_wrong_pointer_step(self):
        text = self.valid_disassembly().replace(
            "addi t1, t1, 16", "addi t1, t1, 32", 1
        )

        result = MODULE.audit(text)

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(
            result["invalid_memory_streams"]["xsai_mb_load_stream_throughput"][
                "pointer_steps"
            ],
            14,
        )

    def test_rejects_v0_memory_dependency_chain(self):
        text = self.valid_disassembly().replace(
            "vle32.v v8, (a0)", "vle32.v v0, (a0)", 1
        )
        result = MODULE.audit(text)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(
            result["invalid_ordinary_vd_memory_chains"][
                "xsai_mb_load_same_vd"
            ][0],
            {"found": 15, "required": 16},
        )


if __name__ == "__main__":
    unittest.main()
