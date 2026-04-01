from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.models import AppData, Skin
from app.services import catalog_service, runtime_state, storage
from app.services.bymykel_catalog import ByMykelCatalogClient, infer_required_sources
from app.services import catalog_sync
from app.services.catalog_sync import sync_catalog_snapshot
from app.services.price_providers.csfloat import CSFloatProvider
from app.services.thumbnail_service import ThumbnailService


class SkinModelTests(unittest.TestCase):
    def test_configurable_iof_and_status(self) -> None:
        skin = Skin(
            nome="AK-47 | Slate",
            preco_compra=100.0,
            preco_atual=135.0,
            iof_aplicavel=True,
        )
        self.assertEqual(skin.total_com_iof_com_taxa(10), 110.0)
        self.assertEqual(skin.lucro_com_taxa(10), 25.0)
        self.assertAlmostEqual(skin.variacao_pct_com_taxa(10), 0.2273, places=4)
        self.assertEqual(skin.status_preco(), "Ao vivo")


class CSFloatEstimationTests(unittest.TestCase):
    def test_estimation_prefers_nearest_float_comparables(self) -> None:
        provider = CSFloatProvider("key")
        listings = [
            {"price": 10000, "item": {"float_value": 0.151}},
            {"price": 10500, "item": {"float_value": 0.148}},
            {"price": 11000, "item": {"float_value": 0.149}},
            {"price": 18000, "item": {"float_value": 0.400}},
            {"price": 19000, "item": {"float_value": 0.500}},
        ]
        preco, usados = provider._estimar_preco_usd(listings, target_float=0.15)
        self.assertEqual(usados, 5)
        self.assertEqual(preco, 110.0)

    def test_extract_image_url_from_listing(self) -> None:
        provider = CSFloatProvider("key")
        listings = [
            {"item": {"icon_url": "-9a81-example-icon"}},
        ]
        image_url = provider._extrair_imagem_url(listings)
        self.assertIn("community.cloudflare.steamstatic.com/economy/image", image_url)
        self.assertIn("-9a81-example-icon", image_url)


class StorageBackupTests(unittest.TestCase):
    def test_load_falls_back_to_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            original_data_file = storage.DATA_FILE
            original_backup_file = storage.DATA_FILE_BACKUP
            original_data_dir = storage.DATA_DIR
            try:
                storage.DATA_DIR = temp_path
                storage.DATA_FILE = temp_path / "skins.json"
                storage.DATA_FILE_BACKUP = temp_path / "skins.backup.json"

                valid_data = AppData(skins=[Skin(nome="M4A1-S | Basilisk")])
                storage.DATA_FILE_BACKUP.write_text(valid_data.model_dump_json(indent=2), encoding="utf-8")
                storage.DATA_FILE.write_text("{invalid json", encoding="utf-8")

                loaded = storage.carregar_dados()
                self.assertEqual(len(loaded.skins), 1)
                self.assertEqual(loaded.skins[0].nome, "M4A1-S | Basilisk")
            finally:
                storage.DATA_FILE = original_data_file
                storage.DATA_FILE_BACKUP = original_backup_file
                storage.DATA_DIR = original_data_dir


