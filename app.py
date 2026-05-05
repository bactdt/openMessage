import logging
import os
import platform
import sys
import uuid

from flask import Flask, g, has_request_context, request, jsonify, render_template
from flask_limiter import Limiter
from flask_limiter.errors import RateLimitExceeded
from flask_limiter.util import get_remote_address
from crypto_utils import (
    generate_key,
    encrypt_message,
    decrypt_message,
    hash_password,
    verify_password,
)
from config import load_config
import storage

if getattr(sys, "frozen", False):
    BASE_PATH = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_PATH, "templates"),
    static_folder=os.path.join(BASE_PATH, "static"),
)

APP_CONFIG = load_config()
RATE_LIMIT_STORAGE_URI = APP_CONFIG.RATE_LIMIT_STORAGE_URI

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri=RATE_LIMIT_STORAGE_URI,
)


def _message_attempt_key() -> str:
    view_args = request.view_args or {}
    msg_id = view_args.get("msg_id", "")
    return f"{get_remote_address()}:{msg_id}"


app.config["SECRET_KEY"] = APP_CONFIG.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = APP_CONFIG.MAX_CONTENT_LENGTH

ALLOWED_EXPIRES = APP_CONFIG.ALLOWED_EXPIRES
V2_E2E_ENABLED = APP_CONFIG.V2_E2E_ENABLED

_MESSAGE_READ_ERROR_RESPONSES = {
    storage.ERROR_INVALID_ID: (404, {"error": "Secret not found or already read"}),
    storage.ERROR_NOT_FOUND: (404, {"error": "Secret not found or already read"}),
    storage.ERROR_EXPIRED: (404, {"error": "Secret not found or already read"}),
    storage.ERROR_UNSUPPORTED_VERSION: (
        404,
        {"error": "Secret not found or already read"},
    ),
    storage.ERROR_PASSWORD_REQUIRED: (
        401,
        {"error": "Password required", "needs_password": True},
    ),
    storage.ERROR_WRONG_PASSWORD: (401, {"error": "Incorrect password"}),
    storage.ERROR_LOCKED: (
        409,
        {"error": "Secret is temporarily locked", "retryable": True},
    ),
}


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(g, "request_id", "-") if has_request_context() else "-"
        return True


def _message_read_error_response(error):
    status, body = _MESSAGE_READ_ERROR_RESPONSES.get(
        error,
        (404, {"error": "Secret not found or already read"}),
    )
    return jsonify(body), status


def _template_flags():
    return {"v2_e2e_enabled": V2_E2E_ENABLED}


def _validate_expires(data):
    expires_in = data.get("expires_in", 3600 * 24)
    if expires_in not in ALLOWED_EXPIRES:
        return None, (jsonify({"error": "Invalid expiration time"}), 400)
    return expires_in, None


def _validate_password(data):
    password = data.get("password")
    if password is not None and (not isinstance(password, str) or len(password) > 1024):
        return None, (jsonify({"error": "Invalid password format"}), 400)
    return password, None


_PASSWORD_MISSING = object()


def _build_password_verify_fn(password, msg_id):
    msg_meta = storage.get_message_metadata(msg_id)
    if not msg_meta or not msg_meta.get("has_password"):
        return None
    if not password:
        return _PASSWORD_MISSING
    return lambda pw_hash: verify_password(password, pw_hash)


def _init_logging() -> None:
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    request_id_filter = RequestIDFilter()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        handler.addFilter(request_id_filter)
        root.addHandler(handler)
    else:
        for h in root.handlers:
            if h.formatter is None:
                h.setFormatter(formatter)
            h.addFilter(request_id_filter)


_init_logging()
logger = logging.getLogger(__name__)


