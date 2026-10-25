"""Original deterministic implementation for API Detective (plotxyz-api-detective-agent)."""
from __future__ import annotations

import ast
import csv
import io
import json
import math
import os
import re
import statistics
import time
from collections import Counter, defaultdict, deque


class LogicError(ValueError):
    """Raised when supplied input cannot be processed."""


def _text(payload, key, min_len=1, max_len=20000):
    value = payload.get(key)
    if not isinstance(value, str):
        raise LogicError(f"'{key}' must be a string")
    value = value.strip()
    if len(value) < min_len:
        raise LogicError(f"'{key}' is required")
    if len(value) > max_len:
        raise LogicError(f"'{key}' exceeds {max_len} characters")
    return value


def _num(payload, key, default=None, lo=None, hi=None):
    value = payload.get(key, default)
    if value is None or value == "":
        if default is None:
            raise LogicError(f"'{key}' is required")
        return default
    if isinstance(value, bool):
        raise LogicError(f"'{key}' must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise LogicError(f"'{key}' must be numeric")
    if lo is not None and number < lo:
        raise LogicError(f"'{key}' must be at least {lo}")
    if hi is not None and number > hi:
        raise LogicError(f"'{key}' must be at most {hi}")
    return number


def _json(payload, key, expected=None, max_len=200000):
    raw = payload.get(key)
    if isinstance(raw, (dict, list)):
        data = raw
    elif isinstance(raw, str):
        if len(raw) > max_len:
            raise LogicError(f"'{key}' exceeds {max_len} characters")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LogicError(f"'{key}' is not valid JSON: {exc.msg} at line {exc.lineno}")
    else:
        raise LogicError(f"'{key}' must be JSON")
    if expected is not None and not isinstance(data, expected):
        name = expected.__name__ if hasattr(expected, "__name__") else str(expected)
        raise LogicError(f"'{key}' must be a JSON {name}")
    return data


def _csv(payload, key, max_rows=5000):
    text = _text(payload, key, max_len=2000000)
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise LogicError(f"'{key}' must include a header row")
        columns = [str(c).strip() for c in reader.fieldnames if c and str(c).strip()]
        if not columns:
            raise LogicError(f"'{key}' must include named columns")
        rows = []
        for index, raw in enumerate(reader):
            if index >= max_rows:
                raise LogicError(f"'{key}' exceeds {max_rows} rows")
            rows.append({col: (raw.get(col) or "").strip() for col in columns})
    except csv.Error as exc:
        raise LogicError(f"'{key}' is not valid CSV: {exc}")
    if not rows:
        raise LogicError(f"'{key}' must include at least one data row")
    return columns, rows


STOPWORDS = {'will', 'they', 'was', 'your', 'than', 'that', 'on', 'be', 'then', 'do', 'our', 'with', 'he', 'is', 'about', 'had', 'were', 'as', 'may', 'we', 'their', 'are', 'did', 'at', 'she', 'a', 'by', 'the', 'if', 'might', 'it', 'into', 'have', 'from', 'should', 'not', 'over', 'can', 'for', 'and', 'an', 'you', 'does', 'to', 'this', 'could', 'would', 'under', 'of', 'no', 'its', 'in', 'i', 'or', 'has'}


def _tokens(text):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9_+-]{1,}", text.lower()) if w not in STOPWORDS]


def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip(" -•\t") for p in parts if len(p.strip()) > 2]


def provider_status():
    """Report which optional model providers are configured (never exposes secrets)."""
    ollama = bool(os.getenv("OLLAMA_BASE_URL"))
    openai = bool(os.getenv("OPENAI_BASE_URL") and os.getenv("OPENAI_MODEL"))
    return {"ollama_compatible": ollama, "openai_compatible": openai}


