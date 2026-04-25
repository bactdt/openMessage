import json
import os
import time
import tempfile
import unittest
from unittest.mock import patch

import storage
import crypto_utils


class TestStorageVersionCompat(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.patcher = patch.object(storage, "DATA_DIR", self.tmp_dir)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def tearDown(self):
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)

    def _write_legacy_file(self, msg_id, data):
        path = os.path.join(self.tmp_dir, f"{msg_id}.json")
        with open(path, "w") as f:
            json.dump(data, f)
        os.chmod(path, 0o600)
        return path

    def test_get_metadata_legacy_no_version(self):
        msg_id = str(storage.uuid.uuid4())
        now = int(time.time())
        self._write_legacy_file(
            msg_id,
            {
                "id": msg_id,
                "ciphertext": "AAA",
                "created_at": now,
                "expires_at": now + 3600,
                "has_password": False,
                "password_hash": None,
            },
        )
        meta = storage.get_message_metadata(msg_id)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["id"], msg_id)
        self.assertFalse(meta["has_password"])

    def test_get_metadata_legacy_no_version_expired(self):
        msg_id = str(storage.uuid.uuid4())
        now = int(time.time())
        self._write_legacy_file(
            msg_id,
            {
                "id": msg_id,
                "ciphertext": "AAA",
                "created_at": now - 7200,
                "expires_at": now - 3600,
                "has_password": False,
                "password_hash": None,
            },
        )
        meta = storage.get_message_metadata(msg_id)
        self.assertIsNone(meta)

    def test_pop_message_legacy_no_version(self):
        msg_id = str(storage.uuid.uuid4())
        now = int(time.time())
        self._write_legacy_file(
            msg_id,
            {
                "id": msg_id,
                "ciphertext": "AAA",
                "created_at": now,
                "expires_at": now + 3600,
                "has_password": False,
                "password_hash": None,
            },
        )
        data = storage.pop_message(msg_id)
        self.assertIsNotNone(data)
        self.assertEqual(data["id"], msg_id)
        self.assertEqual(data["version"], storage.PROTOCOL_VERSION)

    def test_verify_and_pop_legacy_no_version(self):
        msg_id = str(storage.uuid.uuid4())
        now = int(time.time())
        self._write_legacy_file(
            msg_id,
            {
                "id": msg_id,
                "ciphertext": "AAA",
                "created_at": now,
                "expires_at": now + 3600,
                "has_password": False,
                "password_hash": None,
            },
        )
        data, error = storage.verify_and_pop(msg_id)
        self.assertIsNone(error)
        self.assertIsNotNone(data)
        self.assertEqual(data["id"], msg_id)
        self.assertEqual(data["version"], storage.PROTOCOL_VERSION)

    def test_verify_and_pop_legacy_no_version_with_password(self):
        msg_id = str(storage.uuid.uuid4())
        now = int(time.time())
        pwhash = crypto_utils.hash_password("secret")
        self._write_legacy_file(
            msg_id,
            {
                "id": msg_id,
                "ciphertext": "AAA",
                "created_at": now,
                "expires_at": now + 3600,
                "has_password": True,
                "password_hash": pwhash,
            },
        )
        data, error = storage.verify_and_pop(
            msg_id,
            password_verify_fn=lambda pw_hash: crypto_utils.verify_password(
                "secret", pw_hash
            ),
        )
        self.assertIsNone(error)
        self.assertIsNotNone(data)
        self.assertEqual(data["id"], msg_id)
        self.assertEqual(data["version"], storage.PROTOCOL_VERSION)

    def test_verify_and_pop_legacy_wrong_password(self):
        msg_id = str(storage.uuid.uuid4())
        now = int(time.time())
        pwhash = crypto_utils.hash_password("secret")
        self._write_legacy_file(
            msg_id,
            {
                "id": msg_id,
                "ciphertext": "AAA",
                "created_at": now,
                "expires_at": now + 3600,
                "has_password": True,
                "password_hash": pwhash,
            },
        )
        data, error = storage.verify_and_pop(
            msg_id,
            password_verify_fn=lambda pw_hash: crypto_utils.verify_password(
                "wrong", pw_hash
            ),
        )
        self.assertEqual(error, "wrong_password")
        self.assertIsNone(data)
        meta = storage.get_message_metadata(msg_id)
        self.assertIsNotNone(meta)

    def test_ensure_version_adds_v1_when_missing(self):
        data = {"id": "x", "ciphertext": "AAA"}
        result = storage._ensure_version(data)
        self.assertEqual(result["version"], "v1")

    def test_ensure_version_preserves_existing(self):
        data = {"id": "x", "version": "v1", "ciphertext": "AAA"}
        result = storage._ensure_version(data)
        self.assertEqual(result["version"], "v1")

    def test_validate_version_rejects_unknown(self):
        self.assertFalse(storage._validate_version({"version": "v999"}))

    def test_validate_version_accepts_v1(self):
        self.assertTrue(storage._validate_version({"version": "v1"}))

    def test_save_message_includes_version(self):
        msg_id = storage.save_message("ciphertext", 3600)
        path = os.path.join(self.tmp_dir, f"{msg_id}.json")
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["version"], "v1")


