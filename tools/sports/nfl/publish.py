"""Upload cleaned dataset, model and hold-out results to Azure Blob container nba/sports/nfl/.

Credentials come from the environment (AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET);
nothing secret is stored in the repo.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
from azure.identity import ClientSecretCredential

from tools.sports.nfl.build import OUT_DEFAULT

BASE = "https://stpersonalv5ethud2i3cfq.blob.core.windows.net/nba/sports/nfl/"
FILES = ["dataset.csv.gz", "model.json", "holdout_results.json"]


def publish(out: Path = OUT_DEFAULT) -> None:
    import os

    e = os.environ
    cred = ClientSecretCredential(
        e["AZURE_TENANT_ID"], e["AZURE_CLIENT_ID"], e["AZURE_CLIENT_SECRET"]
    )
    tok = cred.get_token("https://storage.azure.com/.default").token
    for n in FILES:
        r = httpx.put(BASE + n, content=(out / n).read_bytes(), timeout=120, headers={
            "Authorization": f"Bearer {tok}", "x-ms-version": "2021-08-06",
            "x-ms-blob-type": "BlockBlob"})
        print(n, r.status_code)


if __name__ == "__main__":
    publish(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DEFAULT)
