import os
import platform
import sys

from flask import Flask, request, jsonify, render_template, abort
from crypto_utils import (
    generate_key,
    encrypt_message,
    decrypt_message,
    hash_password,
    verify_password,
)
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
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", os.urandom(24).hex())
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

ALLOWED_EXPIRES = {3600, 86400, 604800}


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/message", methods=["POST"])
def create_message():
    data = request.json
    if not data or "content" not in data:
        return jsonify({"error": "Missing content"}), 400

    content = data["content"]
    if len(content) > 100000:
        return jsonify({"error": "Message too long. Maximum 100,000 characters."}), 400

    password = data.get("password")
    expires_in = data.get("expires_in", 3600 * 24)
    if expires_in not in ALLOWED_EXPIRES:
        return jsonify({"error": "Invalid expiration time"}), 400

    key = generate_key()

    try:
        ciphertext = encrypt_message(content, key)
    except Exception:
        return jsonify({"error": "Encryption failed"}), 500

    pwhash = None
    if password:
        pwhash = hash_password(password)

    msg_id = storage.save_message(ciphertext, expires_in, password_hash=pwhash)

    storage.cleanup_expired()

    return jsonify({"id": msg_id, "key": key})


@app.route("/v/<msg_id>")
def view_confirm(msg_id):
    if not storage.validate_msg_id(msg_id):
        return render_template(
            "view.html", error="Message not found or already deleted."
        ), 404

    msg_meta = storage.get_message_metadata(msg_id)
    if not msg_meta:
        return render_template(
            "view.html", error="Message not found or already deleted."
        ), 404

    return render_template("view_confirm.html", msg=msg_meta)


@app.route("/api/message/<msg_id>", methods=["POST"])
def view_message_api(msg_id):
    data = request.json or {}
    key = data.get("key")
    password = data.get("password")

    if not key:
        return jsonify({"error": "Decryption key missing"}), 400

    if not storage.validate_msg_id(msg_id):
        return jsonify({"error": "Secret not found or already read"}), 404

    verify_fn = None
    msg_meta = storage.get_message_metadata(msg_id)
    if msg_meta and msg_meta.get("has_password"):
        if not password:
            return jsonify({"error": "Password required", "needs_password": True}), 401
        verify_fn = lambda pw_hash: verify_password(password, pw_hash)

    msg_data, error = storage.verify_and_pop(msg_id, verify_fn)
    if error == "invalid_id" or error == "not_found" or error == "expired":
        return jsonify({"error": "Secret not found or already read"}), 404
    if error == "password_required":
        return jsonify({"error": "Password required", "needs_password": True}), 401
    if error == "wrong_password":
        return jsonify({"error": "Incorrect password"}), 401
    if error or msg_data is None:
        return jsonify({"error": "Secret not found or already read"}), 404

    try:
        plaintext = decrypt_message(msg_data["ciphertext"], key)
    except Exception:
        return jsonify({"error": "Decryption failed (invalid key)"}), 400

    return jsonify({"content": plaintext})


def _run_gunicorn_linux() -> None:
    from gunicorn.app.base import BaseApplication

    workers_raw = os.environ.get("WORKERS", "4")
    try:
        workers = int(workers_raw)
    except ValueError:
        workers = 4
    workers = max(workers, 1)

    host = os.environ.get("HOST", "0.0.0.0")
    port = os.environ.get("PORT", "5000")
    bind = os.environ.get("BIND", f"{host}:{port}")

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

    StandaloneApplication(app, {"bind": bind, "workers": workers}).run()


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        host = os.environ.get("HOST", "0.0.0.0")
        port_raw = os.environ.get("PORT", "5000")
        try:
            port = int(port_raw)
        except ValueError:
            port = 5000

        if platform.system() == "Linux":
            try:
                _run_gunicorn_linux()
            except Exception:
                app.run(host=host, port=port, debug=False)
        else:
            app.run(host=host, port=port, debug=False)
    else:
        app.run(debug=True, port=5000)
