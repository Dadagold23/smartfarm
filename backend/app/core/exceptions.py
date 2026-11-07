"""Domain exceptions.

Services raise these; `app.main` registers handlers that render the
spec-mandated consistent error envelope:
    {"error": {"code": "...", "message": "..."}}
"""


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str = "Internal server error") -> None:
        super().__init__(message)
        self.message = message


class AuthenticationError(AppError):
    status_code = 401
    code = "authentication_failed"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class BusinessRuleError(AppError):
    status_code = 400
    code = "business_rule_violation"
