"""Pagina Comparador - ativo vs item com snapshot seguro e simulacao local."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import streamlit as st

from app.config import COMPARISON_DEFAULT_FLOAT_MARGIN
from app.models import ComparableListing, ComparisonSnapshot, MarketInstrument, MarketIntelligenceRecord, Skin, WeeklyPricePoint
from app.services.catalog_service import hydrate_app_data_from_catalog
from app.services import db
from app.services.asset_service import AssetService
from app.services.comparison_service import ComparisonService, build_projection
from app.services.runtime_state import get_provider_state, provider_is_in_cooldown
from app.services.storage import carregar_dados, obter_market_snapshot, salvar_dados
from app.services.thumbnail_service import ThumbnailService

THUMBNAIL_SERVICE = ThumbnailService()
SNAPSHOT_SESSION_KEY = "comparison_snapshot"
LISTING_SESSION_KEY = "comparison_listing_id"
ASSET_SESSION_KEY = "comparison_asset_id"


def _ensure_state() -> None:
    st.session_state.setdefault(SNAPSHOT_SESSION_KEY, {})
    st.session_state.setdefault(LISTING_SESSION_KEY, "")
    st.session_state.setdefault(ASSET_SESSION_KEY, "")


def _load_snapshot() -> ComparisonSnapshot | None:
    raw = st.session_state.get(SNAPSHOT_SESSION_KEY) or {}
    if not raw:
        return None
    return ComparisonSnapshot.model_validate(raw)


def _store_snapshot(snapshot: ComparisonSnapshot) -> None:
    st.session_state[SNAPSHOT_SESSION_KEY] = snapshot.model_dump()
    if snapshot.comparables:
        st.session_state[LISTING_SESSION_KEY] = snapshot.comparables[0].listing_id


def _thumbnail_path(image_url: str) -> str | None:
    if not image_url:
        return None
    local_path = THUMBNAIL_SERVICE.get_local_path(image_url)
    return str(local_path) if local_path else None


def _skin_thumbnail(skin: Skin) -> str | None:
    return _thumbnail_path(skin.imagem_url)


def _safe_pct(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(numerator / denominator, 4)


def normalize_weekly_points(points: list[WeeklyPricePoint]) -> list[WeeklyPricePoint]:
    deduped: dict[str, WeeklyPricePoint] = {}
    for point in points:
        deduped[point.week_end_date] = point
    return [deduped[key] for key in sorted(deduped)]


def summarize_weekly_points(points: list[WeeklyPricePoint]) -> dict[str, object]:
    normalized = normalize_weekly_points(points)
    latest = normalized[-1] if normalized else None
    previous = normalized[-2] if len(normalized) >= 2 else None
    delta_value = 0.0
    delta_pct = 0.0
    if latest and previous:
        delta_value = round(latest.close_native - previous.close_native, 2)
        delta_pct = _safe_pct(delta_value, previous.close_native)

    return {
        "count": len(normalized),
        "latest": latest,
        "previous": previous,
        "delta_value": delta_value,
        "delta_pct": delta_pct,
        "sparkline": [point.close_native for point in normalized[-12:]],
        "first": normalized[0] if normalized else None,
        "last_date": latest.week_end_date if latest else "",
    }


def summarize_skin_history(snapshot: ComparisonSnapshot, record: MarketIntelligenceRecord | None) -> dict[str, object]:
    entries = list(reversed(record.history[:12])) if record and record.history else []
    if not entries:
        entries = [snapshot]

    values: list[float] = []
    labels: list[str] = []
    for entry in entries:
        reference_price = entry.benchmark_price_brl or entry.best_offer_price_brl or entry.asset_price_brl
        if reference_price <= 0:
            continue
        values.append(reference_price)
        labels.append(_format_dt(entry.fetched_at))

    current = values[-1] if values else snapshot.benchmark_price_brl or snapshot.best_offer_price_brl or snapshot.asset_price_brl
    previous = values[-2] if len(values) >= 2 else 0.0
    delta_value = round(current - previous, 2) if previous else 0.0
    delta_pct = _safe_pct(delta_value, previous) if previous else 0.0

    return {
        "count": len(values),
        "current": current,
        "previous": previous,
        "delta_value": delta_value,
        "delta_pct": delta_pct,
        "sparkline": values[-12:],
        "labels": labels[-12:],
        "latest_label": labels[-1] if labels else "",
    }


def _build_base100_series(values: list[float], label: str) -> pd.DataFrame:
    usable = [value for value in values if value > 0]
    if len(usable) < 2:
        return pd.DataFrame()
    base = usable[0]
    return pd.DataFrame(
        {
            "ponto": list(range(1, len(usable) + 1)),
            label: [round((value / base) * 100, 2) for value in usable],
        }
    ).set_index("ponto")


def _asset_option_label(asset: MarketInstrument) -> str:
    exchange = f" | {asset.exchange}" if asset.exchange else ""
    return f"{asset.display_name} ({asset.symbol}) | {asset.kind.upper()}{exchange}"


def _effective_skin_reference(snapshot: ComparisonSnapshot, skin: Skin) -> tuple[float, str]:
    if snapshot.benchmark_price_brl > 0:
        return snapshot.benchmark_price_brl, "Benchmark de mercado"
    if snapshot.best_offer_price_brl > 0:
        return snapshot.best_offer_price_brl, "Melhor listing"
    if snapshot.asset_price_brl > 0:
        return snapshot.asset_price_brl, "Preco atual da skin"
    if skin.preco_atual > 0:
        return skin.preco_atual, "Preco salvo da skin"
    if skin.preco_compra > 0:
        return skin.preco_compra, "Preco de compra"
    return 0.0, "Sem referencia"


def _asset_display_value(asset: MarketInstrument, asset_context: dict[str, object]) -> tuple[str, str | None]:
    asset_summary = asset_context["summary"]
    asset_latest = asset_summary["latest"]
    if asset_latest:
        delta = f"{asset_summary['delta_pct']:+.1%}" if asset_summary["count"] >= 2 else None
        return f"R$ {asset_latest.close_brl:,.2f}", delta
    return "-", None


def _build_asset_same_capital_view(asset_context: dict[str, object], base_capital_brl: float) -> dict[str, float]:
    summary = asset_context["summary"]
    first_point = summary["first"]
    latest = summary["latest"]
    if not first_point or not latest or base_capital_brl <= 0 or first_point.close_brl <= 0:
        return {
            "units": 0.0,
            "initial_value_brl": 0.0,
            "current_value_brl": 0.0,
            "pnl_brl": 0.0,
            "pnl_pct": 0.0,
        }

    units = base_capital_brl / first_point.close_brl
    current_value_brl = round(units * latest.close_brl, 2)
    pnl_brl = round(current_value_brl - base_capital_brl, 2)
    return {
        "units": round(units, 4),
        "initial_value_brl": round(base_capital_brl, 2),
        "current_value_brl": current_value_brl,
        "pnl_brl": pnl_brl,
        "pnl_pct": _safe_pct(pnl_brl, base_capital_brl),
    }


def _load_asset_context(asset: MarketInstrument, config, refresh_series: bool = False) -> dict[str, object]:
    service = AssetService(config)
    refreshed = False
    if refresh_series and (config.twelvedata_api_key or config.alphavantage_api_key):
        service.fetch_weekly_series(asset, outputsize=12)
        refreshed = True

    points = db.get_weekly_prices(asset.id)
    metadata = db.get_instrument_metadata(asset.id)
    metadata_payload = {}
    if metadata and metadata.payload_json:
        try:
            metadata_payload = json.loads(metadata.payload_json)
        except json.JSONDecodeError:
            metadata_payload = {}

    summary = summarize_weekly_points(points)
    latest = summary["latest"]
    direct_value_supported = bool(latest and latest.close_brl > 0)
    source_label = "catalogo local"
    if latest:
        source_label = "cache local semanal" if latest.provider == "seed_local" else latest.provider

    return {
        "asset": asset,
        "metadata": metadata_payload,
        "summary": summary,
        "points": normalize_weekly_points(points),
        "refreshed": refreshed,
        "direct_value_supported": direct_value_supported,
        "source_label": source_label,
    }


def _metadata_badges(metadata: dict[str, object]) -> list[str]:
    badges = [
        str(metadata.get("sector", "")),
        str(metadata.get("risk_profile", "")),
        str(metadata.get("benchmark_role", "")),
    ]
    return [item for item in badges if item and item != "-"]


def _render_chip_row(chips: list[str]) -> None:
    if not chips:
        return
    st.caption(" | ".join(chips))


def _render_key_value_grid(items: list[tuple[str, str]], columns: int = 3) -> None:
    filtered = [(label, value) for label, value in items if value not in {"", None}]
    if not filtered:
        return
    cols = st.columns(columns)
    for index, (label, value) in enumerate(filtered):
        with cols[index % columns]:
            st.caption(label)
            st.markdown(f"**{value}**")


def _render_panel_header(title: str, subtitle: str = "") -> None:
    st.markdown(f"**{title}**")
    if subtitle:
        st.caption(subtitle)


def _render_skin_panel(skin: Skin, snapshot: ComparisonSnapshot, iof_percentual: float) -> None:
    reference_value, reference_label = _effective_skin_reference(snapshot, skin)
    with st.container(border=True):
        top_left, top_right = st.columns([0.26, 0.74])
        with top_left:
            thumb = _skin_thumbnail(skin)
            if thumb:
                st.image(thumb, use_container_width=True)
            else:
                st.metric("Skin", skin.tipo, border=True)
        with top_right:
            _render_panel_header("Skin na carteira", f"{skin.nome} | {skin.desgaste}")
            _render_chip_row(
                [
                    f"Provider: {snapshot.asset_price_source or 'local'}",
                    f"Status: {skin.status_preco()}",
                    f"Pattern: {skin.pattern_seed or 'n/a'}",
                    f"Float: {f'{skin.float_value:.5f}' if skin.float_value > 0 else 'n/a'}",
                ]
            )
        _render_key_value_grid(
            [
                ("Compra", f"R$ {skin.preco_compra:.2f}"),
                ("Compra + IOF", f"R$ {skin.total_com_iof_com_taxa(iof_percentual):.2f}"),
                ("Preco atual", f"R$ {snapshot.asset_price_brl:.2f}"),
                ("Referencia", f"R$ {reference_value:.2f}"),
                ("Leitura", reference_label),
                ("Plataforma", skin.plataforma or "-"),
            ],
            columns=3,
        )


def _render_asset_panel(asset: MarketInstrument, asset_context: dict[str, object], skin: Skin) -> None:
    metadata = asset_context["metadata"]
    summary = asset_context["summary"]
    latest = summary["latest"]
    previous = summary["previous"]
    same_capital = _build_asset_same_capital_view(asset_context, skin.total_com_iof_com_taxa())
    with st.container(border=True):
        _render_panel_header("Ativo financeiro", f"{asset.display_name} | {asset.symbol}")
        _render_chip_row(
            [
                f"Classe: {metadata.get('class_label', asset.kind.upper())}",
                f"Bolsa: {asset.exchange or '-'}",
                f"Moeda: {asset.currency}",
                * _metadata_badges(metadata),
            ]
        )
        _render_key_value_grid(
            [
                ("Ultimo dado", f"{asset.currency} {latest.close_native:.2f}" if latest else f"{asset.symbol} | {asset.currency}"),
                ("Valor em BRL", f"R$ {latest.close_brl:.2f}" if latest else "-"),
                ("Data ref.", latest.week_end_date if latest else "catalogo local"),
                ("Serie salva", f"{summary['count']} semanas"),
                ("Provider", asset.provider_primary or "-"),
                ("Cotas mesmo capital", f"{same_capital['units']:.4f}" if same_capital["units"] > 0 else "indisponivel"),
            ],
            columns=3,
        )
        if latest and previous:
            st.caption(
                f"Variacao semanal atual: {summary['delta_value']:+.2f} {asset.currency} ({summary['delta_pct']:+.1%}) | "
                f"Mesmo capital hoje: R$ {same_capital['current_value_brl']:.2f} ({same_capital['pnl_pct']:+.1%})"
            )
        if metadata.get("notes"):
            st.caption(str(metadata["notes"]))


def _render_reference_panel(listing: ComparableListing | None, snapshot: ComparisonSnapshot) -> None:
    with st.container(border=True):
        _render_panel_header("Referencia de mercado", "Listing comparavel ou benchmark seguro da skin")
        if not listing:
            st.info("Sem listing comparavel no snapshot atual. O resumo usa o preco atual da skin como fallback seguro.")
            return
        top_left, top_right = st.columns([0.26, 0.74])
        with top_left:
            thumb = _thumbnail_path(listing.image_url)
            if thumb:
                st.image(thumb, use_container_width=True)
            else:
                st.metric("Listing", listing.listing_id, border=True)
        with top_right:
            st.markdown(f"**{listing.market_hash_name}**")
            _render_chip_row(
                [
                    f"Listing #{listing.listing_id}",
                    f"Seed match: {'Sim' if listing.seed_match else 'Nao'}",
                    f"Watchers: {listing.watchers}",
                    f"Seller: {listing.seller_name or '-'}",
                ]
            )
        _render_key_value_grid(
            [
                ("Preco", f"R$ {listing.price_brl:.2f}"),
                ("Oferta minima", f"R$ {listing.min_offer_price_brl:.2f}"),
                ("Float", f"{listing.float_value:.6f}" if listing.float_value is not None else "-"),
                ("Gap float", f"{listing.float_delta:.5f}" if listing.float_delta is not None else "-"),
                ("Trades", str(listing.seller_trade_count)),
                ("Verified", str(listing.seller_verified_trades)),
            ],
            columns=3,
        )


def _hero(total_skins: int) -> None:
    state = get_provider_state("csfloat")
    ultimo_sucesso = "-"
    if state.last_success_ts:
        ultimo_sucesso = datetime.fromtimestamp(state.last_success_ts).strftime("%d/%m %H:%M")

    st.markdown(
        f"""
        <div class="app-hero">
            <div class="app-hero-eyebrow">Comparador</div>
            <div class="app-hero-title">Modo Ativo vs Item</div>
            <div class="app-hero-copy">
                Busca comparaveis sob demanda, respeita cooldown e usa simulacao local para recalcular cenarios em tempo real sem polling agressivo.
            </div>
            <div class="app-chip-row">
                <span class="app-chip">Skins na carteira: {total_skins}</span>
                <span class="app-chip">CSFloat cooldown: {"Ativo" if provider_is_in_cooldown("csfloat") else "Livre"}</span>
                <span class="app-chip">Ultimo sucesso: {ultimo_sucesso}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_provider_health() -> None:
    state = get_provider_state("csfloat")
    with st.expander("Saude do provider e protecoes", expanded=False):
        st.markdown("**Saude do provider**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Falhas seguidas", state.consecutive_failures)
        c2.metric("Cooldown", "Ativo" if provider_is_in_cooldown("csfloat") else "Livre")
        c3.metric(
            "Ultima req.",
            datetime.fromtimestamp(state.last_request_ts).strftime("%H:%M:%S") if state.last_request_ts else "-",
        )
        c4.metric(
            "Ultimo sucesso",
            datetime.fromtimestamp(state.last_success_ts).strftime("%H:%M:%S") if state.last_success_ts else "-",
        )
        if state.last_error:
            st.caption(f"Ultimo erro observado: {state.last_error}")
        st.caption("A pagina so consulta o provider quando voce envia o formulario. Os controles de simulacao sao locais.")