class TestStorageErrorCodes(unittest.TestCase):
    def test_error_code_values_match_existing_returns(self):
        self.assertEqual(storage.ERROR_INVALID_ID, "invalid_id")
        self.assertEqual(storage.ERROR_NOT_FOUND, "not_found")
        self.assertEqual(storage.ERROR_UNSUPPORTED_VERSION, "unsupported_version")
        self.assertEqual(storage.ERROR_EXPIRED, "expired")
        self.assertEqual(storage.ERROR_PASSWORD_REQUIRED, "password_required")
        self.assertEqual(storage.ERROR_WRONG_PASSWORD, "wrong_password")
        self.assertEqual(storage.ERROR_LOCKED, "locked")

    def test_retryable_errors_contains_only_locked(self):
        self.assertEqual(storage.RETRYABLE_ERRORS, {storage.ERROR_LOCKED})

    def test_is_retryable_error_with_locked_is_true(self):
        self.assertTrue(storage.is_retryable_error(storage.ERROR_LOCKED))

    def test_is_retryable_error_with_non_retryable_is_false(self):
        for err in [
            storage.ERROR_INVALID_ID,
            storage.ERROR_NOT_FOUND,
            storage.ERROR_EXPIRED,
            storage.ERROR_UNSUPPORTED_VERSION,
            storage.ERROR_PASSWORD_REQUIRED,
            storage.ERROR_WRONG_PASSWORD,
        ]:
            self.assertFalse(
                storage.is_retryable_error(err),
                f"{err} must not be retryable",
            )

    def test_is_retryable_error_with_none_is_false(self):
        self.assertFalse(storage.is_retryable_error(None))


class TestVerifyAndPopReturnsErrorCodes(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.patcher = patch.object(storage, "DATA_DIR", self.tmp_dir)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def tearDown(self):
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)

    def test_verify_and_pop_invalid_id_returns_const(self):
        _, error = storage.verify_and_pop("not-a-uuid")
        self.assertEqual(error, storage.ERROR_INVALID_ID)

    def test_verify_and_pop_not_found_returns_const(self):
        msg_id = str(storage.uuid.uuid4())
        _, error = storage.verify_and_pop(msg_id)
        self.assertEqual(error, storage.ERROR_NOT_FOUND)

    def test_verify_and_pop_password_required_returns_const(self):
        msg_id = str(storage.uuid.uuid4())
        now = int(time.time())
        pwhash = crypto_utils.hash_password("secret")
        path = os.path.join(self.tmp_dir, f"{msg_id}.json")
        data = {
            "id": msg_id,
            "ciphertext": "AAA",
            "created_at": now,
            "expires_at": now + 3600,
            "has_password": True,
            "password_hash": pwhash,
        }
        with open(path, "w") as f:
            json.dump(data, f)
        os.chmod(path, 0o600)

        _, error = storage.verify_and_pop(msg_id)
        self.assertEqual(error, storage.ERROR_PASSWORD_REQUIRED)

    def test_verify_and_pop_wrong_password_returns_const(self):
        msg_id = str(storage.uuid.uuid4())
        now = int(time.time())
        pwhash = crypto_utils.hash_password("secret")
        path = os.path.join(self.tmp_dir, f"{msg_id}.json")
        data = {
            "id": msg_id,
            "ciphertext": "AAA",
            "created_at": now,
            "expires_at": now + 3600,
            "has_password": True,
            "password_hash": pwhash,
        }
        with open(path, "w") as f:
            json.dump(data, f)
        os.chmod(path, 0o600)

        _, error = storage.verify_and_pop(
            msg_id,
            password_verify_fn=lambda pw_hash: crypto_utils.verify_password(
                "wrong", pw_hash
            ),
        )
        self.assertEqual(error, storage.ERROR_WRONG_PASSWORD)


if __name__ == "__main__":
    unittest.main()
