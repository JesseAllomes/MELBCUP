"""Pack every public dataset into one zip for outside review (owner, 2026-11-07).

    python3 tools/export_data.py          env AZURE_*, NBA_ACCOUNT; uploads export/asynym-data.zip
    python3 tools/export_data.py --out F  write the zip locally only

Takes every blob /data lists (melbcup/web/app.py `data_ok`), the per-sport write-ups in
research/sports/ and a README with what each file is, and writes them into one zip under data/.
Token-free: rerun it whenever a fresh snapshot is wanted.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NAME = "export/asynym-data.zip"


def data_rules():
    from melbcup.data_public import DATA_ABOUT, DATA_OK

    return DATA_OK, DATA_ABOUT


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args()
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    ok, about = data_rules()
    cc = BlobServiceClient(
        f"https://{os.environ['NBA_ACCOUNT']}.blob.core.windows.net",
        credential=DefaultAzureCredential(),
    ).get_container_client("nba")
    names = sorted(
        b.name for b in cc.list_blobs() if ok.match(b.name) and not b.name.startswith("export/")
    )
    buf = io.BytesIO()
    lines = [
        "# AsynymBet data export",
        f"Snapshot {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC. Live copies: https://bet.asynym.dev/data",
        "Code: https://github.com/JesseAllomes/MELBCUP (tools/sports, tools/nba, melbcup).",
        "Write-ups: research/ in this zip. .gz files are gzip CSV/JSON (pandas reads them).",
        "",
        "| file | what it is |",
        "|---|---|",
    ]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            raw = cc.download_blob(n).readall()
            z.writestr(
                "data/" + n, raw, zipfile.ZIP_STORED if n.endswith(".gz") else zipfile.ZIP_DEFLATED
            )
            what = next(w for pre, w in about if n.startswith(pre))
            lines.append(f"| data/{n} | {what} |")
        for md in sorted((ROOT / "research/sports").glob("*.md")):
            z.write(md, "research/sports/" + md.name)
        z.writestr("README.md", "\n".join(lines) + "\n")
    body = buf.getvalue()
    if a.out:
        Path(a.out).write_bytes(body)
    else:
        cc.upload_blob(NAME, body, overwrite=True)
    print(f"{len(names)} files, {len(body) / 1e6:.1f} MB -> {a.out or NAME}")


if __name__ == "__main__":
    main()