def _render_controls(skins: list[Skin], config) -> tuple[Skin | None, MarketInstrument | None, bool]:
    if not skins:
        st.info("Nenhuma skin cadastrada para comparar.")
        return None, None, False

    skin_options = {f"{skin.nome} | {skin.desgaste} | compra R$ {skin.preco_compra:.2f}": skin for skin in skins}
    assets = AssetService(config).list_catalog_assets()
    if not assets:
        st.info("Nenhum ativo salvo no catalogo local ainda.")
        return None, None, False
    asset_options = {_asset_option_label(asset): asset for asset in assets}
    default_asset_id = st.session_state.get(ASSET_SESSION_KEY)
    default_asset_index = 0
    for index, asset in enumerate(assets):
        if asset.id == default_asset_id:
            default_asset_index = index
            break
    has_asset_provider = bool(config.twelvedata_api_key or config.alphavantage_api_key)

    with st.form("comparison_fetch_form", border=False):
        selected_skin_label = st.selectbox("Skin da carteira", list(skin_options.keys()))
        selected_asset_label = st.selectbox(
            "Ativo para comparar",
            list(asset_options.keys()),
            index=default_asset_index,
            help="Escolha o ativo financeiro que sera usado como referencia da comparacao com a skin.",
        )
        st.caption("A comparacao so e montada quando voce escolhe os dois lados: a skin e o ativo de referencia.")

        c3, c4, c5 = st.columns(3)
        with c3:
            considerar_float = st.toggle("Usar float", value=True)
        with c4:
            considerar_pattern = st.toggle("Usar pattern", value=True)
        with c5:
            margem_float = st.slider(
                "Margem do float",
                min_value=0.005,
                max_value=0.050,
                value=COMPARISON_DEFAULT_FLOAT_MARGIN,
                step=0.005,
                format="%.3f",
            )
        c6, c7 = st.columns([1.4, 1.6])
        with c6:
            atualizar_ativo = st.toggle(
                "Atualizar serie semanal do ativo",
                value=False,
                disabled=not has_asset_provider,
                help="So consulta provider externo do ativo quando voce envia o formulario.",
            )
        with c7:
            st.text_input(
                "Fluxo seguro",
                value="CSFloat sob demanda + ativo local/weekly sob submit",
                disabled=True,
            )

        submitted = st.form_submit_button("Montar comparacao segura", type="primary", use_container_width=True)

    if submitted:
        service = ComparisonService(config)
        snapshot = service.montar_snapshot(
            skin_options[selected_skin_label],
            considerar_float=considerar_float,
            margem_float=margem_float,
            considerar_pattern=considerar_pattern,
        )
        _store_snapshot(snapshot)
        selected_asset = asset_options[selected_asset_label]
        st.session_state[ASSET_SESSION_KEY] = selected_asset.id
        _load_asset_context(selected_asset, config, refresh_series=atualizar_ativo)
        return skin_options[selected_skin_label], selected_asset, True

    return skin_options[selected_skin_label], asset_options[selected_asset_label], False


