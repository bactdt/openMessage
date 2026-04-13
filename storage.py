import os
import json
import re
import uuid
import time
import sys
from typing import Optional, Dict, Any, Tuple

if getattr(sys, "frozen", False):
    DATA_DIR = os.path.join(os.path.dirname(sys.executable), "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

CLEANUP_INTERVAL_SECONDS = 300
_last_cleanup_at = 0
_last_cleanup_cursor = 0


def _take_message(file_path: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    held_path = f"{file_path}.lock-{uuid.uuid4().hex}"
    try:
        os.replace(file_path, held_path)
    except FileNotFoundError:
        return None, None
    except OSError:
        return None, None

    try:
        with open(held_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        _delete_held_message(held_path)
        return held_path, None

    return held_path, data


def _delete_held_message(held_path: str) -> None:
    try:
        os.remove(held_path)
    except OSError:
        pass


def _restore_held_message(held_path: str, file_path: str) -> None:
    try:
        os.replace(held_path, file_path)
        try:
            os.chmod(file_path, 0o600)
        except OSError:
            pass
    except OSError:
        _delete_held_message(held_path)


def validate_msg_id(msg_id: str) -> bool:
    return isinstance(msg_id, str) and bool(_UUID_RE.match(msg_id))


def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    else:
        try:
            os.chmod(DATA_DIR, 0o700)
        except OSError:
            pass


def save_message(
    ciphertext: str, expires_in_seconds: int, password_hash: Optional[str] = None
) -> str:
    ensure_data_dir()
    msg_id = str(uuid.uuid4())
    now = int(time.time())

    data = {
        "id": msg_id,
        "ciphertext": ciphertext,
        "created_at": now,
        "expires_at": now + expires_in_seconds,
        "has_password": password_hash is not None,
        "password_hash": password_hash,
    }

    file_path = os.path.join(DATA_DIR, f"{msg_id}.json")
    with open(file_path, "w") as f:
        json.dump(data, f)

    try:
        os.chmod(file_path, 0o600)
    except OSError:
        pass

    return msg_id


def _resolve_path(msg_id: str) -> Optional[str]:
    if not validate_msg_id(msg_id):
        return None
    path = os.path.join(DATA_DIR, f"{msg_id}.json")
    real_dir = os.path.realpath(os.path.dirname(path))
    if os.path.realpath(DATA_DIR) != real_dir:
        return None
    return path


def get_message_metadata(msg_id: str) -> Optional[Dict[str, Any]]:
    """Returns message metadata without ciphertext if valid, None if expired/missing."""
    ensure_data_dir()
    file_path = _resolve_path(msg_id)
    if file_path is None:
        return None

    if not os.path.exists(file_path):
        return None

    with open(file_path, "r") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return None

    # Check expiration
    if int(time.time()) > data.get("expires_at", 0):
        try:
            os.remove(file_path)
        except OSError:
            pass
        return None

    # Return safe metadata
    return {
        "id": data["id"],
        "has_password": data["has_password"],
        "expires_at": data["expires_at"],
        "created_at": data["created_at"],
    }


def pop_message(msg_id: str) -> Optional[Dict[str, Any]]:
    """Reads the message and deletes it permanently. Returns the full data including ciphertext."""
    ensure_data_dir()
    file_path = _resolve_path(msg_id)
    if file_path is None:
        return None

    held_path, data = _take_message(file_path)
    if held_path is None:
        return None

    if not data:
        return None

    # Still check expiration before returning
    if int(time.time()) > data.get("expires_at", 0):
        _delete_held_message(held_path)
        return None

    _delete_held_message(held_path)

    return data


def verify_and_pop(
    msg_id: str, password_verify_fn=None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Atomically read, verify password, and pop a message.
    password_verify_fn: callable(password_hash, provided_password) -> bool
    Returns (data, error) tuple. error is None on success.
    On wrong password the file is NOT deleted.
    """
    ensure_data_dir()
    file_path = _resolve_path(msg_id)
    if file_path is None:
        return None, "invalid_id"

    held_path, data = _take_message(file_path)
    if held_path is None:
        return None, "not_found"

    if data is None:
        return None, "not_found"

    if int(time.time()) > data.get("expires_at", 0):
        _delete_held_message(held_path)
        return None, "expired"

    if data.get("has_password"):
        if password_verify_fn is None:
            _restore_held_message(held_path, file_path)
            return None, "password_required"
        verified = password_verify_fn(data.get("password_hash"))
        if not verified:
            _restore_held_message(held_path, file_path)
            return None, "wrong_password"

    _delete_held_message(held_path)

    return data, None


def cleanup_expired():
    """Iterate and remove expired files. Can be run periodically."""
    ensure_data_dir()
    now = int(time.time())
    global _last_cleanup_cursor
    files = [name for name in os.listdir(DATA_DIR) if name.endswith(".json")]
    if not files:
        return

    batch_size = 200
    start = _last_cleanup_cursor % len(files)
    ordered = files[start:] + files[:start]

    for filename in ordered[:batch_size]:
        if not filename.endswith(".json"):
            continue

        file_path = os.path.join(DATA_DIR, filename)
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
            if now > data.get("expires_at", 0):
                os.remove(file_path)
        except Exception:
            # If it's corrupted, just delete it
            try:
                os.remove(file_path)
            except OSError:
                pass

    _last_cleanup_cursor = start + batch_size


def maybe_cleanup_expired() -> None:
    global _last_cleanup_at
    now = int(time.time())
    if now - _last_cleanup_at < CLEANUP_INTERVAL_SECONDS:
        return

    cleanup_expired()
    _last_cleanup_at = now
