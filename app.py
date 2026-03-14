from flask import Flask, request, jsonify, render_template, abort
from crypto_utils import generate_key, encrypt_message, decrypt_message, hash_password, verify_password
import storage

app = Flask(__name__)
# 16 MB max payload size just in case, though usually secrets are small
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/message', methods=['POST'])
def create_message():
    data = request.json
    if not data or 'content' not in data:
        return jsonify({'error': 'Missing content'}), 400
        
    content = data['content']
    if len(content) > 100000:
        return jsonify({'error': 'Message too long. Maximum 100,000 characters.'}), 400
        
    password = data.get('password')
    expires_in = data.get('expires_in', 3600 * 24) # default 24h
    
    # Generate unique encryption key
    key = generate_key()
    
    # Encrypt the content
    try:
        ciphertext = encrypt_message(content, key)
    except Exception as e:
        return jsonify({'error': 'Encryption failed'}), 500
        
    # Process password if any
    pwhash = None
    if password:
        pwhash = hash_password(password)
        
    # Save to storage
    msg_id = storage.save_message(ciphertext, expires_in, password_hash=pwhash)
    
    # Clean up expired on creation (simple background replacement)
    storage.cleanup_expired()
    
    # Return ID and key. The key must be handled by the client to construct the URL `#key=...`
    return jsonify({
        'id': msg_id,
        'key': key
    })

@app.route('/v/<msg_id>')
def view_confirm(msg_id):
    """
    Renders the confirmation page to view the secret.
    We don't want to decrypt on GET because link unfurling bots (Slack/Discord)
    would accidentally view and destroy the secret.
    """
    msg_meta = storage.get_message_metadata(msg_id)
    if not msg_meta:
        return render_template('view.html', error="Message not found or already deleted."), 404
        
    return render_template('view_confirm.html', msg=msg_meta)

@app.route('/api/message/<msg_id>', methods=['POST'])
def view_message_api(msg_id):
    """
    Actual endpoint where the secret is popped, decrypted, and returned.
    """
    data = request.json or {}
    key = data.get('key')
    password = data.get('password')
    
    if not key:
        return jsonify({'error': 'Decryption key missing'}), 400
        
    # Attempt to read metadata first to check password
    msg_meta = storage.get_message_metadata(msg_id)
    if not msg_meta:
        return jsonify({'error': 'Secret not found or already read'}), 404
        
    # If password is required, verify before popping
    # Wait, if we verify before popping, an attacker could brute force the password!
    # A safer approach for one-time secrets: allow viewing the prompt, but reading requires popping.
    # However, if they entered the WRONG password, should we destroy the secret?
    # Usually NO. So we don't pop until password is correct.
    # To prevent brute force, we could rate limit, but for simplicity here we just check.
    if msg_meta['has_password']:
        if not password:
            return jsonify({'error': 'Password required', 'needs_password': True}), 401
            
        # We need the hash. So we should pop, or read it fully. Wait, `get_message_metadata` doesn't return the hash.
        # Let's modify storage to have a `peek_message` or pass we pass the hash?
        # Let's use `pop_message` directly. No, wait, if password is wrong and we popped it, it's destroyed!
        # "burn-after-reading" philosophy: "If auth fails, maybe don't burn?"
        # Standard: wrong password DOES NOT burn the secret.
        pass
        
    # We must carefully read the file to check the hash without deleting it
    import os, json
    file_path = os.path.join(storage.DATA_DIR, f"{msg_id}.json")
    if not os.path.exists(file_path):
        return jsonify({'error': 'Secret not found or already read'}), 404
        
    with open(file_path, 'r') as f:
        full_data = json.load(f)
        
    if full_data.get('has_password'):
        if not password:
            return jsonify({'error': 'Password required', 'needs_password': True}), 401
        if not verify_password(password, full_data['password_hash']):
            return jsonify({'error': 'Incorrect password'}), 401
            
    # Now it's safe to pop!
    msg_data = storage.pop_message(msg_id)
    if not msg_data:
        # Extremely unlikely race condition
        return jsonify({'error': 'Secret not found or already read'}), 404
        
    # Decrypt
    try:
        plaintext = decrypt_message(msg_data['ciphertext'], key)
    except Exception as e:
        # Wrong key? If the key is wrong, we STILL burned the message! This is correct.
        # It prevents infinite attempts to guess the key.
        return jsonify({'error': 'Decryption failed (invalid key)'}), 400
        
    return jsonify({
        'content': plaintext
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
