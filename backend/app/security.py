from __future__ import annotations

import ipaddress
import os
import ssl
from urllib.parse import urlsplit
from typing import Any, Awaitable, Callable


def production_mode() -> bool:
    return os.getenv("NETLAB_ENV", "development").strip().lower() in {"production", "prod"}


def configured_origins() -> list[str]:
    return [
        origin.strip()
        for origin in os.getenv(
            "NETLAB_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
        ).split(",")
        if origin.strip()
    ]


def configured_hosts() -> list[str]:
    return [host.strip() for host in os.getenv("NETLAB_ALLOWED_HOSTS", "").split(",") if host.strip()]


def configured_images() -> set[str]:
    return {image.strip() for image in os.getenv("NETLAB_ALLOWED_IMAGES", "").split(",") if image.strip()}


def strong_secret(value: str) -> bool:
    return len(value) >= 32 and len(set(value)) >= 16


def client_ssl_context(prefix: str, required: bool = False) -> ssl.SSLContext | None:
    ca_file = os.getenv(f"{prefix}_CA_FILE", "")
    cert_file = os.getenv(f"{prefix}_CERT_FILE", "")
    key_file = os.getenv(f"{prefix}_KEY_FILE", "")
    configured = (ca_file, cert_file, key_file)
    if not any(configured):
        if required:
            raise RuntimeError(f"{prefix} requires CA, client certificate and private key files")
        return None
    if not all(configured):
        raise RuntimeError(f"{prefix} requires CA, client certificate and private key files")
    context = ssl.create_default_context(cafile=ca_file)
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return context


def _validate_server_mtls(errors: list[str]) -> None:
    cert_file = os.getenv("NETLAB_MTLS_SERVER_CERT_FILE", "")
    key_file = os.getenv("NETLAB_MTLS_SERVER_KEY_FILE", "")
    ca_file = os.getenv("NETLAB_MTLS_SERVER_CA_FILE", "")
    if not all((cert_file, key_file, ca_file)):
        errors.append(
            "mTLS server requires NETLAB_MTLS_SERVER_CERT_FILE, "
            "NETLAB_MTLS_SERVER_KEY_FILE and NETLAB_MTLS_SERVER_CA_FILE",
        )
        return
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
        context.load_verify_locations(cafile=ca_file)
        context.verify_mode = ssl.CERT_REQUIRED
    except (OSError, ssl.SSLError) as exc:
        errors.append(f"mTLS server certificate configuration is invalid: {exc}")


def validate_production_settings() -> None:
    if not production_mode():
        return

    errors: list[str] = []
    if os.getenv("NETLAB_COOKIE_SECURE", "").strip().lower() not in {"1", "true", "yes"}:
        errors.append("NETLAB_COOKIE_SECURE=true is required")
    database_url = os.getenv("NETLAB_DATABASE_URL", "")
    database = urlsplit(database_url)
    if database.scheme not in {"postgres", "postgresql"}:
        errors.append("NETLAB_DATABASE_URL must point to PostgreSQL")
    elif dict(part.split("=", 1) for part in database.query.split("&") if "=" in part).get("sslmode") not in {
        "require", "verify-ca", "verify-full",
    }:
        errors.append("NETLAB_DATABASE_URL must require TLS with sslmode=require or stronger")
    origins = configured_origins()
    if not origins or any(
        (parsed := urlsplit(origin)).scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        for origin in origins
    ):
        errors.append("NETLAB_ALLOWED_ORIGINS must contain only HTTPS origins")
    hosts = configured_hosts()
    if not hosts or "*" in hosts:
        errors.append("NETLAB_ALLOWED_HOSTS must list the public API hostnames")
    worker_url = os.getenv("NETLAB_WORKER_URL", "")
    worker = urlsplit(worker_url)
    if worker.scheme != "https" or not worker.hostname or worker.username is not None or worker.password is not None or worker.query or worker.fragment:
        errors.append("NETLAB_WORKER_URL must use HTTPS")
    if not strong_secret(os.getenv("NETLAB_WORKER_TOKEN", "")):
        errors.append("NETLAB_WORKER_TOKEN must be a high-entropy secret of at least 32 characters")
    try:
        client_ssl_context("NETLAB_MTLS", required=True)
    except (OSError, ssl.SSLError, RuntimeError) as exc:
        errors.append(f"API-to-worker mTLS configuration is invalid: {exc}")
    if not configured_images():
        errors.append("NETLAB_ALLOWED_IMAGES must list pre-approved container images")
    bootstrap_token = os.getenv("NETLAB_BOOTSTRAP_TOKEN", "")
    if bootstrap_token and not strong_secret(bootstrap_token):
        errors.append("NETLAB_BOOTSTRAP_TOKEN must be a high-entropy secret of at least 32 characters")
    if errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))