def _render_snapshot_overview(snapshot: ComparisonSnapshot) -> None:
    benchmark_value = snapshot.benchmark_price_brl or snapshot.asset_price_brl
    benchmark_delta = f"{snapshot.spread_to_benchmark_pct:+.1%}" if snapshot.benchmark_price_brl > 0 else None
    best_listing_value = snapshot.best_offer_price_brl or snapshot.asset_price_brl
    best_listing_delta = f"{snapshot.spread_to_best_offer_pct:+.1%}" if snapshot.best_offer_price_brl > 0 else None

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Preco da skin", f"R$ {snapshot.asset_price_brl:,.2f}", border=True)
    c2.metric("Benchmark", f"R$ {benchmark_value:,.2f}", delta=benchmark_delta, border=True)
    c3.metric("Melhor listing", f"R$ {best_listing_value:,.2f}", delta=best_listing_delta, border=True)
    c4.metric("Comparaveis", snapshot.comparables_count, border=True)
    c5.metric("Seed match", snapshot.exact_seed_matches, border=True)

    st.caption(
        f"Snapshot de {snapshot.source_provider.upper()} via {snapshot.source_method or 'comparacao de mercado'} "
        f"em {_format_dt(snapshot.fetched_at)}."
    )
    st.caption(
        f"Leitura atual: confianca {snapshot.confidence.lower() or '-'} | "
        f"{'sem comparaveis de mercado' if snapshot.comparables_count == 0 else 'comparaveis disponiveis'}"
    )
    if snapshot.note:
        st.info(snapshot.note)


