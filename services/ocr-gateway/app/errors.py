class GatewayError(Exception):
    """An expected, normalized gateway error safe to expose to the caller."""

    def __init__(self, code: str, message: str, status_code: int, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


class ProviderError(GatewayError):
    pass