class ThumbnailServiceTests(unittest.TestCase):
    def test_rejects_non_allowlisted_urls(self) -> None:
        self.assertFalse(ThumbnailService.is_allowed_url("https://example.com/image.png"))
        self.assertFalse(ThumbnailService.is_allowed_url("http://community.cloudflare.steamstatic.com/economy/image/test"))
        self.assertTrue(
            ThumbnailService.is_allowed_url(
                "https://community.cloudflare.steamstatic.com/economy/image/test/160fx160f"
            )
        )
        self.assertTrue(
            ThumbnailService.is_allowed_url(
                "https://community.akamai.steamstatic.com/economy/image/test"
            )
        )

    def test_downloads_and_reuses_local_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "thumbs"
            state_file = Path(temp_dir) / "thumbnail_state.json"
            service = ThumbnailService(cache_dir=cache_dir, state_file=state_file, ttl_seconds=9999)

            response = Mock()
            response.headers = {"Content-Type": "image/png", "Content-Length": "4"}
            response.iter_content.return_value = [b"test"]
            response.raise_for_status.return_value = None

            with patch.object(service._session, "get", return_value=response) as mock_get:
                path = service.get_local_path(
                    "https://community.cloudflare.steamstatic.com/economy/image/test/160fx160f"
                )
                self.assertIsNotNone(path)
                self.assertTrue(path.exists())
                self.assertEqual(mock_get.call_count, 1)

                reused = service.get_local_path(
                    "https://community.cloudflare.steamstatic.com/economy/image/test/160fx160f"
                )
                self.assertEqual(path, reused)
                self.assertEqual(mock_get.call_count, 1)

    def test_failed_download_enters_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "thumbs"
            state_file = Path(temp_dir) / "thumbnail_state.json"
            service = ThumbnailService(
                cache_dir=cache_dir,
                state_file=state_file,
                error_cooldown_seconds=3600,
            )
            url = "https://community.cloudflare.steamstatic.com/economy/image/test/160fx160f"

            with patch.object(service._session, "get", side_effect=Exception("boom")) as mock_get:
                path = service.get_local_path(url)
                self.assertIsNone(path)
                self.assertEqual(mock_get.call_count, 1)

            with patch.object(service._session, "get") as mock_get:
                retry = service.get_local_path(url)
                self.assertIsNone(retry)
                self.assertEqual(mock_get.call_count, 0)


class RuntimeStateCacheTests(unittest.TestCase):
    def test_price_cache_persists_image_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            original_price_cache_file = runtime_state.PRICE_CACHE_FILE
            original_provider_state_file = runtime_state.PROVIDER_STATE_FILE
            try:
                runtime_state.PRICE_CACHE_FILE = temp_path / "price_cache.json"
                runtime_state.PROVIDER_STATE_FILE = temp_path / "provider_state.json"

                runtime_state.set_cached_price(
                    key="csfloat|ak-47",
                    preco=12.34,
                    provider="CSFloat",
                    ttl_seconds=60,
                    imagem_url="https://community.cloudflare.steamstatic.com/economy/image/test/160fx160f",
                )

                cached = runtime_state.get_cached_price("csfloat|ak-47")
                self.assertIsNotNone(cached)
                self.assertEqual(
                    cached.imagem_url,
                    "https://community.cloudflare.steamstatic.com/economy/image/test/160fx160f",
                )
            finally:
                runtime_state.PRICE_CACHE_FILE = original_price_cache_file
                runtime_state.PROVIDER_STATE_FILE = original_provider_state_file


class CatalogServiceTests(unittest.TestCase):
    def test_hydrates_skin_from_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / "current_skin_catalog.json"
            snapshot_file.write_text(
                """
{
  "items_by_skin_id": {
    "abc123": {
      "market_hash_name": "AK-47 | Slate (Factory New)",
                    "image": "https://community.akamai.steamstatic.com/economy/image/test"
    }
  },
  "items_by_lookup": {}
}
                """.strip(),
                encoding="utf-8",
            )

            original_snapshot_file = catalog_service.CATALOG_SNAPSHOT_FILE
            try:
                catalog_service.CATALOG_SNAPSHOT_FILE = snapshot_file
                catalog_service.load_catalog_snapshot.cache_clear()

                skin = Skin(
                    id="abc123",
                    nome="AK-47 | Slate",
                    tipo="Arma",
                    desgaste="Factory New (FN)",
                )
                changed = catalog_service.hydrate_skin_from_catalog(skin)
                self.assertTrue(changed)
                self.assertEqual(skin.market_hash_name, "AK-47 | Slate (Factory New)")
                self.assertIn("community.akamai.steamstatic.com", skin.imagem_url)
            finally:
                catalog_service.CATALOG_SNAPSHOT_FILE = original_snapshot_file
                catalog_service.load_catalog_snapshot.cache_clear()