def _render_comparison_summary(
    skin: Skin,
    asset: MarketInstrument,
    snapshot: ComparisonSnapshot,
    asset_context: dict[str, object],
    skin_history_summary: dict[str, object],
) -> None:
    asset_summary = asset_context["summary"]
    reference_value, reference_label = _effective_skin_reference(snapshot, skin)
    skin_position_value = snapshot.asset_price_brl
    skin_pnl_brl = round(skin_position_value - skin.total_com_iof_com_taxa(), 2) if skin_position_value > 0 else 0.0
    skin_pnl_pct = _safe_pct(skin_pnl_brl, skin.total_com_iof_com_taxa()) if skin.total_com_iof_com_taxa() > 0 else 0.0
    asset_same_capital = _build_asset_same_capital_view(asset_context, skin.total_com_iof_com_taxa())
    asset_price_label, asset_delta_label = _asset_display_value(asset, asset_context)
    has_asset_series = asset_summary["count"] > 0

    with st.container(border=True):
        st.markdown("**Comparacao consolidada**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Skin hoje",
            f"R$ {skin_position_value:,.2f}",
            delta=f"{skin_pnl_pct:+.1%}" if skin_position_value > 0 else None,
            border=True,
        )
        c2.metric(
            "Ativo em BRL",
            asset_price_label,
            delta=asset_delta_label if has_asset_series else None,
            border=True,
        )
        c3.metric(
            "Mesmo capital no ativo",
            f"R$ {asset_same_capital['current_value_brl']:,.2f}" if asset_same_capital["current_value_brl"] > 0 else "-",
            delta=f"{asset_same_capital['pnl_pct']:+.1%}" if asset_same_capital["current_value_brl"] > 0 else None,
            border=True,
        )
        c4.metric(
            "Semanas do ativo",
            asset_summary["count"],
            border=True,
        )
        st.caption(
            f"Base da skin: {reference_label} | lucro atual da skin: R$ {skin_pnl_brl:.2f} | "
            f"fonte do ativo: {asset_context['source_label']}"
        )

        if asset_context["refreshed"]:
            st.caption("A serie semanal do ativo foi atualizada neste envio e persistida localmente.")
        elif has_asset_series:
            st.caption("A serie semanal do ativo foi carregada do banco local para evitar consultas repetidas.")
        else:
            st.caption("Ainda nao ha serie semanal salva para este ativo. O painel usa o catalogo local e os metadados persistidos para manter a comparacao preenchida.")

        if not asset_context["direct_value_supported"]:
            st.info(
                "Ativos fora de BRL ainda aparecem na moeda nativa. A comparacao percentual funciona melhor agora; "
                "a conversao semanal para BRL entra na proxima camada de dados."
            )


