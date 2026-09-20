"""Stable process exit codes and machine-readable failures."""


class ClientError(Exception):
    def __init__(self, message, *, code="invalid_input", exit_code=2, status=None, details=None):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.status = status
        self.details = details

    def payload(self):
        result = {"code": self.code, "message": str(self), "status": self.status}
        if self.details is not None:
            result["details"] = self.details
        return result