def _llm(messages, temperature=0.2):
    """Call an explicitly configured OpenAI-compatible endpoint; return None when unavailable."""
    base = os.getenv("OPENAI_BASE_URL", "").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "")
    if not base or not model:
        ollama = os.getenv("OLLAMA_BASE_URL", "").rstrip("/")
        if not ollama:
            return None
        base = f"{ollama}/v1"
        model = os.getenv("OLLAMA_MODEL", "")
    if not model:
        return None
    try:
        import httpx

        headers = {"Content-Type": "application/json"}
        key = os.getenv("OPENAI_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        with httpx.Client(timeout=20) as client:
            response = client.post(
                f"{base}/chat/completions",
                headers=headers,
                json={"model": model, "messages": messages, "temperature": temperature},
            )
            response.raise_for_status()
            return str(response.json()["choices"][0]["message"]["content"]).strip()
    except Exception:
        return None


def _result(summary, result, warnings=None):
    return {"summary": summary, "result": result, "warnings": warnings or []}


def agent_api_detective(payload):
    method = _text(payload, "method", max_len=12).upper()
    url = _text(payload, "url", max_len=2000)
    status = int(_num(payload, "status", lo=100, hi=599))
    body = str(payload.get("response_body", "")).strip()
    lowered = body.lower()
    findings, suggestions = [], []
    if 200 <= status < 300:
        summary = f"{method} {url} returned {status}; the request succeeded."
        severity = "info"
    elif status == 401:
        summary = "Authentication is missing, expired, or malformed."
        findings.append({"title": "401 Unauthorized", "severity": "high", "detail": "The server did not accept the supplied credentials."})
        suggestions += ["Confirm the Authorization header is present and uses the expected scheme.", "Check token expiry and audience."]
    elif status == 403:
        summary = "The caller is authenticated but not authorized for this resource."
        findings.append({"title": "403 Forbidden", "severity": "high", "detail": "Check scopes, roles, and resource ownership."})
        suggestions += ["Verify scopes/roles.", "Confirm the resource belongs to the caller."]
    elif status == 404:
        summary = "The route or resource was not found."
        findings.append({"title": "404 Not Found", "severity": "medium", "detail": "Check the path, base URL, and resource identifier."})
        suggestions += ["Compare the path with the API specification.", "Check for a missing ID or trailing slash."]
    elif status == 429:
        summary = "The request was rate limited."
        findings.append({"title": "429 Rate limited", "severity": "medium", "detail": "Retry after the advertised delay and add backoff."})
        suggestions += ["Read Retry-After if present.", "Add exponential backoff with jitter."]
    elif 500 <= status < 600:
        summary = f"Server error {status}; the failure is likely on the provider side."
        findings.append({"title": "Server-side failure", "severity": "high", "detail": "Capture a request ID and retry idempotent requests with backoff."})
        suggestions += ["Retry idempotent requests with backoff.", "Escalate with the request ID and timestamp."]
    elif 400 <= status < 500:
        summary = f"Client error {status}; the request needs correction."
        findings.append({"title": "Client error", "severity": "medium", "detail": "Inspect validation messages and required fields."})
        suggestions += ["Validate required fields and content type.", "Log the response body without secrets."]
    else:
        summary = f"Informational response {status}."
    if "cors" in lowered:
        findings.append({"title": "CORS mentioned", "severity": "medium", "detail": "Check allowed origins, methods, and preflight headers."})
    if "timeout" in lowered:
        findings.append({"title": "Timeout mentioned", "severity": "medium", "detail": "Check server latency and client timeout settings."})
    if not body:
        suggestions.append("Attach the response body for more specific guidance.")
    rows = [["Status class", f"{status // 100}xx"], ["Body supplied", "yes" if body else "no"], ["Method", method], ["URL host", re.sub(r"^https?://([^/]+).*", r"\1", url)]]
    return _result(summary, {
        "metrics": {"status": status, "client_error": 400 <= status < 500, "server_error": status >= 500},
        "findings": findings,
        "items": suggestions,
        "table": {"columns": ["Check", "Value"], "rows": rows},
    }, ["No network request was made; this analysis uses the supplied request and response details."])


run = agent_api_detective