def _render_market_details(record: MarketIntelligenceRecord | None) -> None:
    if not record:
        return

    details = record.details
    if not any(
        [
            details.item_name,
            details.collection,
            details.description,
            details.sticker_count,
            details.scm_volume,
            details.watchers_total,
        ]
    ):
        return

    st.markdown("### Inteligencia local salva")
    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("Colecao", details.collection or "-")
    d2.metric("Raridade", details.rarity or "-")
    d3.metric("SCM ref.", f"R$ {details.scm_price_brl:,.2f}" if details.scm_price_brl > 0 else "-")
    d4.metric("SCM volume", details.scm_volume)
    d5.metric("Watchers", details.watchers_total)

    with st.container(border=True):
        st.write(f"Item: **{details.item_name or '-'}**")
        st.write(f"Wear name: **{details.wear_name or '-'}**")
        st.write(f"Asset ID: **{details.asset_id or '-'}**")
        st.write(f"Paint index: **{details.paint_index or '-'}**")
        st.write(f"Paint seed: **{details.paint_seed or '-'}**")
        st.write(f"Stickers detectados: **{details.sticker_count}**")
        st.write(f"Screenshot disponivel: **{'Sim' if details.has_screenshot else 'Nao'}**")
        st.write(f"Media trades vendedor: **{details.avg_seller_trades:.2f}**")
        st.write(f"Media verified trades: **{details.avg_seller_verified:.2f}**")
        if details.description:
            st.caption(details.description)


