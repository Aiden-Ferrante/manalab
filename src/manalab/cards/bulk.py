"""Scryfall bulk-data download. Keyless, stdlib-only.

Scryfall publishes daily full exports and explicitly asks that you use them
instead of crawling the API. We only ever touch two URLs: the bulk index, and
whichever export it points at.

The exports are gzipped JSONL. We keep them gzipped on disk — DuckDB reads
`.jsonl.gz` directly, so decompressing would cost ~150 MB for nothing.

Data is under the WotC Fan Content Policy plus Scryfall's terms — fine for
research, requires attribution, is not CC0. See ATTRIBUTION.md.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BULK_INDEX = "https://api.scryfall.com/bulk-data"

# Scryfall asks every client to identify itself and set an explicit Accept.
HEADERS = {
    "User-Agent": "manalab/0.1 (research; deckbuilding simulation)",
    "Accept": "application/json",
}


@dataclass(frozen=True)
class BulkEntry:
    kind: str
    download_uri: str
    size_bytes: int
    updated_at: str

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1_000_000

    @property
    def suffix(self) -> str:
        """Extension the export actually uses, e.g. `.jsonl.gz`.

        Read from the URI rather than hardcoded: Scryfall moved from `.json` to
        `.jsonl.gz` once already, and DuckDB dispatches on this extension.
        """
        name = self.download_uri.rsplit("/", 1)[-1]
        parts = name.split(".")
        return "." + ".".join(parts[1:]) if len(parts) > 1 else ".json"


def fetch_index() -> dict[str, BulkEntry]:
    """List available bulk exports. ~2 KB; safe to call freely."""
    req = urllib.request.Request(BULK_INDEX, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)

    out: dict[str, BulkEntry] = {}
    for item in payload.get("data", []):
        # `jsonl_download_uri`/`compressed_size` are the current field names;
        # the older `download_uri`/`size` are accepted so a rollback isn't fatal.
        uri = item.get("jsonl_download_uri") or item.get("download_uri")
        if not uri:
            continue
        out[item["type"]] = BulkEntry(
            kind=item["type"],
            download_uri=uri,
            size_bytes=int(item.get("compressed_size") or item.get("size") or 0),
            updated_at=item.get("updated_at", ""),
        )
    return out


def path_for(kind: str, data_dir: Path = Path("data")) -> Path:
    """Where `kind` will land on disk, without downloading it."""
    entry = _entry(kind)
    return Path(data_dir) / f"{kind}{entry.suffix}"


def download(kind: str, data_dir: Path = Path("data"), *, force: bool = False) -> Path:
    """Download one bulk export. Returns the path written.

    `oracle_cards` is what you want: one record per distinct card, ~25 MB
    compressed. `default_cards` and `all_cards` include every printing.

    Skips only when the local copy matches upstream's `updated_at`, recorded in a
    sidecar at download time. The old rule — skip whenever the file exists — made
    a re-fetch against *changed* upstream data a silent no-op: the CLI printed the
    new timestamp and URL, kept a three-day-old file, and said "done".
    """
    entry = _entry(kind)
    dest = Path(data_dir) / f"{kind}{entry.suffix}"
    meta = dest.with_suffix(dest.suffix + ".meta.json")

    if dest.exists() and not force:
        recorded = _provenance(meta)
        if recorded.get("updated_at") == entry.updated_at:
            return dest      # genuinely current — this is the no-op the waypoint asks for

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")

    req = urllib.request.Request(entry.download_uri, headers=HEADERS)
    digest = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=600) as resp, tmp.open("wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            digest.update(chunk)

    tmp.replace(dest)
    meta.write_text(json.dumps({
        "kind": kind,
        "updated_at": entry.updated_at,
        "download_uri": entry.download_uri,
        "sha256": digest.hexdigest(),
        "bytes": dest.stat().st_size,
    }, indent=2) + "\n")
    return dest


def _provenance(meta: Path) -> dict:
    """What we recorded when the file was written. Empty when unknown — a file
    with no sidecar predates provenance and must be treated as stale."""
    try:
        return json.loads(meta.read_text())
    except (OSError, ValueError):
        return {}


def _entry(kind: str) -> BulkEntry:
    index = fetch_index()
    entry = index.get(kind)
    if entry is None:
        raise KeyError(f"unknown bulk kind {kind!r}; available: {', '.join(sorted(index))}")
    return entry
