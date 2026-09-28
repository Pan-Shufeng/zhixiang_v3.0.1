import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
import tomllib

import connections as c


class ClientConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="知向 连接测试 ")
        self.home = Path(self.temp.name)
        self.root = self.home / "应用 中文 空格"

    def tearDown(self):
        self.temp.cleanup()

    def test_codex_preserves_unrelated_settings_and_rollback(self):
        path = c.target("codex", self.home)
        path.parent.mkdir()
        original = '# keep comment\nmodel = "example"\n[mcp_servers.other]\ncommand = "other"\n'
        path.write_text(original, encoding="utf-8")
        result = c.configure("codex", home=self.home, root=self.root)
        self.assertEqual(Path(result["backup"]).read_text(encoding="utf-8"), original)
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(parsed["mcp_servers"]["other"]["command"], "other")
        self.assertIn("应用 中文 空格", parsed["mcp_servers"]["zhixiang"]["args"][2])
        content = path.read_bytes()
        c.configure("codex", home=self.home, root=self.root)
        self.assertEqual(content, path.read_bytes())
        with path.open("a", encoding="utf-8") as f:
            f.write('\n[mcp_servers.later]\ncommand = "later"\n')
        c.configure("codex", True, home=self.home, root=self.root)
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(parsed["mcp_servers"]), {"other", "later"})
        self.assertIn("# keep comment", path.read_text(encoding="utf-8"))

    def test_workbuddy_preserves_other_servers_and_new_edits(self):
        path = c.target("workbuddy", self.home)
        path.parent.mkdir()
        path.write_text(json.dumps({"mcpServers": {"existing": {"command": "old"}}, "extra": True}))
        c.configure("workbuddy", home=self.home, root=self.root)
        config = json.loads(path.read_text(encoding="utf-8"))
        config["mcpServers"]["added_later"] = {"command": "new"}
        path.write_text(json.dumps(config))
        c.configure("workbuddy", True, home=self.home, root=self.root)
        config = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(config["extra"])
        self.assertEqual(set(config["mcpServers"]), {"existing", "added_later"})

    def test_conflicting_other_installation_is_never_replaced(self):
        c.configure("workbuddy", home=self.home, root=self.root)
        path = c.target("workbuddy", self.home)
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            c.configure("workbuddy", home=self.home, root=self.home / "another")
        self.assertEqual(before, path.read_bytes())

    def test_corrupt_config_is_not_overwritten(self):
        path = c.target("codex", self.home)
        path.parent.mkdir()
        path.write_text("not valid = [")
        with self.assertRaises(ValueError):
            c.configure("codex", home=self.home, root=self.root)
        self.assertEqual(path.read_text(), "not valid = [")

    def test_manual_edit_to_owned_codex_entry_blocks_removal(self):
        c.configure("codex", home=self.home, root=self.root)
        path = c.target("codex", self.home)
        text = path.read_text(encoding="utf-8").replace("tool_timeout_sec = 180", "tool_timeout_sec = 200")
        path.write_text(text, encoding="utf-8")
        with self.assertRaises(ValueError):
            c.configure("codex", True, home=self.home, root=self.root)
        self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_diagnostic_cannot_claim_a_real_client_call(self):
        c.record_event({"client": "diagnostic", "stage": "tool_called"}, self.root)
        self.assertEqual(c.read_events(self.root), {})

    def test_handshake_event_does_not_wait_for_dsh_launch_lock(self):
        with ThreadPoolExecutor(max_workers=1) as pool:
            with c.LOCK:
                result = pool.submit(c.record_event, {"client":"dsh", "stage":"initialized"}, self.root).result(timeout=2)
                self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
