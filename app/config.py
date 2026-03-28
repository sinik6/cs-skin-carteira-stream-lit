"""Constantes e configurações da aplicação."""

from pathlib import Path

APP_NAME = "CS2 Skin Tracker"
APP_ICON = "🎮"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path("/app/data") if Path("/app").exists() else BASE_DIR / "data"
DATA_FILE = DATA_DIR / "skins.json"
PRICE_CACHE_FILE = DATA_DIR / "price_cache.json"
PROVIDER_STATE_FILE = DATA_DIR / "provider_state.json"

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
