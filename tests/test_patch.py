from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_mcp_server.patch import PatchError, apply_patch_text


class ApplyPatchTests(unittest.TestCase):
    def test_add_update_delete_and_move(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "old.txt").write_text("alpha\nbeta\n", encoding="utf-8")
            (root / "delete.txt").write_text("gone\n", encoding="utf-8")
            patch = """*** Begin Patch
*** Add File: added.txt
+hello
+world
*** Update File: old.txt
*** Move to: renamed.txt
@@
-alpha
+ALPHA
 beta
*** Delete File: delete.txt
*** End Patch"""

            result = apply_patch_text(patch, root)

            self.assertEqual((root / "added.txt").read_text(encoding="utf-8"), "hello\nworld\n")
            self.assertEqual((root / "renamed.txt").read_text(encoding="utf-8"), "ALPHA\nbeta\n")
            self.assertFalse((root / "old.txt").exists())
            self.assertFalse((root / "delete.txt").exists())
            self.assertEqual(result["added"], ["added.txt"])
            self.assertEqual(result["modified"], ["renamed.txt"])
            self.assertEqual(result["deleted"], ["delete.txt"])

    def test_rejects_missing_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("one\ntwo\n", encoding="utf-8")
            patch = """*** Begin Patch
*** Update File: file.txt
@@
-three
+four
*** End Patch"""

            with self.assertRaises(PatchError):
                apply_patch_text(patch, root)


if __name__ == "__main__":
    unittest.main()