def _render_local_history(record: MarketIntelligenceRecord | None) -> None:
    if not record or not record.history:
        return

    st.markdown("### Historico local de snapshots")
    history_df = pd.DataFrame(
        [
            {
                "capturado_em": _format_dt(entry.fetched_at),
                "benchmark": entry.benchmark_price_brl,
                "melhor_listing": entry.best_offer_price_brl,
                "ativo": entry.asset_price_brl,
                "amostra": entry.comparables_count,
                "confianca": entry.confidence,
                "metodo": entry.source_method,
            }
            for entry in record.history[:8]
        ]
    )
    st.dataframe(
        history_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "benchmark": st.column_config.NumberColumn("Benchmark", format="R$ %.2f"),
            "melhor_listing": st.column_config.NumberColumn("Melhor listing", format="R$ %.2f"),
            "ativo": st.column_config.NumberColumn("Ativo", format="R$ %.2f"),
        },
    )


def _render_trend_section(snapshot: ComparisonSnapshot, asset: MarketInstrument, asset_context: dict[str, object], skin_summary: dict[str, object]) -> None:
    st.markdown("### Tendencia relativa")
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**Skin - historico local**")
            if skin_summary["count"] >= 2:
                skin_df = pd.DataFrame(
                    {
                        "captura": list(range(1, len(skin_summary["sparkline"]) + 1)),
                        "benchmark_brl": skin_summary["sparkline"],
                    }
                ).set_index("captura")
                st.line_chart(skin_df, use_container_width=True)
                st.caption("Sequencia baseada nos snapshots salvos localmente para esta skin.")
            else:
                st.caption("Ainda nao ha pontos suficientes da skin para desenhar tendencia local.")

    with right:
        with st.container(border=True):
            st.markdown(f"**Ativo - {asset.symbol}**")
            asset_points = asset_context["points"]
            if asset_points:
                asset_df = pd.DataFrame(
                    {
                        "semana": [point.week_end_date for point in asset_points[-12:]],
                        "close_native": [point.close_native for point in asset_points[-12:]],
                    }
                ).set_index("semana")
                st.line_chart(asset_df, use_container_width=True)
                st.caption("Serie semanal persistida localmente no banco para evitar consultas repetidas.")
            else:
                st.caption("Ainda nao ha serie semanal salva para este ativo.")

    skin_index = _build_base100_series(skin_summary["sparkline"], "skin_base100")
    asset_index = _build_base100_series(asset_context["summary"]["sparkline"], "ativo_base100")
    if not skin_index.empty and not asset_index.empty:
        merged = pd.concat([skin_index, asset_index], axis=1)
        st.markdown("**Base 100 dos pontos disponiveis**")
        st.line_chart(merged, use_container_width=True)
        st.caption("Essa visao compara a direcao do movimento entre a skin e o ativo, mesmo quando as moedas diferem.")


