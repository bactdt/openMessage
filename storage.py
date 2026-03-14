import os
import json
import uuid
import time
from typing import Optional, Dict, Any

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def save_message(ciphertext: str, expires_in_seconds: int, password_hash: Optional[str] = None) -> str:
    ensure_data_dir()
    msg_id = str(uuid.uuid4())
    now = int(time.time())
    
    data = {
        "id": msg_id,
        "ciphertext": ciphertext,
        "created_at": now,
        "expires_at": now + expires_in_seconds,
        "has_password": password_hash is not None,
        "password_hash": password_hash
    }
    
    file_path = os.path.join(DATA_DIR, f"{msg_id}.json")
    with open(file_path, 'w') as f:
        json.dump(data, f)
        
    return msg_id

def get_message_metadata(msg_id: str) -> Optional[Dict[str, Any]]:
    """Returns message metadata without ciphertext if valid, None if expired/missing."""
    ensure_data_dir()
    file_path = os.path.join(DATA_DIR, f"{msg_id}.json")
    
    if not os.path.exists(file_path):
        return None
        
    with open(file_path, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return None
            
    # Check expiration
    if int(time.time()) > data.get("expires_at", 0):
        os.remove(file_path) # cleanup
        return None
        
    # Return safe metadata
    return {
        "id": data["id"],
        "has_password": data["has_password"],
        "expires_at": data["expires_at"],
        "created_at": data["created_at"]
    }

def pop_message(msg_id: str) -> Optional[Dict[str, Any]]:
    """Reads the message and deletes it permanently. Returns the full data including ciphertext."""
    ensure_data_dir()
    file_path = os.path.join(DATA_DIR, f"{msg_id}.json")
    
    if not os.path.exists(file_path):
        return None
        
    with open(file_path, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = None
            
    # Always delete when popped, right after reading! One-Time viewing!
    try:
        os.remove(file_path)
    except OSError:
        pass
        
    if not data:
        return None
        
    # Still check expiration before returning
    if int(time.time()) > data.get("expires_at", 0):
        return None
        
    return data

def cleanup_expired():
    """Iterate and remove expired files. Can be run periodically."""
    ensure_data_dir()
    now = int(time.time())
    for filename in os.listdir(DATA_DIR):
        if not filename.endswith('.json'):
            continue
            
        file_path = os.path.join(DATA_DIR, filename)
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            if now > data.get("expires_at", 0):
                os.remove(file_path)
        except Exception:
            # If it's corrupted, just delete it
            try:
                os.remove(file_path)
            except:
                pass
