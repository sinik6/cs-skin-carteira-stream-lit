from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.bymykel_catalog import (
    ByMykelCatalogClient,
    build_indexes,
    infer_required_sources,
    lookup_candidates,
    select_catalog_item,
)

API_ROOT_ENV = "CS2_API_ROOT"
CURRENT_SKINS_FILE_ENV = "CS2_CURRENT_SKINS_FILE"
OUTPUT_FILE_ENV = "CS2_CATALOG_OUTPUT_FILE"
LANGUAGE_ENV = "CS2_SOURCE_LANGUAGE"
CACHE_DIR_ENV = "CS2_SOURCE_CACHE_DIR"
FORCE_REFRESH_ENV = "CS2_FORCE_REFRESH"

CURRENT_SKINS_FILE = Path(os.getenv(CURRENT_SKINS_FILE_ENV, "data/skins.json"))
OUTPUT_FILE = Path(os.getenv(OUTPUT_FILE_ENV, "data/current_skin_catalog.json"))


def main() -> None:
    api_root_value = os.getenv(API_ROOT_ENV, "").strip()
    if not CURRENT_SKINS_FILE.exists():
        raise SystemExit(
            f"Arquivo de skins atual nao encontrado: {CURRENT_SKINS_FILE}. "
            f"Defina {CURRENT_SKINS_FILE_ENV} ou gere primeiro o data/skins.json do app."
        )
    raw_skins = json.loads(CURRENT_SKINS_FILE.read_text(encoding="utf-8")).get("skins", [])
    language = os.getenv(LANGUAGE_ENV, "en").strip() or "en"
    cache_dir_value = os.getenv(CACHE_DIR_ENV, "").strip()
    cache_dir = Path(cache_dir_value) if cache_dir_value else ROOT_DIR / "data" / "catalog_cache"
    force_refresh = os.getenv(FORCE_REFRESH_ENV, "").strip().lower() in {"1", "true", "yes"}

    client = ByMykelCatalogClient(
        language=language,
        cache_dir=cache_dir,
        local_api_root=Path(api_root_value) if api_root_value else None,
    )

    source_files = infer_required_sources(raw_skins)
    items = client.load_catalog_items(source_files, force_refresh=force_refresh)
    by_lookup, by_name = build_indexes(items)

    items_by_skin_id: dict[str, dict] = {}
    items_by_lookup: dict[str, dict] = {}
    unmatched: list[str] = []

    for raw_skin in raw_skins:
        match = None
        for candidate in lookup_candidates(raw_skin):
            match = by_lookup.get(candidate) or by_name.get(candidate)
            if match:
                break

        if not match:
            unmatched.append(raw_skin.get("nome", ""))
            continue

        selected = select_catalog_item(match)
        items_by_skin_id[raw_skin["id"]] = selected

        for candidate in lookup_candidates(raw_skin):
            items_by_lookup.setdefault(candidate, selected)

    payload = {
        "catalog_version": 1,
        "source": {
            "provider": "ByMykel/CSGO-API",
            "language": language,
            "mode": "local" if api_root_value else "remote-cached",
            "source_files": source_files,
        },
        "total_current_skins": len(raw_skins),
        "matched_skins": len(items_by_skin_id),
        "unmatched_skins": unmatched,
        "items_by_skin_id": items_by_skin_id,
        "items_by_lookup": items_by_lookup,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"Snapshot gerado em {OUTPUT_FILE} com {len(items_by_skin_id)} skins casadas "
        f"usando {len(source_files)} arquivo(s) de catalogo."
    )
    if unmatched:
        print("Sem match:")
        for name in unmatched:
            print(name)


if __name__ == "__main__":
    main()
