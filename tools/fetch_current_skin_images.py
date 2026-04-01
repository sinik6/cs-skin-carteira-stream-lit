from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
SNAPSHOT_FILE = ROOT_DIR / "data" / "current_skin_catalog.json"

ALLOWED_IMAGE_HOSTS = {
    "community.cloudflare.steamstatic.com",
    "community.akamai.steamstatic.com",
}


def normalize_url(url: str) -> str:
    return (url or "").strip()


def is_supported_url(url: str) -> bool:
    normalized = normalize_url(url)
    if not normalized:
        return False
    parsed = urlparse(normalized)
    return parsed.scheme == "https" and parsed.netloc in ALLOWED_IMAGE_HOSTS


def main() -> None:
    if not SNAPSHOT_FILE.exists():
        raise SystemExit(
            f"Snapshot nao encontrado em {SNAPSHOT_FILE}. "
            "Gere primeiro o current_skin_catalog.json com build_current_skin_catalog.py."
        )
    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))

    supported = 0
    unsupported = 0

    for item in snapshot.get("items_by_skin_id", {}).values():
        updated = normalize_url(item.get("image", ""))
        item["image"] = updated
        item.pop("local_image", None)
        if is_supported_url(updated):
            supported += 1
        elif updated:
            unsupported += 1

    for item in snapshot.get("items_by_lookup", {}).values():
        item["image"] = normalize_url(item.get("image", ""))
        item.pop("local_image", None)

    SNAPSHOT_FILE.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"URLs de imagem compativeis com o modo seguro: {supported}")
    print(f"URLs de imagem ainda nao suportadas: {unsupported}")


if __name__ == "__main__":
    main()
