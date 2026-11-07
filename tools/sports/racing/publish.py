"""Upload the cleaned datasets, fitted model and hold-out results to blob container nba under
sports/racing/. Credentials from env (AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET)."""

import os
import sys

import httpx
from azure.identity import ClientSecretCredential

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import OUT  # noqa: E402

ACCOUNT = "stpersonalv5ethud2i3cfq"
FILES = [
    "dataset.csv.gz",
    "betfair.csv.gz",
    "model.json",
    "holdout_results.json",
    "build_meta.json",
]


def main() -> None:
    cred = ClientSecretCredential(
        os.environ["AZURE_TENANT_ID"],
        os.environ["AZURE_CLIENT_ID"],
        os.environ["AZURE_CLIENT_SECRET"],
    )
    token = cred.get_token("https://storage.azure.com/.default").token
    for name in FILES:
        with open(os.path.join(OUT, name), "rb") as f:
            data = f.read()
        ctype = "application/json" if name.endswith(".json") else "application/gzip"
        r = httpx.put(
            f"https://{ACCOUNT}.blob.core.windows.net/nba/sports/racing/{name}",
            content=data,
            timeout=600,
            headers={
                "Authorization": f"Bearer {token}",
                "x-ms-version": "2021-08-06",
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": ctype,
            },
        )
        r.raise_for_status()
        print("put", name, len(data), r.status_code)


if __name__ == "__main__":
    main()
