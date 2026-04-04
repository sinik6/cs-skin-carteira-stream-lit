"""Servico do modo ativo vs item com busca segura e simulacao local."""

from __future__ import annotations

from statistics import median

from app.config import (
    COMPARISON_COMPARABLES_LIMIT,
    CSFLOAT_COOLDOWN_SECONDS,
    CSFLOAT_DELAY_SECONDS,
    CSFLOAT_FAILURE_THRESHOLD,
)
from app.models import (
    ApiConfig,
    ComparableListing,
    ComparisonSnapshot,
    MarketDetailsSnapshot,
    MarketIntelligenceRecord,
    Skin,
)
from app.services.price_providers.csfloat import CSFloatProvider
from app.services.price_service import PriceService
from app.services.runtime_state import (
    get_provider_state,
    provider_is_in_cooldown,
    record_provider_failure,
    record_provider_success,
    touch_provider_request,
    wait_for_provider_slot,
)
from app.services.storage import salvar_market_snapshot


def _safe_pct(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(numerator / denominator, 4)


def _confidence_label(comparables_count: int, exact_seed_matches: int, average_float_gap: float | None) -> str:
    if comparables_count >= 5 and (exact_seed_matches > 0 or (average_float_gap is not None and average_float_gap <= 0.01)):
        return "Alta"
    if comparables_count >= 3:
        return "Media"
    if comparables_count >= 1:
        return "Baixa"
    return "Sem amostra"


def build_projection(
    snapshot: ComparisonSnapshot,
    purchase_price_brl: float,
    iof_percentual: float,
    market_move_pct: float,
    fx_move_pct: float,
    liquidity_haircut_pct: float,
    exit_fee_pct: float,
    custom_target_pct: float,
) -> dict[str, float]:
    benchmark = snapshot.benchmark_price_brl or snapshot.best_offer_price_brl or snapshot.asset_price_brl
    if benchmark <= 0:
        benchmark = purchase_price_brl

    simulated_reference = benchmark
    simulated_reference *= 1 + (market_move_pct / 100)
    simulated_reference *= 1 + (fx_move_pct / 100)
    simulated_reference *= 1 + (custom_target_pct / 100)

    gross_exit = simulated_reference * (1 - (liquidity_haircut_pct / 100))
    net_exit = gross_exit * (1 - (exit_fee_pct / 100))
    purchase_with_iof = purchase_price_brl * (1 + (iof_percentual / 100))
    pnl = net_exit - purchase_with_iof

    return {
        "reference_price_brl": round(simulated_reference, 2),
        "gross_exit_brl": round(gross_exit, 2),
        "net_exit_brl": round(net_exit, 2),
        "purchase_with_iof_brl": round(purchase_with_iof, 2),
        "pnl_brl": round(pnl, 2),
        "pnl_pct": _safe_pct(pnl, purchase_with_iof),
    }


class ComparisonService:
    """Monta snapshots de comparacao sem polling agressivo."""

    def __init__(self, config: ApiConfig) -> None:
        self._config = config
        self._csfloat = CSFloatProvider(api_key=config.csfloat_api_key)

    def montar_snapshot(
        self,
        skin: Skin,
        considerar_float: bool = True,
        margem_float: float = 0.01,
        considerar_pattern: bool = True,
        limit: int = COMPARISON_COMPARABLES_LIMIT,
    ) -> ComparisonSnapshot:
        market_hash_name = skin.gerar_market_hash_name()
        float_value = skin.float_value if considerar_float else 0.0
        paint_seed = skin.pattern_seed if considerar_pattern else ""

        price_service = PriceService(
            self._config,
            considerar_float=considerar_float,
            margem_float=margem_float,
            considerar_pattern=considerar_pattern,
        )
        price_result = price_service.buscar_preco(skin)
        asset_price = price_result.preco if price_result.sucesso and price_result.preco > 0 else skin.preco_atual
        asset_source = price_result.provider or skin.preco_provider or "Snapshot local"

        base_snapshot = ComparisonSnapshot(
            skin_id=skin.id,
            skin_name=skin.nome,
            market_hash_name=market_hash_name,
            asset_price_brl=asset_price,
            asset_price_source=asset_source,
            source_method=price_result.metodo,
        )

        if not self._csfloat.esta_configurado():
            base_snapshot.note = "CSFloat sem API key. Comparacao fina indisponivel; usando apenas o preco base do ativo."
            base_snapshot.confidence = "Baixa"
            return base_snapshot

        if provider_is_in_cooldown("csfloat"):
            state = get_provider_state("csfloat")
            base_snapshot.cooldown_active = True
            base_snapshot.note = (
                "CSFloat em cooldown por falhas recentes. "
                f"Aguarde cerca de {int(CSFLOAT_COOLDOWN_SECONDS / 60)} min ou use o snapshot atual."
            )
            base_snapshot.confidence = "Baixa"
            if state.last_error:
                base_snapshot.note += f" Ultimo erro: {state.last_error}"
            return base_snapshot

        wait_for_provider_slot("csfloat", CSFLOAT_DELAY_SECONDS)
        touch_provider_request("csfloat")

        try:
            label, listings, _ = self._csfloat.buscar_comparaveis(
                market_hash_name=market_hash_name,
                float_value=float_value,
                margem=margem_float,
                paint_seed=paint_seed,
                limit=limit,
            )
            record_provider_success("csfloat")
        except Exception as exc:
            record_provider_failure(
                "csfloat",
                str(exc),
                failure_threshold=CSFLOAT_FAILURE_THRESHOLD,
                cooldown_seconds=CSFLOAT_COOLDOWN_SECONDS,
            )
            base_snapshot.note = f"Falha ao buscar comparaveis no CSFloat: {exc}"
            base_snapshot.confidence = "Baixa"
            return base_snapshot

        fx_rate = self._csfloat._buscar_cambio()
        comparables = [self._parse_listing(skin, listing, fx_rate) for listing in listings]
        valid_comparables = [item for item in comparables if item.price_brl > 0]

        if not valid_comparables:
            base_snapshot.note = "Nenhum comparavel valido retornou preco utilizavel."
            base_snapshot.confidence = "Baixa"
            return base_snapshot

        prices = [item.price_brl for item in valid_comparables]
        benchmark = round(float(median(prices)), 2)
        best_offer = min(prices)
        exact_seed_matches = sum(1 for item in valid_comparables if item.seed_match)

        float_gaps = [item.float_delta for item in valid_comparables if item.float_delta is not None]
        average_float_gap = round(sum(float_gaps) / len(float_gaps), 5) if float_gaps else None

        spread_benchmark = round(asset_price - benchmark, 2) if asset_price > 0 else 0.0
        spread_best = round(asset_price - best_offer, 2) if asset_price > 0 else 0.0

        snapshot = ComparisonSnapshot(
            skin_id=skin.id,
            skin_name=skin.nome,
            market_hash_name=market_hash_name,
            source_provider="csfloat",
            source_method=label,
            asset_price_brl=asset_price,
            asset_price_source=asset_source,
            benchmark_price_brl=benchmark,
            best_offer_price_brl=best_offer,
            spread_to_benchmark_brl=spread_benchmark,
            spread_to_benchmark_pct=_safe_pct(spread_benchmark, benchmark),
            spread_to_best_offer_brl=spread_best,
            spread_to_best_offer_pct=_safe_pct(spread_best, best_offer),
            comparables_count=len(valid_comparables),
            exact_seed_matches=exact_seed_matches,
            average_float_gap=average_float_gap,
            confidence=_confidence_label(len(valid_comparables), exact_seed_matches, average_float_gap),
            note=(
                "Snapshot sob demanda. Os sliders da simulacao recalculam localmente "
                "e nao disparam novas consultas externas."
            ),
            comparables=valid_comparables,
        )
        salvar_market_snapshot(
            MarketIntelligenceRecord(
                skin_id=skin.id,
                skin_name=skin.nome,
                snapshot=snapshot,
                details=self._build_market_details(listings, valid_comparables, fx_rate),
            )
        )
        return snapshot

    @staticmethod
    def _parse_listing(skin: Skin, listing: dict, fx_rate: float) -> ComparableListing:
        item = listing.get("item") or {}
        seller = listing.get("seller") or {}
        stats = seller.get("statistics") or {}
        float_value = item.get("float_value")
        if not isinstance(float_value, (int, float)):
            float_value = None

        listing_seed = item.get("paint_seed")
        listing_seed_str = str(listing_seed) if listing_seed not in (None, "") else ""
        asset_seed = skin.pattern_seed.strip()

        min_offer_cents = listing.get("min_offer_price", 0)
        min_offer_price_brl = round((min_offer_cents / 100.0) * fx_rate, 2) if min_offer_cents else 0.0
        icon_url = item.get("icon_url")
        image_url = f"https://community.cloudflare.steamstatic.com/economy/image/{icon_url}/160fx160f" if icon_url else ""

        return ComparableListing(
            listing_id=str(listing.get("id", "")),
            market_hash_name=str(item.get("market_hash_name", "") or skin.gerar_market_hash_name()),
            price_brl=CSFloatProvider.listing_price_brl(listing, fx_rate=fx_rate),
            price_usd=CSFloatProvider._listing_price_usd(listing),
            float_value=float_value,
            float_delta=round(abs(float_value - skin.float_value), 5) if float_value is not None and skin.float_value > 0 else None,
            paint_seed=listing_seed_str,
            seed_match=bool(asset_seed and asset_seed == listing_seed_str),
            seller_name=str(seller.get("username", "")),
            seller_trade_count=int(stats.get("total_trades", 0) or 0),
            seller_verified_trades=int(stats.get("total_verified_trades", 0) or 0),
            min_offer_price_brl=min_offer_price_brl,
            watchers=int(listing.get("watchers", 0) or 0),
            inspect_link=str(item.get("inspect_link", "")),
            image_url=image_url,
        )

    @staticmethod
    def _build_market_details(
        listings: list[dict],
        comparables: list[ComparableListing],
        fx_rate: float,
    ) -> MarketDetailsSnapshot:
        if not listings:
            return MarketDetailsSnapshot()

        item = (listings[0].get("item") or {})
        scm = item.get("scm") or {}
        seller_trades = [entry.seller_trade_count for entry in comparables if entry.seller_trade_count > 0]
        seller_verified = [entry.seller_verified_trades for entry in comparables if entry.seller_verified_trades > 0]

        rarity = item.get("rarity")
        if isinstance(rarity, dict):
            rarity_name = str(rarity.get("name", ""))
        else:
            rarity_name = str(rarity or "")

        watchers_total = sum(entry.watchers for entry in comparables)
        scm_price_cents = scm.get("price", 0) or 0

        return MarketDetailsSnapshot(
            item_name=str(item.get("item_name", "")),
            wear_name=str(item.get("wear_name", "")),
            collection=str(item.get("collection", "")),
            description=str(item.get("description", "")),
            rarity=rarity_name,
            asset_id=str(item.get("asset_id", "")),
            paint_index=int(item.get("paint_index", 0) or 0),
            paint_seed=str(item.get("paint_seed", "")) if item.get("paint_seed") not in (None, "") else "",
            tradable=int(item.get("tradable", 0) or 0),
            has_screenshot=bool(item.get("has_screenshot", False)),
            sticker_count=len(item.get("stickers") or []),
            scm_price_brl=round((scm_price_cents / 100.0) * fx_rate, 2) if scm_price_cents else 0.0,
            scm_volume=int(scm.get("volume", 0) or 0),
            watchers_total=watchers_total,
            avg_seller_trades=round(sum(seller_trades) / len(seller_trades), 2) if seller_trades else 0.0,
            avg_seller_verified=round(sum(seller_verified) / len(seller_verified), 2) if seller_verified else 0.0,
        )
