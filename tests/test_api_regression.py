import shutil
import tempfile
import unittest
from unittest.mock import patch

import storage
from app import app


class TestApiLoggingRegression(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir_patcher = patch.object(storage, "DATA_DIR", self.tmp_dir)
        self.data_dir_patcher.start()
        self.addCleanup(self.data_dir_patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp_dir)

        self.previous_testing = app.config.get("TESTING")
        self.previous_rate_limit = app.config.get("RATELIMIT_ENABLED")
        app.config["TESTING"] = True
        app.config["RATELIMIT_ENABLED"] = False
        self.addCleanup(self._restore_app_config)

        storage._last_cleanup_at = 0
        storage._last_cleanup_cursor = 0
        self.client = app.test_client()

    def _restore_app_config(self):
        app.config["TESTING"] = self.previous_testing
        app.config["RATELIMIT_ENABLED"] = self.previous_rate_limit

    def _create_message(self, content="hello", password=None):
        payload = {"content": content, "expires_in": 3600}
        if password is not None:
            payload["password"] = password

        response = self.client.post(
            "/api/message",
            json=payload,
            headers={"X-Request-ID": "test-request-id"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(set(data.keys()), {"id", "key"})
        self.assertTrue(storage.validate_msg_id(data["id"]))
        self.assertIsInstance(data["key"], str)
        return data

    def test_create_and_read_message_api_behavior_is_unchanged(self):
        created = self._create_message("secret text")

        response = self.client.post(
            f"/api/message/{created['id']}",
            json={"key": created["key"]},
            headers={"X-Request-ID": "test-request-id"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"content": "secret text"})

        second_response = self.client.post(
            f"/api/message/{created['id']}",
            json={"key": created["key"]},
            headers={"X-Request-ID": "test-request-id"},
        )
        self.assertEqual(second_response.status_code, 404)
        self.assertEqual(
            second_response.get_json(),
            {"error": "Secret not found or already read"},
        )

    def test_password_message_api_behavior_is_unchanged(self):
        created = self._create_message("password protected", password="secret")

        missing_password = self.client.post(
            f"/api/message/{created['id']}",
            json={"key": created["key"]},
            headers={"X-Request-ID": "test-request-id"},
        )
        self.assertEqual(missing_password.status_code, 401)
        self.assertEqual(
            missing_password.get_json(),
            {"error": "Password required", "needs_password": True},
        )

        wrong_password = self.client.post(
            f"/api/message/{created['id']}",
            json={"key": created["key"], "password": "wrong"},
            headers={"X-Request-ID": "test-request-id"},
        )
        self.assertEqual(wrong_password.status_code, 401)
        self.assertEqual(wrong_password.get_json(), {"error": "Incorrect password"})

        correct_password = self.client.post(
            f"/api/message/{created['id']}",
            json={"key": created["key"], "password": "secret"},
            headers={"X-Request-ID": "test-request-id"},
        )
        self.assertEqual(correct_password.status_code, 200)
        self.assertEqual(correct_password.get_json(), {"content": "password protected"})

    def test_invalid_key_error_response_is_unchanged(self):
        created = self._create_message("secret text")

        response = self.client.post(
            f"/api/message/{created['id']}",
            json={"key": "invalid-key"},
            headers={"X-Request-ID": "test-request-id"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"error": "Decryption failed (invalid key)"},
        )

    def test_locked_message_api_returns_retryable_conflict(self):
        created = self._create_message("secret text")

        with patch.object(
            storage,
            "verify_and_pop",
            return_value=(None, storage.ERROR_LOCKED),
        ):
            response = self.client.post(
                f"/api/message/{created['id']}",
                json={"key": created["key"]},
                headers={"X-Request-ID": "test-request-id"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json(),
            {"error": "Secret is temporarily locked", "retryable": True},
        )


if __name__ == "__main__":
    unittest.main()
