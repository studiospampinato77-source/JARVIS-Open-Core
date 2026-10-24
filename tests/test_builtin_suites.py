import unittest

import _paths  # noqa: F401
import jarvis_evidence_gold_gate_v5 as gold
import jarvis_ingestion_gateway_v5 as gateway


class BuiltinSuitesTest(unittest.TestCase):
    def check(self, out):
        failed = [t for t in out["tests"] if not t["ok"]]
        self.assertFalse(failed, failed)

    def test_evidence_gold_gate_suite(self):
        self.check(gold.run_local_tests())

    def test_ingestion_gateway_suite(self):
        self.check(gateway.run_local_tests())

    def test_pdf_without_reader_is_reported_not_crashing(self):
        import tempfile
        from pathlib import Path
        p = Path(tempfile.mkdtemp()) / "doc.pdf"
        p.write_bytes(b"%PDF-1.4\n%fake\n")
        rec = gateway.ingest({"source_id": "LOCAL_FILE", "path": str(p)}, persist=False)
        self.assertIn("READER_NOT_INCLUDED:PDF", rec["errors"])


if __name__ == "__main__":
    unittest.main()
