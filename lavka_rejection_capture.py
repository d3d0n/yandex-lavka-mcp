"""Offline, allowlisted projection of a rejection; no HTTP or order transport.

Never persist or log the response body. Unknown values are deliberately not
returned, even if they look like error codes: they may contain personal data.
This projection cannot establish whether an order was created.
"""

_KNOWN_CODES = frozenset({"grocery_unavailable_for_checkout", "bad_service_fee", "bad_service_fee_v2"})
# Provider errors can wrap the backend response under data.data.response.
# Deliberately do not traverse body: it can contain the submitted private payload.
_CONTAINER_KEYS = ("data", "response", "details", "detail", "error", "cart")
_CODE_KEYS = ("code", "message", "checkout_unavailable_reason")


def sanitize_rejection(status, body):
    """Extract only known public error literals, traversing bounded known fields."""
    if type(status) is not int or not 400 <= status <= 599:
        raise ValueError("Expected an HTTP error status")
    codes = []
    unknown = False
    stack = [(body, 0)]
    count = 0
    while stack and count < 128:
        obj, depth = stack.pop()
        count += 1
        if depth > 8:
            unknown = True
            continue
        if isinstance(obj, list):
            stack.extend((child, depth + 1) for child in obj[:128])
            if len(obj) > 128:
                unknown = True
        elif isinstance(obj, dict):
            for key in _CODE_KEYS:
                value = obj.get(key)
                if isinstance(value, str):
                    if value in _KNOWN_CODES:
                        if value not in codes:
                            codes.append(value)
                    else:
                        unknown = True
            for key in reversed(_CONTAINER_KEYS):
                if key in obj:
                    stack.append((obj[key], depth + 1))
        elif isinstance(obj, str) and depth:
            if obj in _KNOWN_CODES:
                if obj not in codes:
                    codes.append(obj)
            else:
                unknown = True
    if stack:
        unknown = True
    result = {"http_status": status, "codes": codes}
    if unknown or not codes:
        result["unrecognized_code"] = unknown
    return result


# Error fields are selected rather than copying arbitrary response objects.  Free
# text, request bodies, and identifiers are not safe to expose in diagnostics.
_ERROR_FIELDS = frozenset({"error", "errors", "code", "message", "reason",
                           "checkout_unavailable_reason", "details", "detail",
                           "data", "response", "cart", "status", "retryable"})
_STRING_FIELDS = frozenset({"code", "message", "reason", "error",
                            "checkout_unavailable_reason"})


def sanitize_upstream_error(status, body):
    """Project structured upstream error fields without exposing free-form PII.

    Unknown machine-readable values are retained, not mapped to known codes.
    Free text and untrusted fields are suppressed because they may contain PII.
    """
    import re
    if type(status) is not int or not 400 <= status <= 599:
        raise ValueError("Expected an HTTP error status")
    budget = [256]

    def project(value, depth=0, field=None):
        budget[0] -= 1
        if budget[0] < 0 or depth > 8:
            return "[redacted]"
        if isinstance(value, dict):
            return {k: project(v, depth + 1, k) for k, v in value.items()
                    if isinstance(k, str) and k in _ERROR_FIELDS}
        if isinstance(value, list):
            return [project(v, depth + 1, field) for v in value[:128]]
        if isinstance(value, str):
            # Only compact lower-case machine identifiers; never echo arbitrary
            # human messages, URLs, numeric identifiers, secrets or credentials.
            if (field in _STRING_FIELDS and len(value) <= 80
                    and re.fullmatch(r"[a-z][a-z0-9_]*", value)
                    and not re.search(r"token|secret|password|cookie|authorization|card|address|phone|email", value)):
                return value
            return "[redacted]"
        if value is None or type(value) in (bool, int, float):
            return value if field in {"status", "code", "retryable"} else "[redacted]"
        return "[redacted]"

    return {"http_status": status, "error": project(body)}
