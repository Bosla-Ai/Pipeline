from src.config.settings import YOUTUBE_API_KEYS


class KeyManager:
    def __init__(self):
        self.keys = YOUTUBE_API_KEYS
        self.current_index = 0

    def get_current_key(self):
        if not self.keys:
            raise Exception("No API Keys provided in settings!")
        return self.keys[self.current_index]

    def rotate(self):
        """Switches to the next key. Returns False if we cycled through all keys."""
        next_index = (self.current_index + 1) % len(self.keys)

        # Optional: Prevent infinite loops if all keys are dead
        if next_index == 0:
            print("    ⚠️ All API Keys have been exhausted!")

        self.current_index = next_index
        print(f"    🔄 Switching to API Key #{self.current_index + 1}...")
        return self.keys[self.current_index]


# Singleton instance
key_manager = KeyManager()
