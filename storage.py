import logging
import os
import json
import re
import uuid
import time
import sys
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

if getattr(sys, "frozen", False):
    DATA_DIR = os.path.join(os.path.dirname(sys.executable), "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

CLEANUP_INTERVAL_SECONDS = 300
LOCK_DETECTION_WINDOW_SECONDS = 0.05
LOCK_DETECTION_POLL_INTERVAL_SECONDS = 0.005
_cleanup_state = {"last_cleanup_at": 0, "last_cleanup_cursor": 0}


def reset_runtime_state() -> None:
    """Reset in-process storage runtime state for tests and one-off benchmarks."""
    _cleanup_state["last_cleanup_at"] = 0
    _cleanup_state["last_cleanup_cursor"] = 0


def _take_message(file_path: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Move a message file to a held path and load JSON data.

    Returns:
    - (None, None): source file was missing or could not be moved.
    - (held_path, data): source file was held and parsed successfully.

    Corrupted or unreadable held files are deleted before returning (None, None).
    """
    held_path = f"{file_path}.lock-{uuid.uuid4().hex}"
    try:
        os.replace(file_path, held_path)
    except FileNotFoundError:
        return None, None
    except OSError:
        logger.warning("storage.take.failed path=%s", file_path)
        return None, None

    try:
        with open(held_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("storage.held.corrupt_deleted path=%s", held_path)
        _delete_held_message(held_path)
        return None, None

    return held_path, data


def _delete_held_message(held_path: str) -> None:
    try:
        os.remove(held_path)
    except OSError:
        logger.warning("storage.held.delete_failed path=%s", held_path)


def _restore_held_message(held_path: str, file_path: str) -> None:
    try:
        os.replace(held_path, file_path)
        try:
            os.chmod(file_path, 0o600)
        except OSError:
            logger.warning("storage.restore.chmod_failed path=%s", file_path)
    except OSError:
        logger.error("storage.restore.failed held_path=%s path=%s", held_path, file_path)
        _delete_held_message(held_path)


def _has_held_message_lock(file_path: str) -> bool:
    lock_prefix = f"{os.path.basename(file_path)}.lock-"
    try:
        return any(
            name.startswith(lock_prefix)
            for name in os.listdir(os.path.dirname(file_path))
        )
    except OSError:
        logger.warning("storage.lock.inspect_failed path=%s", file_path)
        return False


def _detect_transient_lock(file_path: str) -> bool:
    deadline = time.monotonic() + LOCK_DETECTION_WINDOW_SECONDS
    while True:
        if _has_held_message_lock(file_path) or os.path.exists(file_path):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(LOCK_DETECTION_POLL_INTERVAL_SECONDS)


PROTOCOL_VERSION = "v1"
SUPPORTED_VERSIONS = {"v1"}

ERROR_INVALID_ID = "invalid_id"
ERROR_NOT_FOUND = "not_found"
ERROR_UNSUPPORTED_VERSION = "unsupported_version"
ERROR_EXPIRED = "expired"
ERROR_PASSWORD_REQUIRED = "password_required"
ERROR_WRONG_PASSWORD = "wrong_password"
ERROR_LOCKED = "locked"

RETRYABLE_ERRORS = {ERROR_LOCKED}


def is_retryable_error(error: Optional[str]) -> bool:
    return error in RETRYABLE_ERRORS


def _ensure_version(data: dict) -> dict:
    if "version" not in data:
        data["version"] = PROTOCOL_VERSION
    return data


def _validate_version(data: dict) -> bool:
    return data.get("version") in SUPPORTED_VERSIONS


def validate_msg_id(msg_id: str) -> bool:
    return isinstance(msg_id, str) and bool(_UUID_RE.match(msg_id))


def ensure_data_dir():
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        logger.warning("storage.data_dir.chmod_failed path=%s", DATA_DIR)


def save_message(
    ciphertext: str, expires_in_seconds: int, password_hash: Optional[str] = None
) -> str:
    ensure_data_dir()
    msg_id = str(uuid.uuid4())
    now = int(time.time())

    data = {
        "version": PROTOCOL_VERSION,
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
        logger.warning("storage.message.chmod_failed path=%s", file_path)

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
    """
    Return non-sensitive message metadata without ciphertext.

    This is a best-effort, non-destructive read used by the confirmation page.
    The destructive API read path uses verify_and_hold() for stronger handoff semantics.
    """
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

    data = _ensure_version(data)

    if not _validate_version(data):
        return None

    # Check expiration
    if int(time.time()) > data.get("expires_at", 0):
        try:
            os.remove(file_path)
        except OSError:
            logger.warning("storage.metadata.expired_delete_failed path=%s", file_path)
        return None

    # Return safe metadata
    return {
        "id": data["id"],
        "has_password": data["has_password"],
        "expires_at": data["expires_at"],
        "created_at": data["created_at"],
    }


def verify_and_hold(
    msg_id: str, password_verify_fn=None
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """
    Atomically read and verify a message while holding its file.
    password_verify_fn: callable(password_hash) -> bool
    The caller must either delete or restore the returned held_path.
    """
    ensure_data_dir()
    file_path = _resolve_path(msg_id)
    if file_path is None:
        return None, ERROR_INVALID_ID, None

    held_path, data = _take_message(file_path)
    if held_path is None:
        if _detect_transient_lock(file_path):
            return None, ERROR_LOCKED, None
        return None, ERROR_NOT_FOUND, None

    if data is None:
        return None, ERROR_NOT_FOUND, None

    data = _ensure_version(data)

    if not _validate_version(data):
        _delete_held_message(held_path)
        return None, ERROR_UNSUPPORTED_VERSION, None

    if int(time.time()) > data.get("expires_at", 0):
        _delete_held_message(held_path)
        return None, ERROR_EXPIRED, None

    if data.get("has_password"):
        if password_verify_fn is None:
            _restore_held_message(held_path, file_path)
            return None, ERROR_PASSWORD_REQUIRED, None
        verified = password_verify_fn(data.get("password_hash"))
        if not verified:
            _restore_held_message(held_path, file_path)
            return None, ERROR_WRONG_PASSWORD, None

    return data, None, held_path


def finish_held_message(held_path: str) -> None:
    _delete_held_message(held_path)


def restore_held_message(msg_id: str, held_path: str) -> None:
    file_path = _resolve_path(msg_id)
    if file_path is None:
        _delete_held_message(held_path)
        return
    _restore_held_message(held_path, file_path)


def cleanup_expired():
    """Iterate and remove expired files. Can be run periodically."""
    ensure_data_dir()
    now = int(time.time())
    files = [name for name in os.listdir(DATA_DIR) if name.endswith(".json")]
    if not files:
        return

    scanned = 0
    deleted = 0
    failed = 0

    batch_size = 200
    start = _cleanup_state["last_cleanup_cursor"] % len(files)
    ordered = files[start:] + files[:start]

    for filename in ordered[:batch_size]:
        if not filename.endswith(".json"):
            continue

        scanned += 1
        file_path = os.path.join(DATA_DIR, filename)
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
            if now > data.get("expires_at", 0):
                os.remove(file_path)
                deleted += 1
        except Exception:
            # If it's corrupted, just delete it
            try:
                os.remove(file_path)
                deleted += 1
            except OSError:
                logger.warning("storage.cleanup.delete_failed path=%s", file_path)
                failed += 1

    _cleanup_state["last_cleanup_cursor"] = start + batch_size

    logger.info(
        "storage.cleanup.completed scanned=%d deleted=%d failed=%d",
        scanned, deleted, failed,
    )


def maybe_cleanup_expired() -> None:
    now = int(time.time())
    if now - _cleanup_state["last_cleanup_at"] < CLEANUP_INTERVAL_SECONDS:
        return

    cleanup_expired()
    _cleanup_state["last_cleanup_at"] = now
