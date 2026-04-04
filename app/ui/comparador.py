"""Pagina Comparador - ativo vs item com snapshot seguro e simulacao local."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from app.config import COMPARISON_DEFAULT_FLOAT_MARGIN
from app.models import ComparableListing, ComparisonSnapshot, MarketIntelligenceRecord, Skin
from app.services.catalog_service import hydrate_app_data_from_catalog
from app.services.comparison_service import ComparisonService, build_projection
from app.services.runtime_state import get_provider_state, provider_is_in_cooldown
from app.services.storage import carregar_dados, obter_market_snapshot, salvar_dados
from app.services.thumbnail_service import ThumbnailService

THUMBNAIL_SERVICE = ThumbnailService()
SNAPSHOT_SESSION_KEY = "comparison_snapshot"
LISTING_SESSION_KEY = "comparison_listing_id"


def _ensure_state() -> None:
    st.session_state.setdefault(SNAPSHOT_SESSION_KEY, {})
    st.session_state.setdefault(LISTING_SESSION_KEY, "")


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
    with st.container(border=True):
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


def _render_controls(skins: list[Skin], config) -> tuple[Skin | None, bool]:
    if not skins:
        st.info("Nenhuma skin cadastrada para comparar.")
        return None, False

    options = {f"{skin.nome} | {skin.desgaste} | compra R$ {skin.preco_compra:.2f}": skin for skin in skins}

    with st.form("comparison_fetch_form", border=False):
        c1, c2 = st.columns([2.2, 1.4])
        with c1:
            selected_label = st.selectbox("Ativo da carteira", list(options.keys()))
        with c2:
            considerar_float = st.toggle("Usar float", value=True)

        c3, c4, c5 = st.columns(3)
        with c3:
            considerar_pattern = st.toggle("Usar pattern", value=True)
        with c4:
            margem_float = st.slider(
                "Margem do float",
                min_value=0.005,
                max_value=0.050,
                value=COMPARISON_DEFAULT_FLOAT_MARGIN,
                step=0.005,
                format="%.3f",
            )
        with c5:
            st.text_input(
                "Provider principal",
                value="CSFloat (Steam como base/fallback)",
                disabled=True,
            )

        submitted = st.form_submit_button("Buscar comparaveis com seguranca", type="primary", use_container_width=True)

    if submitted:
        service = ComparisonService(config)
        snapshot = service.montar_snapshot(
            options[selected_label],
            considerar_float=considerar_float,
            margem_float=margem_float,
            considerar_pattern=considerar_pattern,
        )
        _store_snapshot(snapshot)
        return options[selected_label], True

    return options[selected_label], False


def _render_snapshot_overview(snapshot: ComparisonSnapshot) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Preco do ativo", f"R$ {snapshot.asset_price_brl:,.2f}", border=True)
    c2.metric("Benchmark", f"R$ {snapshot.benchmark_price_brl:,.2f}", delta=f"{snapshot.spread_to_benchmark_pct:+.1%}", border=True)
    c3.metric("Melhor listing", f"R$ {snapshot.best_offer_price_brl:,.2f}", delta=f"{snapshot.spread_to_best_offer_pct:+.1%}", border=True)
    c4.metric("Amostra", snapshot.comparables_count, delta=snapshot.confidence, border=True)
    c5.metric("Seed match", snapshot.exact_seed_matches, border=True)

    st.caption(
        f"Snapshot de {snapshot.source_provider.upper()} via {snapshot.source_method or 'comparacao de mercado'} "
        f"em {_format_dt(snapshot.fetched_at)}."
    )
    if snapshot.note:
        st.info(snapshot.note)


def _render_head_to_head(skin: Skin, snapshot: ComparisonSnapshot, listing: ComparableListing | None, iof_percentual: float) -> None:
    col_asset, col_item = st.columns(2)
    with col_asset:
        with st.container(border=True):
            st.markdown("**Seu ativo**")
            thumb = _skin_thumbnail(skin)
            if thumb:
                st.image(thumb, use_container_width=True)
            st.markdown(f"### {skin.nome}")
            st.caption(f"{skin.tipo} | {skin.desgaste}")
            st.write(f"Compra: **R$ {skin.preco_compra:.2f}**")
            st.write(f"Compra + IOF: **R$ {skin.total_com_iof_com_taxa(iof_percentual):.2f}**")
            st.write(f"Preco atual do ativo: **R$ {snapshot.asset_price_brl:.2f}**")
            st.write(f"Origem: **{snapshot.asset_price_source or '-'}**")

    with col_item:
        with st.container(border=True):
            st.markdown("**Item de referencia**")
            if listing:
                thumb = _thumbnail_path(listing.image_url)
                if thumb:
                    st.image(thumb, use_container_width=True)
                st.markdown(f"### {listing.market_hash_name}")
                st.caption(f"Listing #{listing.listing_id}")
                st.write(f"Preco anunciado: **R$ {listing.price_brl:.2f}**")
                st.write(f"Oferta minima: **R$ {listing.min_offer_price_brl:.2f}**")
                float_text = f"{listing.float_value:.6f}" if listing.float_value is not None else "-"
                delta_text = f"{listing.float_delta:.5f}" if listing.float_delta is not None else "-"
                st.write(f"Float: **{float_text}**")
                st.write(f"Gap do float: **{delta_text}**")
                st.write(f"Seed match: **{'Sim' if listing.seed_match else 'Nao'}**")
                st.write(f"Vendedor: **{listing.seller_name or '-'}**")
            else:
                st.write("Sem listing selecionado ainda. O benchmark usa a mediana dos comparaveis encontrados.")


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


def _render_comparables(snapshot: ComparisonSnapshot) -> ComparableListing | None:
    if not snapshot.comparables:
        st.warning("Nenhum comparavel disponivel no snapshot atual.")
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

    selected_skin, submitted = _render_controls(data.skins, data.config)
    snapshot = _load_snapshot()

    if submitted:
        snapshot = _load_snapshot()

    if not selected_skin:
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

    _render_snapshot_overview(active_snapshot)
    selected_listing = _render_comparables(active_snapshot)
    _render_head_to_head(selected_skin, active_snapshot, selected_listing, data.config.iof_percentual)
    _render_market_details(local_record)
    _render_local_history(local_record)
    _render_simulation(active_snapshot, selected_skin, selected_listing, data.config.iof_percentual)
