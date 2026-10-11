"""Engine errors that the API turns into HTTP status codes."""


class EngineError(Exception):
    status = 500


class BadRequest(EngineError):
    status = 400


class Unauthorized(EngineError):
    status = 401


class Forbidden(EngineError):
    status = 403


class NotFound(EngineError):
    status = 404


class Conflict(EngineError):
    status = 409
