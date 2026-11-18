"""One offline validation entry point, with explicit executed-check evidence."""
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from .contracts import REPO_ROOT, atomic_json, utc_now


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed.append(test.id())


def validate_local(output: Path):
    suite = unittest.defaultTestLoader.discover(str(REPO_ROOT / "tests"))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=EvidenceResult).run(suite)
    evidence = {"executed_at": utc_now(), "engine": "Python unittest; local only", "python_version": sys.version.split()[0],
                "test_count": result.testsRun, "passed": result.passed,
                "failures": [{"test": test.id(), "detail": detail} for test, detail in result.failures],
                "errors": [{"test": test.id(), "detail": detail} for test, detail in result.errors],
                "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
                "status": "passed" if result.wasSuccessful() else "failed",
                "scope": "Contracts, metrics, time conversion, source failure handling, local replay/recovery, credential/field boundaries. This does not execute BigQuery or Power BI."}
    atomic_json(output, evidence)
    if result.wasSuccessful():
        from .replay_demo import run_replay_demo
        replay = run_replay_demo(REPO_ROOT / "artifacts/replay/local-replay.json")
        print(json.dumps({"status": "passed", "tests": result.testsRun, "evidence": str(output), "replay_evidence": "artifacts/replay/local-replay.json"}))
        return 0
    print(stream.getvalue(), file=sys.stderr)
    print(json.dumps({"status": "failed", "tests": result.testsRun, "evidence": str(output)}))
    return 1
