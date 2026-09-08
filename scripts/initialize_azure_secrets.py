"""Initialize missing runtime secrets without printing values or rotating existing keys.

Run on a trusted host/container with Azure CLI signed in. The caller must already
have Key Vault Secrets Officer (or equivalent) on this project's vault.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import tempfile
from pathlib import Path


def az(*args: str) -> str:
    return subprocess.check_output(["az", *args, "--output", "json"], text=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--insights", required=True)
    args = parser.parse_args()
    existing = {
        item["name"]
        for item in json.loads(az("keyvault", "secret", "list", "--vault-name", args.vault))
    }
    for name in ("api-key", "application-insights-connection-string"):
        if name in existing:
            print(f"Preserved existing {name}")
            continue
        value = (
            secrets.token_urlsafe(48)
            if name == "api-key"
            else json.loads(
                az(
                    "resource",
                    "show",
                    "--resource-group",
                    args.resource_group,
                    "--resource-type",
                    "Microsoft.Insights/components",
                    "--name",
                    args.insights,
                    "--api-version",
                    "2020-02-02",
                )
            )["properties"]["ConnectionString"]
        )
        with tempfile.TemporaryDirectory(prefix="mfbo-secret-") as directory:
            path = Path(directory) / "value"
            path.touch(mode=0o600)
            path.write_text(value)
            subprocess.run(
                [
                    "az",
                    "keyvault",
                    "secret",
                    "set",
                    "--vault-name",
                    args.vault,
                    "--name",
                    name,
                    "--file",
                    str(path),
                    "--output",
                    "none",
                ],
                check=True,
            )
        print(f"Initialized {name}; value not displayed")


if __name__ == "__main__":
    main()
