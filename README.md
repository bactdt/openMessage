# OpenMessage

OpenMessage is a secure, view-once, self-destructing message application built with Python and Flask. Its core philosophy is "Burn After Reading" — messages are destroyed from the server immediately upon being read, leaving no trace behind. No database required; messages are stored as encrypted local JSON files.

## Features

- **End-to-End Encryption**: AES-128-CBC + HMAC-SHA256 (Fernet). The encryption key is returned to the client and never stored alongside the ciphertext.
- **View-Once Guarantee**: The moment a message is viewed, it is permanently deleted from the server.
- **No Database Needed**: Simplified architecture using local JSON file storage.
- **Optional Password Protection**: Add a secondary layer of security to your messages.
- **Expiration Logic**: Messages automatically self-destruct if not viewed within the configured time (1 hour, 24 hours, or 7 days).
- **Rich Text Support**: Full rendering of Markdown and LaTeX (via KaTeX).
- **Dark Mode**: Notion-inspired glassmorphism design with automatic system theme detection and manual toggle.
- **Safe Previews**: Link preview crawlers (Slack, Discord, iMessage) will not accidentally burn the message. Viewing requires an explicit user action.
- **Interactive Envelope**: CSS-animated paper envelope with a red wax seal to "open" your secret.
- **Security Hardened**: UUID path validation, CSP headers, no-store cache policy, `X-Content-Type-Options`, `X-Frame-Options`, `expires_in` whitelist, rate limiting, atomic one-time read.
- **Accessible**: Keyboard-navigable envelope (Tab + Enter), password Enter-to-submit, secure context clipboard fallback.

## Screenshots

| Light Mode | Dark Mode |
| --- | --- |
| <img src="assets/homepage.png" width="400"> | <img src="assets/homepage-dark.png" width="400"> |

*Create a secret message*

| Light Mode | Dark Mode |
| --- | --- |
| <img src="assets/success.png" width="400"> | <img src="assets/success-dark.png" width="400"> |

*Share the one-time link*

## Tech Stack

- **Backend**: Python 3, Flask, Werkzeug
- **Cryptography**: `cryptography` library (Fernet — AES-128-CBC + HMAC-SHA256)
- **Frontend**: HTML5, Vanilla CSS3 (Glassmorphism Design System), Vanilla JavaScript
- **Markdown & Math**: Marked.js, KaTeX, DOMPurify

## Getting Started

### Prerequisites

Ensure you have Python 3.7+ installed.

### Installation & Running

1. Clone this repository:
   ```bash
   git clone <your-repo-url>
   cd openMessage
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   # Development mode
   python app.py

   # Production mode (using gunicorn)
   gunicorn --bind 127.0.0.1:5000 app:app
   ```

4. Access the app in your browser at `http://localhost:5000`.

### Environment Variables

| Variable | Description | Default |
| --- | --- | --- |
| `SECRET_KEY` | Flask secret key for sessions | Auto-generated random value |
| `RATE_LIMIT_STORAGE_URI` | Flask-Limiter storage backend (set Redis in production) | `memory://` |

## How It Works

1. **Creation**: User inputs a message. The server creates a random AES encryption key. This key is used to encrypt the message, and then returned to the client without being stored.
2. **Storage**: The application stores only the ciphertext, an expiry timestamp, and an optional password hash in `data/<uuid>.json`.
3. **Sharing**: A unique URL is generated containing the ID and the decryption key in the URL hash fragment (`http://site.com/v/<id>#<key>`).
4. **Viewing**: The recipient opens the URL. An animated envelope confirmation page appears. Upon opening the envelope, the browser sends the key to the server. The server reads the file, **immediately deletes it** from the filesystem, decrypts the content, and returns the plain text to be rendered on the frontend.

## Security

- **Path traversal protection**: All message IDs are validated as UUID v4; `realpath` check prevents directory traversal.
- **Atomic verification**: Password check and message deletion happen in a single operation — wrong password does not destroy the message.
- **CSP headers**: Content-Security-Policy restricts script/style/font sources.
- **Rate limiting**: Message creation and view endpoints are throttled (global + per-message) to reduce abuse and brute force attempts.
- **No key storage**: The decryption key never touches the server disk; it lives only in the URL hash fragment (never sent to the server in a GET request).
- **Expiration enforcement**: Expired messages are cleaned up automatically on creation and rejected on access.

## License

This project is licensed under the [MIT License](LICENSE).