def _render_asset_catalog(config) -> None:
    service = AssetService(config)
    assets = service.list_catalog_assets()
    with st.expander(f"Catalogo local de ativos ({len(assets)})", expanded=False):
        if not assets:
            st.info("Nenhum ativo persistido localmente ainda.")
            return
        metadata_records = db.get_instrument_metadata_map([item.id for item in assets])
        metadata_by_asset = {
            item_id: json.loads(metadata.payload_json)
            for item_id, metadata in metadata_records.items()
            if metadata.payload_json
        }
        df = pd.DataFrame(
            [
                {
                    "nome": item.display_name,
                    "symbol": item.symbol,
                    "tipo": item.kind,
                    "bolsa": item.exchange or "-",
                    "moeda": item.currency,
                    "setor": metadata_by_asset.get(item.id, {}).get("sector", "-"),
                    "perfil": metadata_by_asset.get(item.id, {}).get("risk_profile", "-"),
                    "papel": metadata_by_asset.get(item.id, {}).get("benchmark_role", "-"),
                    "provider": item.provider_primary or "-",
                }
                for item in assets
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True, height=280)
        st.caption("Esse catalogo local foi ampliado para cobrir mais setores, bolsas e perfis de risco, servindo como base visual e analitica do comparador.")


def _render_comparables(snapshot: ComparisonSnapshot) -> ComparableListing | None:
    if not snapshot.comparables:
        st.info("Nenhum comparavel disponivel no snapshot atual.")
        return None

    options = {
        f"#{item.listing_id} | R$ {item.price_brl:.2f} | float {item.float_value if item.float_value is not None else '-'}": item
        for item in snapshot.comparables
    }
    current_listing_id = st.session_state.get(LISTING_SESSION_KEY) or snapshot.comparables[0].listing_id
    default_index = 0
    for idx, item in enumerate(snapshot.comparables):
        if item.listing_id == current_listing_id:
            default_index = idx
            break

    selected_label = st.selectbox("Listing de referencia", list(options.keys()), index=default_index)
    selected = options[selected_label]
    st.session_state[LISTING_SESSION_KEY] = selected.listing_id

    table = pd.DataFrame(
        [
            {
                "listing": item.listing_id,
                "preco_brl": item.price_brl,
                "preco_usd": item.price_usd,
                "float": item.float_value,
                "gap_float": item.float_delta,
                "seed": item.paint_seed or "-",
                "seed_match": "Sim" if item.seed_match else "Nao",
                "watchers": item.watchers,
                "trades": item.seller_trade_count,
                "verified": item.seller_verified_trades,
            }
            for item in snapshot.comparables
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
    return selected


def _render_simulation(snapshot: ComparisonSnapshot, skin: Skin, listing: ComparableListing | None, iof_percentual: float) -> None:
    st.markdown("### Simulacao local em tempo real")
    st.caption("Os controles abaixo recalculam instantaneamente usando o snapshot atual. Nenhum slider dispara nova chamada externa.")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        market_move_pct = st.slider("Mercado %", min_value=-25, max_value=25, value=0, step=1)
    with c2:
        fx_move_pct = st.slider("Cambio %", min_value=-15, max_value=15, value=0, step=1)
    with c3:
        liquidity_haircut_pct = st.slider("Haircut liquidez %", min_value=0, max_value=20, value=3, step=1)
    with c4:
        exit_fee_pct = st.slider("Taxa de saida %", min_value=0.0, max_value=15.0, value=2.5, step=0.5)

    c5, c6 = st.columns(2)
    with c5:
        custom_target_pct = st.slider("Ajuste extra do alvo %", min_value=-20, max_value=20, value=0, step=1)
    with c6:
        reference_anchor = st.selectbox(
            "Anchor da simulacao",
            ["Benchmark do snapshot", "Melhor listing", "Listing selecionado"],
        )

    simulation_snapshot = snapshot.model_copy(deep=True)
    if listing and reference_anchor == "Listing selecionado":
        simulation_snapshot.benchmark_price_brl = listing.price_brl
        simulation_snapshot.best_offer_price_brl = listing.price_brl
    elif reference_anchor == "Melhor listing" and snapshot.best_offer_price_brl > 0:
        simulation_snapshot.benchmark_price_brl = snapshot.best_offer_price_brl

    projection = build_projection(
        simulation_snapshot,
        purchase_price_brl=skin.preco_compra,
        iof_percentual=iof_percentual if skin.iof_aplicavel else 0.0,
        market_move_pct=market_move_pct,
        fx_move_pct=fx_move_pct,
        liquidity_haircut_pct=liquidity_haircut_pct,
        exit_fee_pct=exit_fee_pct,
        custom_target_pct=custom_target_pct,
    )

    c7, c8, c9, c10, c11 = st.columns(5)
    c7.metric("Alvo simulado", f"R$ {projection['reference_price_brl']:,.2f}", border=True)
    c8.metric("Saida bruta", f"R$ {projection['gross_exit_brl']:,.2f}", border=True)
    c9.metric("Saida liquida", f"R$ {projection['net_exit_brl']:,.2f}", border=True)
    c10.metric("PnL projetado", f"R$ {projection['pnl_brl']:,.2f}", delta=f"{projection['pnl_pct']:+.1%}", border=True)
    c11.metric("Base com IOF", f"R$ {projection['purchase_with_iof_brl']:,.2f}", border=True)

    st.caption(f"Ultimo recalculo local: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")


def _format_dt(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value


def render() -> None:
    _ensure_state()
    data = carregar_dados()
    if hydrate_app_data_from_catalog(data):
        salvar_dados(data)

    _hero(len(data.skins))
    _render_provider_health()
    _render_asset_catalog(data.config)

    selected_skin, selected_asset, submitted = _render_controls(data.skins, data.config)
    snapshot = _load_snapshot()

    if submitted:
        snapshot = _load_snapshot()

    if not selected_skin or not selected_asset:
        return

    if snapshot and snapshot.skin_id != selected_skin.id:
        st.caption("O snapshot salvo pertence a outra skin. Envie o formulario para atualizar a comparacao desta selecao.")

    active_snapshot = snapshot if snapshot and snapshot.skin_id == selected_skin.id else None
    if not active_snapshot:
        local_record = obter_market_snapshot(selected_skin.id)
        if local_record:
            st.info("Nenhum snapshot novo nesta sessao. Exibindo o ultimo snapshot salvo localmente para testes e comparacoes.")
            active_snapshot = local_record.snapshot
        else:
            st.info("Selecione o ativo e clique em buscar para montar o snapshot seguro de comparacao.")
            return
    local_record = obter_market_snapshot(selected_skin.id)
    asset_context = _load_asset_context(selected_asset, data.config, refresh_series=False)
    skin_history_summary = summarize_skin_history(active_snapshot, local_record)
    asset_context["skin_history_count"] = skin_history_summary["count"]

    _render_comparison_summary(selected_skin, selected_asset, active_snapshot, asset_context, skin_history_summary)
    _render_snapshot_overview(active_snapshot)
    tab_resumo, tab_mercado, tab_simulacao = st.tabs(["Resumo", "Mercado", "Simulacao"])
    with tab_resumo:
        c1, c2 = st.columns(2)
        with c1:
            _render_skin_panel(selected_skin, active_snapshot, data.config.iof_percentual)
        with c2:
            _render_asset_panel(selected_asset, asset_context, selected_skin)
        _render_trend_section(active_snapshot, selected_asset, asset_context, skin_history_summary)
    with tab_mercado:
        selected_listing = _render_comparables(active_snapshot)
        c3, c4 = st.columns(2)
        with c3:
            _render_reference_panel(selected_listing, active_snapshot)
        with c4:
            _render_market_details(local_record)
        _render_local_history(local_record)
    with tab_simulacao:
        selected_listing = _render_comparables(active_snapshot) if active_snapshot.comparables else None
        _render_simulation(active_snapshot, selected_skin, selected_listing, data.config.iof_percentual)
