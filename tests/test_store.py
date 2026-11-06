"""Offline tests for the document store: key encryption (optional) and MongoDB sync."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("COMFORTABLE_WORKSPACE", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))

from comfortable import config, crypto, store  # noqa: E402


def fresh_store():
    config.LOCAL_DB = Path(tempfile.mkdtemp()) / "test.db"
    return store.Store()


def set_passphrase(value):
    config.SECRET_KEY = value
    crypto._fernet = None


class KeyEncryption(unittest.TestCase):
    def tearDown(self):
        set_passphrase("")

    def test_unencrypted_by_default_and_says_so(self):
        st = fresh_store()
        st.update_settings({"hf_token": "hf_plain"})
        self.assertEqual(st.get("settings", "hf_token")["value"], "hf_plain")
        self.assertEqual(st.setting("hf_token"), "hf_plain")
        keys = st.status()["keys"]
        self.assertFalse(keys["encrypted"])
        self.assertIn("unencrypted", keys["message"])
        self.assertIn("on purpose", keys["message"])

    def test_passphrase_encrypts_stored_keys(self):
        set_passphrase("correct horse")
        st = fresh_store()
        st.update_settings({"civitai_token": "civ_secret", "concurrency": 4})
        stored = st.get("settings", "civitai_token")["value"]
        self.assertTrue(stored.startswith(crypto.PREFIX))
        self.assertNotIn("civ_secret", stored)
        self.assertEqual(st.setting("civitai_token"), "civ_secret")
        self.assertEqual(st.get("settings", "concurrency")["value"], 4)  # only keys are encrypted
        self.assertTrue(st.status()["keys"]["encrypted"])

    def test_keys_saved_before_the_passphrase_get_encrypted(self):
        st = fresh_store()
        st.update_settings({"hf_token": "hf_old"})
        set_passphrase("pw")
        st.encrypt_existing_keys()
        self.assertTrue(crypto.is_encrypted(st.get("settings", "hf_token")["value"]))
        self.assertEqual(st.setting("hf_token"), "hf_old")

    def test_missing_or_wrong_passphrase_reads_as_missing(self):
        set_passphrase("pw")
        st = fresh_store()
        st.update_settings({"hf_token": "hf_x"})
        for other in ("", "wrong"):
            set_passphrase(other)
            self.assertEqual(st.setting("hf_token"), "")
            self.assertEqual(st.status()["keys"]["unreadable"], ["hf_token"])

    def test_clearing_a_key(self):
        set_passphrase("pw")
        st = fresh_store()
        st.update_settings({"hf_token": "hf_x"})
        st.update_settings({"hf_token": ""})
        self.assertEqual(st.setting("hf_token"), "")


if __name__ == "__main__":
    unittest.main()
