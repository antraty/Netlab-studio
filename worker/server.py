import os
import ssl

import uvicorn


def main() -> None:
    kwargs = {}
    cert_file = os.getenv("NETLAB_MTLS_SERVER_CERT_FILE", "")
    key_file = os.getenv("NETLAB_MTLS_SERVER_KEY_FILE", "")
    ca_file = os.getenv("NETLAB_MTLS_SERVER_CA_FILE", "")
    if any((cert_file, key_file, ca_file)):
        if not all((cert_file, key_file, ca_file)):
            raise RuntimeError(
                "mTLS server requires NETLAB_MTLS_SERVER_CERT_FILE, "
                "NETLAB_MTLS_SERVER_KEY_FILE and NETLAB_MTLS_SERVER_CA_FILE",
            )
        kwargs.update(
            ssl_certfile=cert_file,
            ssl_keyfile=key_file,
            ssl_ca_certs=ca_file,
            ssl_cert_reqs=ssl.CERT_REQUIRED,
        )
    uvicorn.run(
        "worker.main:app",
        host=os.getenv("NETLAB_WORKER_HOST", "0.0.0.0"),
        port=int(os.getenv("NETLAB_WORKER_PORT", "9000")),
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info"),
        **kwargs,
    )


if __name__ == "__main__":
    main()
