class SecurityEngine:
    """Small explicit policy for prototype desktop actions."""

    ALLOWED_ACTIONS = frozenset({"open:notepad", "open:calculator"})

    def authorize(self, action: str) -> bool:
        return action.strip().lower() in self.ALLOWED_ACTIONS