def validate_production_topology(topology: dict[str, Any]) -> None:
    if not production_mode():
        return
    allowed = configured_images()
    rejected = sorted({
        node.get("image", "<missing image>")
        for node in topology.get("nodes", [])
        if not isinstance(node, dict) or node.get("image") not in allowed
    })
    if rejected:
        raise ValueError(f"topology contains images not approved by NETLAB_ALLOWED_IMAGES: {', '.join(rejected)}")


def validate_worker_settings() -> None:
    if not production_mode():
        return
    errors: list[str] = []
    if not strong_secret(os.getenv("NETLAB_WORKER_TOKEN", "")):
        errors.append("NETLAB_WORKER_TOKEN must be a high-entropy secret of at least 32 characters")
    if not configured_images():
        errors.append("NETLAB_ALLOWED_IMAGES must list pre-approved container images")
    if os.getenv("NETLAB_WORKER_TLS_ENABLED", "").strip().lower() not in {"1", "true", "yes"}:
        errors.append("worker production server must be launched with worker.server and HTTPS/mTLS enabled")
    _validate_server_mtls(errors)
    control_url = urlsplit(os.getenv("NETLAB_CONTROL_URL", ""))
    if (
        control_url.scheme != "https"
        or not control_url.hostname
        or control_url.username is not None
        or control_url.password is not None
        or control_url.query
        or control_url.fragment
    ):
        errors.append("NETLAB_CONTROL_URL must use HTTPS in production")
    try:
        client_ssl_context("NETLAB_CONTROL_MTLS", required=True)
    except (OSError, ssl.SSLError, RuntimeError) as exc:
        errors.append(f"worker-to-control mTLS configuration is invalid: {exc}")
    host = os.getenv("NETLAB_WORKER_HOST", "")
    try:
        address = ipaddress.ip_address(host)
        # A containerized worker must bind 0.0.0.0 to be reachable by the
        # control plane on the private Compose network. It is not published
        # to the host; the explicit flag prevents silently allowing this in a
        # normal host deployment.
        container_bind = os.getenv("NETLAB_WORKER_CONTAINER", "").strip().lower() in {"1", "true", "yes"}
        if (address.is_unspecified and not container_bind) or not (
            address.is_unspecified or address.is_loopback or address.is_private
        ):
            errors.append("NETLAB_WORKER_HOST must be a loopback or private IP address")
    except ValueError:
        if host.lower() != "localhost":
            errors.append("NETLAB_WORKER_HOST must be localhost or a loopback/private IP address")
    if errors:
        raise RuntimeError("Unsafe production worker configuration: " + "; ".join(errors))


class BodySizeLimitMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]], max_bytes: int = 2 * 1024 * 1024) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[dict[str, Any]]], send: Callable[..., Awaitable[None]]) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_lengths = [value for key, value in scope.get("headers", []) if key.lower() == b"content-length"]
        if content_lengths:
            try:
                parsed_lengths = {int(value) for value in content_lengths}
                if len(parsed_lengths) != 1 or next(iter(parsed_lengths)) < 0:
                    await self._reject(send)
                    return
                if next(iter(parsed_lengths)) > self.max_bytes:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send)
                return

        received = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _RequestTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestTooLarge:
            await self._reject(send)

    @staticmethod
    async def _reject(send: Callable[..., Awaitable[None]]) -> None:
        body = b'{"detail":"request body too large"}'
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})


class _RequestTooLarge(Exception):
    pass


class SecurityHeadersMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[dict[str, Any]]], send: Callable[..., Awaitable[None]]) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                ])
                if production_mode():
                    headers.append(
                        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
                    )
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, secure_send)
