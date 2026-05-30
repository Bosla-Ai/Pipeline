import os
import json

try:
    from src.config.settings import YOUTUBE_API_KEYS
except ImportError:
    # Use Environment Variable fallback for CI/CD or Docker
    # Expects JSON string: '["key1", "key2"]'
    keys_env = os.environ.get("YOUTUBE_API_KEYS", "[]")
    try:
        YOUTUBE_API_KEYS = json.loads(keys_env)
    except json.JSONDecodeError:
        YOUTUBE_API_KEYS = []

    if not YOUTUBE_API_KEYS:
        print("Warning: No API Keys found in settings.py or Environment Variables.")


import threading
from typing import Optional


class KeyManager:
    def __init__(self):
        self.keys = YOUTUBE_API_KEYS
        self.current_index = 0
        self._lock = threading.Lock()

    def get_current_key(self) -> str:
        with self._lock:
            if not self.keys:
                raise Exception("No API Keys provided in settings!")
            return self.keys[self.current_index]

    def get_current_key_and_index(self) -> tuple[str, int]:
        with self._lock:
            if not self.keys:
                raise Exception("No API Keys provided in settings!")
            return self.keys[self.current_index], self.current_index

    def rotate(self, failed_key: Optional[str] = None) -> str:
        """Switches to the next key. Returns the new key. Only rotates if failed_key matches the current key."""
        with self._lock:
            if not self.keys:
                raise Exception("Cannot rotate: No API Keys available.")

            # If a failed key is provided, check if another task already rotated past it
            if failed_key is not None and failed_key != self.keys[self.current_index]:
                print(
                    f"    [KeyManager] Key already rotated by another task. Using current key #{self.current_index + 1}."
                )
                return self.keys[self.current_index]

            next_index = (self.current_index + 1) % len(self.keys)

            # Optional: Prevent infinite loops if all keys are dead
            if next_index == 0:
                print("    [KeyManager] All API Keys have been exhausted!")

            self.current_index = next_index
            print(f"    [KeyManager] Switching to API Key #{self.current_index + 1}...")
            return self.keys[self.current_index]


# Singleton instance
key_manager = KeyManager()
