#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


def validate_substitutions(values: dict[str, str]) -> None:
    """Reject YAML injection and accidental credential-bearing configuration."""
    for marker, value in values.items():
        if not value or any(character.isspace() for character in value):
            raise ValueError(f"empty or whitespace-containing value for {marker}")
        if marker.endswith("IMAGE__"):
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/@-]{0,511}", value):
                raise ValueError(f"invalid image reference for {marker}")
        elif marker in {"__AZURE_CLIENT_ID__", "__AZURE_TENANT_ID__"}:
            UUID(value)
        elif marker == "__KEY_VAULT_NAME__":
            if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9-]{1,22}[a-zA-Z0-9]", value):
                raise ValueError("invalid Key Vault name")
        elif marker == "__AZURE_STORAGE_ACCOUNT_URL__":
            url = urlsplit(value)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path not in {"", "/"}
                or not re.fullmatch(r"[a-zA-Z0-9.-]+", url.netloc)
            ):
                raise ValueError(
                    "storage URL must be an HTTPS account endpoint without credentials"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the Azure Kubernetes manifest")
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--worker-image", required=True)
    parser.add_argument("--tracking-image", required=True)
    parser.add_argument("--storage-url", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--key-vault", required=True)
    parser.add_argument("--template", type=Path, default=Path("k8s/azure.yaml"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    substitutions = {
        "__API_IMAGE__": args.api_image,
        "__WORKER_IMAGE__": args.worker_image,
        "__TRACKING_IMAGE__": args.tracking_image,
        "__AZURE_STORAGE_ACCOUNT_URL__": args.storage_url,
        "__AZURE_CLIENT_ID__": args.client_id,
        "__AZURE_TENANT_ID__": args.tenant_id,
        "__KEY_VAULT_NAME__": args.key_vault,
    }
    validate_substitutions(substitutions)
    rendered = args.template.read_text(encoding="utf-8")
    for marker, value in substitutions.items():
        rendered = rendered.replace(marker, value)
    unresolved = re.findall(r"__[A-Z_]+__", rendered)
    if unresolved:
        raise ValueError(f"unresolved template markers: {unresolved}")
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
