"""Domain errors. Services raise these; main.py turns them into JSON responses."""


class DomainError(Exception):
    status_code = 400

    def __init__(self, detail):
        super().__init__(str(detail))
        self.detail = detail


class NotFound(DomainError):
    status_code = 404


class Forbidden(DomainError):
    status_code = 403


class Conflict(DomainError):
    status_code = 409


class Invalid(DomainError):
    status_code = 422
