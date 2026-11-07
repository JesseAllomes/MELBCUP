"""Upload the NHL datasets, model and hold-out results to Azure Blob container "nba" (sports/nhl/).

    set -a; . <azure.env>; set +a
    python3 tools/sports/nhl/publish.py [DATA_DIR]

Uses the service principal in the environment (AZURE_TENANT_ID / AZURE_CLIENT_ID /
AZURE_CLIENT_SECRET); no key is stored in the repo.
"""

from __future__ import annotations

import os
import sys
import urllib.request

from azure.identity import ClientSecretCredential

ACCOUNT = "https://stpersonalv5ethud2i3cfq.blob.core.windows.net/nba/"
DATA = "/tmp/claude-0/-home-user/418442d0-6a93-5b3f-a291-37c2b3744726/scratchpad/sports/nhl/data"
FILES = {"games.csv.gz": "sports/nhl/dataset.csv.gz", "model.json": "sports/nhl/model.json",
         "holdout_results.json": "sports/nhl/holdout_results.json"}


def main(data: str = DATA) -> None:
    cred = ClientSecretCredential(os.environ["AZURE_TENANT_ID"], os.environ["AZURE_CLIENT_ID"],
                                  os.environ["AZURE_CLIENT_SECRET"])
    tok = cred.get_token("https://storage.azure.com/.default").token
    for local, blob in FILES.items():
        body = open(os.path.join(data, local), "rb").read()
        ctype = "application/json" if blob.endswith(".json") else "application/gzip"
        req = urllib.request.Request(ACCOUNT + blob, data=body, method="PUT", headers={
            "Authorization": f"Bearer {tok}", "x-ms-version": "2021-08-06",
            "x-ms-blob-type": "BlockBlob", "Content-Type": ctype})
        with urllib.request.urlopen(req, timeout=120) as r:
            print(blob, r.status, len(body))


if __name__ == "__main__":
    main(*sys.argv[1:2])
