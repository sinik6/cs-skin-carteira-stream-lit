"""Modelos de dados da aplicação CS2 Skin Tracker."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field


class TipoItem(StrEnum):
    ARMA = "Arma"
    FACA = "Faca"
    LUVA = "Luva"
    ADESIVO = "Adesivo"
    AGENTE = "Agente"
    CHARM = "Charm"
    GRAFITE = "Grafite"
    PATCH = "Patch"
    MUSIC_KIT = "Music Kit"
    CAIXA = "Caixa"
    OUTRO = "Outro"


class Desgaste(StrEnum):
    FN = "Factory New (FN)"
    MW = "Minimal Wear (MW)"
    FT = "Field-Tested (FT)"
    WW = "Well-Worn (WW)"
    BS = "Battle-Scarred (BS)"
    NA = "N/A"


DESGASTE_STEAM_MAP: dict[str, str] = {
    "Factory New (FN)": "Factory New",
    "Minimal Wear (MW)": "Minimal Wear",
    "Field-Tested (FT)": "Field-Tested",
    "Well-Worn (WW)": "Well-Worn",
    "Battle-Scarred (BS)": "Battle-Scarred",
}


class Skin(BaseModel):
    """Representa uma skin comprada pelo usuário."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    nome: str
    tipo: str = TipoItem.ARMA
    desgaste: str = Desgaste.NA
    float_value: float = 0.0
    stattrak: str = "Não"
    pattern_seed: str = ""
    plataforma: str = ""
    preco_compra: float = 0.0
    iof_aplicavel: bool = False
    preco_atual: float = 0.0
    preco_provider: str = ""
    preco_metodo: str = ""
    preco_amostra: int = 0
    preco_confianca: str = ""
    preco_cache_hit: bool = False
    preco_stale: bool = False
    preco_atualizado_em: str = ""
    imagem_url: str = ""
    notas: str = ""
    market_hash_name: str = ""
    criado_em: str = Field(default_factory=lambda: datetime.now().isoformat())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_com_iof(self) -> float:
        return self.total_com_iof_com_taxa()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lucro(self) -> float:
        return self.lucro_com_taxa()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def variacao_pct(self) -> float:
        return self.variacao_pct_com_taxa()

    def total_com_iof_com_taxa(self, iof_percentual: float = 6.38) -> float:
        if self.iof_aplicavel and self.preco_compra > 0:
            return round(self.preco_compra * (1 + (iof_percentual / 100)), 2)
        return self.preco_compra

    def lucro_com_taxa(self, iof_percentual: float = 6.38) -> float:
        total_com_iof = self.total_com_iof_com_taxa(iof_percentual)
        if self.preco_atual > 0 and total_com_iof > 0:
            return round(self.preco_atual - total_com_iof, 2)
        if self.preco_atual > 0 and total_com_iof == 0:
            return self.preco_atual
        return 0.0

    def variacao_pct_com_taxa(self, iof_percentual: float = 6.38) -> float:
        total_com_iof = self.total_com_iof_com_taxa(iof_percentual)
        if total_com_iof > 0 and self.preco_atual > 0:
            return round((self.preco_atual - total_com_iof) / total_com_iof, 4)
        return 0.0

    def status_preco(self) -> str:
        if self.preco_atual <= 0:
            return "Sem preco"
        if self.preco_stale:
            return "Cache expirado"
        if self.preco_cache_hit:
            return "Cache"
        return "Ao vivo"

    def gerar_market_hash_name(self) -> str:
        """Gera o market_hash_name para busca de preço nas APIs."""
        if self.market_hash_name:
            return self.market_hash_name

        nome_base = re.sub(r"\s*\([^)]*\)\s*$", "", self.nome).strip()

        if self.tipo == TipoItem.ADESIVO:
            if not nome_base.lower().startswith("sticker"):
                return f"Sticker | {nome_base}"
            return nome_base

        if self.tipo == TipoItem.CHARM:
            if not nome_base.lower().startswith("charm"):
                return f"Charm | {nome_base}"
            return nome_base

        desgaste_steam = DESGASTE_STEAM_MAP.get(self.desgaste, "")
        if desgaste_steam:
            prefixo = "StatTrak™ " if self.stattrak == "Sim" else ""
            return f"{prefixo}{nome_base} ({desgaste_steam})"

        return nome_base


