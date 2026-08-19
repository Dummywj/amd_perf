import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_hpm_event_map.py"
SPEC = importlib.util.spec_from_file_location("verify_hpm_event_map", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def connection(event_id, signal):
    return f".io_events_sets_{event_id}_value ({signal})"


class HpmEventMapTest(unittest.TestCase):
    def test_current_selectors(self):
        self.assertEqual(
            MODULE.encode_events([105]), 0x3C00000000000069
        )
        self.assertEqual(
            MODULE.encode_events([7, 16, 25]), 0x3C10840001904007
        )
        self.assertEqual(
            MODULE.encode_events([5, 14, 23]), 0x3C10840001703805
        )

    def test_accepts_elaborated_connections(self):
        backend = "\n".join(
            connection(event_id, signal)
            for event_id, signal in MODULE.BACKEND_CONNECTIONS.items()
        )
        memblock = "\n".join(
            connection(event_id, signal)
            for event_id, signal in MODULE.MEMBLOCK_CONNECTIONS.items()
        )
        MODULE.verify_rtl(backend, memblock)

    def test_rejects_event_id_drift(self):
        backend = "\n".join(
            connection(event_id, signal)
            for event_id, signal in MODULE.BACKEND_CONNECTIONS.items()
        )
        memblock = "\n".join(
            connection(event_id, signal)
            for event_id, signal in MODULE.MEMBLOCK_CONNECTIONS.items()
            if event_id != 25
        )
        with self.assertRaises(MODULE.MappingError):
            MODULE.verify_rtl(backend, memblock)


if __name__ == "__main__":
    unittest.main()
