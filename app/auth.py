import hmac

from fastapi import Header, Request

from app.errors import ServiceError


def authorized(candidate: str, current: str, previous: str) -> bool:
    supplied = candidate.encode("utf-8")
    # Evaluate both comparisons even when the current key matches.
    first = hmac.compare_digest(supplied, current.encode("utf-8"))
    second = hmac.compare_digest(supplied, previous.encode("utf-8"))
    return bool((first & bool(current)) | (second & bool(previous)))


def require_key(request: Request, x_service_key: str = Header(default="")) -> None:
    cfg = request.app.state.settings
    if not authorized(x_service_key, cfg.service_key, cfg.previous_key):
        raise ServiceError(401, "unauthorized")