@app.before_request
def set_request_id():
    g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "base-uri 'none'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )

    if request.path.startswith("/api/") or request.path.startswith("/v/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response


@app.errorhandler(RateLimitExceeded)
def handle_rate_limit(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Too many requests. Please try again later."}), 429
    return render_template(
        "view.html",
        error="Too many requests. Please wait and try again.",
        flags=_template_flags(),
    ), 429


@app.route("/")
def index():
    return render_template("index.html", flags=_template_flags())


@app.route("/api/message", methods=["POST"])
@limiter.limit("20 per minute")
def create_message():
    data = request.get_json(silent=True)
    if not data or "content" not in data:
        return jsonify({"error": "Missing content"}), 400

    content = data["content"]
    if not isinstance(content, str):
        return jsonify({"error": "Invalid content format"}), 400
    if len(content) > 100000:
        return jsonify({"error": "Message too long. Maximum 100,000 characters."}), 400

    password, password_error = _validate_password(data)
    if password_error is not None:
        return password_error

    expires_in, expires_error = _validate_expires(data)
    if expires_error is not None:
        return expires_error

    key = generate_key()

    try:
        ciphertext = encrypt_message(content, key)
    except Exception:
        logger.exception("Message encryption failed")
        return jsonify({"error": "Encryption failed"}), 500

    pwhash = None
    if password:
        pwhash = hash_password(password)

    msg_id = storage.save_message(ciphertext, expires_in, password_hash=pwhash)

    storage.maybe_cleanup_expired()

    return jsonify({"id": msg_id, "key": key})


@app.route("/api/v2/message", methods=["POST"])
@limiter.limit("20 per minute")
def create_v2_message():
    if not V2_E2E_ENABLED:
        return jsonify({"error": "v2 E2E messages are disabled"}), 404

    data = request.get_json(silent=True)
    if not data or "payload" not in data:
        return jsonify({"error": "Missing payload"}), 400

    valid_payload, payload_error = storage.validate_v2_payload(data["payload"])
    if not valid_payload:
        return jsonify({"error": payload_error or "Invalid payload"}), 400

    password, password_error = _validate_password(data)
    if password_error is not None:
        return password_error

    expires_in, expires_error = _validate_expires(data)
    if expires_error is not None:
        return expires_error

    pwhash = hash_password(password) if password else None
    msg_id = storage.save_v2_message(data["payload"], expires_in, password_hash=pwhash)

    storage.maybe_cleanup_expired()

    return jsonify({"id": msg_id, "version": "v2"})


@app.route("/v/<msg_id>")
@limiter.limit("120 per minute")
@limiter.limit("20 per minute", key_func=_message_attempt_key)
def view_confirm(msg_id):
    if not storage.validate_msg_id(msg_id):
        return render_template(
            "view.html",
            error="Message not found or already deleted.",
            flags=_template_flags(),
        ), 404

    msg_meta = storage.get_message_metadata(msg_id)
    if not msg_meta:
        return render_template(
            "view.html",
            error="Message not found or already deleted.",
            flags=_template_flags(),
        ), 404

    return render_template("view_confirm.html", msg=msg_meta, flags=_template_flags())


@app.route("/api/v2/message/<msg_id>", methods=["POST"])
@limiter.limit("120 per minute")
@limiter.limit("8 per minute", key_func=_message_attempt_key)
def view_v2_message_api(msg_id):
    if not V2_E2E_ENABLED:
        return jsonify({"error": "v2 E2E messages are disabled"}), 404

    data = request.get_json(silent=True) or {}
    password = data.get("password")

    if password is not None and (not isinstance(password, str) or len(password) > 1024):
        return jsonify({"error": "Invalid password format"}), 400

    verify_fn = _build_password_verify_fn(password, msg_id)
    if verify_fn is _PASSWORD_MISSING:
        return jsonify({"error": "Password required", "needs_password": True}), 401

    msg_data, error, held_path = storage.verify_and_hold(msg_id, verify_fn)
    if error or msg_data is None:
        return _message_read_error_response(error)

    if not storage.is_v2_data(msg_data):
        if held_path is not None:
            storage.finish_held_message(held_path)
        return jsonify({"error": "Secret is not a v2 payload"}), 400

    try:
        payload = storage.decode_v2_payload(storage.get_v2_payload(msg_data))
    except Exception:
        logger.exception("v2 payload decode failed")
        if held_path is not None:
            storage.finish_held_message(held_path)
        return jsonify({"error": "Secret is not a v2 payload"}), 400

    if payload is None:
        if held_path is not None:
            storage.finish_held_message(held_path)
        return jsonify({"error": "Secret is not a v2 payload"}), 400

    if held_path is not None:
        storage.finish_held_message(held_path)

    return jsonify({"version": "v2", "payload": payload})


@app.route("/api/message/<msg_id>", methods=["POST"])
@limiter.limit("120 per minute")
@limiter.limit("8 per minute", key_func=_message_attempt_key)
def view_message_api(msg_id):
    data = request.get_json(silent=True) or {}
    key = data.get("key")
    password = data.get("password")

    if not key:
        return jsonify({"error": "Decryption key missing"}), 400

    if not isinstance(key, str) or len(key) > 256:
        return jsonify({"error": "Invalid decryption key format"}), 400

    if password is not None and (not isinstance(password, str) or len(password) > 1024):
        return jsonify({"error": "Invalid password format"}), 400

    verify_fn = _build_password_verify_fn(password, msg_id)
    if verify_fn is _PASSWORD_MISSING:
        return jsonify({"error": "Password required", "needs_password": True}), 401

    msg_data, error, held_path = storage.verify_and_hold(msg_id, verify_fn)
    if error or msg_data is None:
        return _message_read_error_response(error)

    if storage.is_v2_data(msg_data):
        if held_path is not None:
            storage.finish_held_message(held_path)
        return jsonify({"error": "Use /api/v2/message/ for this secret"}), 400

    try:
        plaintext = decrypt_message(msg_data["ciphertext"], key)
    except Exception:
        logger.exception("Message decryption failed")
        if held_path is not None:
            storage.restore_held_message(msg_id, held_path)
        return jsonify({"error": "Decryption failed (invalid key)"}), 400

    if held_path is not None:
        storage.finish_held_message(held_path)

    return jsonify({"content": plaintext})


def _run_gunicorn_linux() -> None:
    from gunicorn.app.base import BaseApplication

    class StandaloneApplication(BaseApplication):
        def __init__(self, application, options=None):
            self.options = options or {}
            self.application = application
            super().__init__()

        def load_config(self):
            config = {
                key: value
                for key, value in self.options.items()
                if key in self.cfg.settings and value is not None
            }
            for key, value in config.items():
                self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    StandaloneApplication(
        app,
        {"bind": APP_CONFIG.BIND, "workers": APP_CONFIG.WORKERS},
    ).run()


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        if platform.system() == "Linux":
            try:
                _run_gunicorn_linux()
            except Exception:
                app.run(host=APP_CONFIG.HOST, port=APP_CONFIG.PORT, debug=False)
        else:
            app.run(host=APP_CONFIG.HOST, port=APP_CONFIG.PORT, debug=False)
    else:
        app.run(debug=True, port=5000)
