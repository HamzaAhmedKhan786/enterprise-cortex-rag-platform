from typing import Dict, List


class ConversationMemory:
    def __init__(self, max_turns: int = 5):
        self.max_turns = max_turns
        self.messages: List[Dict[str, str]] = []

    def add_user_message(self, message: str):
        self.messages.append(
            {
                "role": "user",
                "content": message,
            }
        )
        self._trim()

    def add_assistant_message(self, message: str):
        self.messages.append(
            {
                "role": "assistant",
                "content": message,
            }
        )
        self._trim()

    def get_history_text(self) -> str:
        if not self.messages:
            return ""

        history_parts = []

        for message in self.messages:
            history_parts.append(
                f"{message['role'].capitalize()}: {message['content']}"
            )

        return "\n".join(history_parts)

    def clear(self):
        self.messages = []

    def _trim(self):
        max_messages = self.max_turns * 2
        if len(self.messages) > max_messages:
            self.messages = self.messages[-max_messages:]