class ApiConfig(BaseModel):
    """Configurações de API keys."""

    csfloat_api_key: str = ""
    steam_enabled: bool = True
    iof_percentual: float = 6.38
    provider_preferido: str = "steam"


class PriceCacheEntry(BaseModel):
    """Entrada persistida de cache de preÃ§o ou cÃ¢mbio."""

    key: str
    preco: float
    moeda: str = "BRL"
    provider: str = ""
    metodo: str = ""
    amostra: int = 0
    confianca: str = ""
    imagem_url: str = ""
    ttl_seconds: int
    atualizado_em_ts: float


class ProviderState(BaseModel):
    """Estado persistido para rate limit e cooldown."""

    last_request_ts: float = 0.0
    last_success_ts: float = 0.0
    consecutive_failures: int = 0
    cooldown_until_ts: float = 0.0
    last_error: str = ""


class ComparableListing(BaseModel):
    """Listing comparavel usado no modo ativo vs item."""

    listing_id: str = ""
    market_hash_name: str = ""
    price_brl: float = 0.0
    price_usd: float = 0.0
    float_value: float | None = None
    float_delta: float | None = None
    paint_seed: str = ""
    seed_match: bool = False
    seller_name: str = ""
    seller_trade_count: int = 0
    seller_verified_trades: int = 0
    min_offer_price_brl: float = 0.0
    watchers: int = 0
    inspect_link: str = ""
    image_url: str = ""


class ComparisonSnapshot(BaseModel):
    """Snapshot seguro de comparacao salvo em sessao."""

    skin_id: str
    skin_name: str
    market_hash_name: str
    fetched_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    source_provider: str = "csfloat"
    source_method: str = ""
    asset_price_brl: float = 0.0
    asset_price_source: str = ""
    benchmark_price_brl: float = 0.0
    best_offer_price_brl: float = 0.0
    spread_to_benchmark_brl: float = 0.0
    spread_to_benchmark_pct: float = 0.0
    spread_to_best_offer_brl: float = 0.0
    spread_to_best_offer_pct: float = 0.0
    comparables_count: int = 0
    exact_seed_matches: int = 0
    average_float_gap: float | None = None
    confidence: str = ""
    cooldown_active: bool = False
    note: str = ""
    comparables: list[ComparableListing] = Field(default_factory=list)


class MarketDetailsSnapshot(BaseModel):
    """Campos adicionais de mercado persistidos localmente."""

    item_name: str = ""
    wear_name: str = ""
    collection: str = ""
    description: str = ""
    rarity: str = ""
    asset_id: str = ""
    paint_index: int = 0
    paint_seed: str = ""
    tradable: int = 0
    has_screenshot: bool = False
    sticker_count: int = 0
    scm_price_brl: float = 0.0
    scm_volume: int = 0
    watchers_total: int = 0
    avg_seller_trades: float = 0.0
    avg_seller_verified: float = 0.0


class MarketIntelligenceRecord(BaseModel):
    """Historico local de inteligencia de mercado por skin."""

    skin_id: str
    skin_name: str
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    snapshot: ComparisonSnapshot
    details: MarketDetailsSnapshot = Field(default_factory=MarketDetailsSnapshot)
    history: list[ComparisonSnapshot] = Field(default_factory=list)


class AppData(BaseModel):
    """Dados completos da aplicação."""

    skins: list[Skin] = Field(default_factory=list)
    config: ApiConfig = Field(default_factory=ApiConfig)
