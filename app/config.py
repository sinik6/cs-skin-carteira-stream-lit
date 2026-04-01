"""Constantes e configurações da aplicação."""

from pathlib import Path

APP_NAME = "CS2 Skin Tracker"
APP_ICON = "🎮"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path("/app/data") if Path("/app").exists() else BASE_DIR / "data"
DATA_FILE = DATA_DIR / "skins.json"
DATA_FILE_BACKUP = DATA_DIR / "skins.backup.json"
PRICE_CACHE_FILE = DATA_DIR / "price_cache.json"
PROVIDER_STATE_FILE = DATA_DIR / "provider_state.json"
LIQUIDITY_HISTORY_FILE = DATA_DIR / "liquidity_history.json"
THUMBNAILS_DIR = DATA_DIR / "thumbs"
THUMBNAIL_STATE_FILE = DATA_DIR / "thumbnail_state.json"
CATALOG_SNAPSHOT_FILE = DATA_DIR / "current_skin_catalog.json"

TIPOS_ITEM = [
    "Arma", "Faca", "Luva", "Adesivo", "Agente",
    "Charm", "Grafite", "Patch", "Music Kit", "Caixa", "Outro",
]

DESGASTES = [
    "Factory New (FN)", "Minimal Wear (MW)", "Field-Tested (FT)",
    "Well-Worn (WW)", "Battle-Scarred (BS)", "N/A",
]

PLATAFORMAS = [
    "CSFloat", "BUFF163", "Steam Market", "DMarket", "CS.Money",
    "Skinport", "BitSkins", "Tradeit.gg", "SkinBaron",
    "DashSkins", "BleikStore", "NeshaStore", "BRSkins",
    "White Market", "Trade P2P", "Drop in-game", "Outro",
]

PRICE_PROVIDERS = ["steam", "csfloat"]

# Mapeia plataformas de compra confiaveis para um provider preferencial.
# Se nao houver mapeamento ou o provider nao estiver disponivel, o app usa o fluxo padrao.
PLATFORM_PROVIDER_HINTS = {
    "CSFloat": "csfloat",
    "Steam Market": "steam",
}

# Rate limiting
STEAM_DELAY_SECONDS = 6.0
CSFLOAT_DELAY_SECONDS = 1.5

# Cache TTLs
STEAM_CACHE_TTL_SECONDS = 60 * 60 * 2
CSFLOAT_CACHE_TTL_SECONDS = 60 * 15
FX_CACHE_TTL_SECONDS = 60 * 60 * 12

# Protecao dos providers
STEAM_FAILURE_THRESHOLD = 3
STEAM_COOLDOWN_SECONDS = 60 * 30

# Atualizacao
PRICE_STALE_AFTER_HOURS = 6

# Miniaturas
THUMBNAIL_ALLOWED_SOURCES = {
    "community.cloudflare.steamstatic.com": ("/economy/image/",),
    "community.akamai.steamstatic.com": ("/economy/image/",),
}
THUMBNAIL_TTL_SECONDS = 60 * 60 * 24 * 7
THUMBNAIL_TIMEOUT_SECONDS = 5
THUMBNAIL_MAX_BYTES = 300 * 1024
THUMBNAIL_ERROR_COOLDOWN_SECONDS = 60 * 30
THUMBNAIL_PAGE_SIZE = 24

# Liquidez
LIQUIDITY_MAX_POINTS_PER_SKIN = 240