class ByMykelCatalogTests(unittest.TestCase):
    def test_infer_required_sources_uses_only_needed_categories(self) -> None:
        raw_skins = [
            {"nome": "AK-47 | Slate", "tipo": "Arma"},
            {"nome": "Battle Scarred (Holo) (Roxo)", "tipo": "Adesivo"},
            {"nome": "Lt. Commander Ricksaw", "tipo": "Agente"},
            {"nome": "Missing Type", "tipo": "Outro"},
        ]

        self.assertEqual(
            infer_required_sources(raw_skins),
            [
                "skins_not_grouped.json",
                "stickers.json",
                "agents.json",
                "collectibles.json",
                "tools.json",
            ],
        )

    def test_remote_source_is_cached_locally(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "catalog_cache"
            session = Mock()

            response = Mock()
            response.json.return_value = [{"name": "Sticker | Test", "market_hash_name": "Sticker | Test"}]
            response.raise_for_status.return_value = None
            session.get.return_value = response

            client = ByMykelCatalogClient(cache_dir=cache_dir, session=session)
            first = client.load_source_items("stickers.json")
            second = client.load_source_items("stickers.json")

            self.assertEqual(len(first), 1)
            self.assertEqual(first, second)
            self.assertEqual(session.get.call_count, 1)


class CatalogSyncTests(unittest.TestCase):
    def test_sync_catalog_snapshot_builds_snapshot_and_hydrates_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            original_catalog_snapshot_file = catalog_service.CATALOG_SNAPSHOT_FILE
            original_catalog_sync_snapshot_file = catalog_sync.CATALOG_SNAPSHOT_FILE
            original_storage_data_dir = storage.DATA_DIR
            original_storage_data_file = storage.DATA_FILE
            original_storage_backup_file = storage.DATA_FILE_BACKUP
            try:
                catalog_service.CATALOG_SNAPSHOT_FILE = temp_path / "current_skin_catalog.json"
                catalog_sync.CATALOG_SNAPSHOT_FILE = temp_path / "current_skin_catalog.json"
                storage.DATA_DIR = temp_path
                storage.DATA_FILE = temp_path / "skins.json"
                storage.DATA_FILE_BACKUP = temp_path / "skins.backup.json"

                data = AppData(
                    skins=[
                        Skin(
                            id="abc123",
                            nome="Battle Scarred (Holo) (Roxo)",
                            tipo="Adesivo",
                            desgaste="N/A",
                        )
                    ]
                )
                storage.salvar_dados(data)

                session = Mock()
                response = Mock()
                response.raise_for_status.return_value = None
                response.json.return_value = [
                    {
                        "market_hash_name": "Sticker | Battle Scarred (Holo)",
                        "name": "Sticker | Battle Scarred (Holo)",
                        "image": "https://community.akamai.steamstatic.com/economy/image/test",
                        "collections": [],
                        "crates": [],
                    }
                ]
                session.get.return_value = response

                client = ByMykelCatalogClient(cache_dir=temp_path / "catalog_cache", session=session)
                result = sync_catalog_snapshot(client=client)

                self.assertEqual(result.matched_skins, 1)
                self.assertEqual(result.hydrated_skins, 1)
                self.assertTrue((temp_path / "current_skin_catalog.json").exists())

                reloaded = storage.carregar_dados()
                self.assertEqual(reloaded.skins[0].market_hash_name, "Sticker | Battle Scarred (Holo)")
                self.assertIn("community.akamai.steamstatic.com", reloaded.skins[0].imagem_url)
            finally:
                catalog_service.CATALOG_SNAPSHOT_FILE = original_catalog_snapshot_file
                catalog_sync.CATALOG_SNAPSHOT_FILE = original_catalog_sync_snapshot_file
                catalog_service.load_catalog_snapshot.cache_clear()
                storage.DATA_DIR = original_storage_data_dir
                storage.DATA_FILE = original_storage_data_file
                storage.DATA_FILE_BACKUP = original_storage_backup_file


if __name__ == "__main__":
    unittest.main()
