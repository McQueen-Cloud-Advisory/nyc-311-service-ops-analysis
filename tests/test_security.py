"""Network-free regressions for credential boundaries and filesystem identifiers."""
import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.request import Request

from nyc311.cli import main
from nyc311.contracts import ContractError
from nyc311.source import BASE_URL, Socrata, SourceRedirectHandler


class SourceRedirectTests(unittest.TestCase):
    def test_off_origin_redirect_is_blocked_before_following(self):
        handler = SourceRedirectHandler()
        handler.parent = Mock()
        request = Request(BASE_URL + "/resource/erm2-nwe9.json", headers={"X-App-Token": "synthetic-token-for-test"})
        # The redirect handler must reject before parent.open could transmit headers.
        for destination in (
            "https://untrusted.example/capture",
            "http://data.cityofnewyork.us/capture",
            "https://data.cityofnewyork.us.untrusted.example/capture",
            "https://data.cityofnewyork.us:444/capture",
            "https://user@data.cityofnewyork.us/capture",
        ):
            with self.subTest(destination=destination):
                headers = Message()
                headers["Location"] = destination
                with self.assertRaises(ContractError):
                    handler.http_error_302(request, io.BytesIO(b""), 302, "Found", headers)
                handler.parent.open.assert_not_called()

    def test_same_origin_https_redirect_is_allowed(self):
        handler = SourceRedirectHandler()
        request = Request(BASE_URL + "/old", headers={"X-App-Token": "synthetic-token-for-test"})
        redirected = handler.redirect_request(request, None, 302, "Found", {}, BASE_URL + "/new")
        self.assertEqual(redirected.full_url, BASE_URL + "/new")
        self.assertEqual(redirected.get_header("X-app-token"), "synthetic-token-for-test")

    def test_socrata_installs_pre_follow_guard(self):
        client = Socrata({})
        handlers = [handler for handler in client.opener.handlers if isinstance(handler, SourceRedirectHandler)]
        self.assertEqual(len(handlers), 1)


class CaptureAuditTests(unittest.TestCase):
    def test_invalid_snapshot_ids_cannot_write_audit_or_contact_sources(self):
        for snapshot_id in ("../escaped", "../../escaped", r"..\escaped", "/absolute", "C:\\escaped"):
            with self.subTest(snapshot_id=snapshot_id), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "should-not-exist.json"
                with (
                    patch("nyc311.cli.load_config") as config,
                    patch("nyc311.cli.atomic_json") as audit_write,
                    patch("nyc311.cli.operator_lock") as lock,
                    patch("nyc311.source.Socrata.capture") as capture,
                    patch("sys.stderr", new_callable=io.StringIO),
                ):
                    result = main(["capture", "--snapshot-id", snapshot_id, "--output", str(output)])
                self.assertEqual(result, 2)
                config.assert_not_called()
                lock.assert_not_called()
                audit_write.assert_not_called()
                capture.assert_not_called()
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_cloud_example_uses_the_infrastructure_region(self):
        root = Path(__file__).resolve().parents[1]
        runtime = json.loads((root / "config/cloud.example.json").read_text(encoding="utf-8"))
        infrastructure = json.loads((root / "infra/gcp.example.json").read_text(encoding="utf-8"))
        self.assertEqual(runtime["location"], infrastructure["location"])


class SheetsRedirectTests(unittest.TestCase):
    def test_authenticated_sheets_get_does_not_follow_redirects(self):
        # Stub cloud dependencies so this check also runs in the local-only install.
        import sys
        import types
        from nyc311.targets import load_sheets

        google_module = types.ModuleType("google")
        auth_module = types.ModuleType("google.auth")
        transport_module = types.ModuleType("google.auth.transport")
        requests_module = types.ModuleType("google.auth.transport.requests")
        google_module.auth = auth_module
        auth_module.transport = transport_module
        transport_module.requests = requests_module
        auth_module.default = Mock(return_value=(object(), None))
        session = Mock()
        session.get.return_value.status_code = 302
        requests_module.AuthorizedSession = Mock(return_value=session)
        modules = {
            "google": google_module, "google.auth": auth_module,
            "google.auth.transport": transport_module, "google.auth.transport.requests": requests_module,
        }
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(ContractError, "HTTP 302"):
                load_sheets("synthetic_sheet_id", "Targets!A:E")
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])
        auth_module.default.assert_called_once_with(scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])


if __name__ == "__main__":
    unittest.main()
