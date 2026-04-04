"""Interface base para providers de ativos."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from app.models import AssetSearchResult, WeeklyPricePoint


@dataclass
class AssetQuoteResult:
    """Resultado simplificado de quote de ativo."""

    symbol: str
    price: float
    currency: str = "USD"
    exchange: str = ""
    provider: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.now().isoformat())


class AssetProvider(ABC):
    """Contrato comum para busca e histórico de ativos."""

    provider_name: str = ""

    @abstractmethod
    def esta_configurado(self) -> bool:
        """Retorna se o provider está pronto para uso."""

    @abstractmethod
    def search_assets(self, query: str) -> list[AssetSearchResult]:
        """Busca ativos por símbolo ou nome."""

    @abstractmethod
    def get_weekly_series(self, symbol: str, outputsize: int = 52) -> list[WeeklyPricePoint]:
        """Busca série semanal normalizada em moeda nativa."""

    @abstractmethod
    def get_quote(self, symbol: str) -> AssetQuoteResult | None:
        """Busca um quote atual simplificado."""
