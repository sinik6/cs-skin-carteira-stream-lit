"""Pagina Adicionar Ativo - cadastro local de posicoes de ativos."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime

import streamlit as st

from app.models import AssetPosition, AssetSearchResult, InstrumentMetadata, MarketInstrument
from app.services import db
from app.services.asset_service import AssetService
from app.services.storage import adicionar_posicao_ativo, carregar_dados


SEARCH_RESULTS_KEY = "asset_add_search_results"
SEARCH_ATTEMPTED_KEY = "asset_add_search_attempted"


def _color_triplet(seed: str) -> tuple[str, str, str]:
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    base = "#" + digest[:6]
    accent = "#" + digest[6:12]
    foreground = "#F8FAFC"
    return base, accent, foreground


def _metadata_dict(instrument_id: str) -> dict[str, object]:
    metadata = db.get_instrument_metadata(instrument_id)
    if not metadata or not metadata.payload_json:
        return {}
    try:
        return json.loads(metadata.payload_json)
    except json.JSONDecodeError:
        return {}


def _brand_metadata(asset: MarketInstrument, metadata: dict[str, object]) -> dict[str, str]:
    bg_default, accent_default, fg_default = _color_triplet(asset.symbol or asset.display_name)
    return {
        "bg": str(metadata.get("brand_bg", bg_default)),
        "accent": str(metadata.get("brand_accent", accent_default)),
        "fg": str(metadata.get("brand_fg", fg_default)),
        "mark": str(metadata.get("logo_mark", (asset.symbol or asset.display_name)[:3].upper())),
    }


def _thumbnail_bytes(asset: MarketInstrument, metadata: dict[str, object]) -> bytes:
    brand = _brand_metadata(asset, metadata)
    symbol = (asset.symbol or asset.display_name).upper()[:8]
    mark = brand["mark"][:3].upper()
    svg = f"""
    <svg viewBox="0 0 88 88" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="{brand['bg']}"/>
          <stop offset="100%" stop-color="{brand['accent']}"/>
        </linearGradient>
      </defs>
      <rect width="88" height="88" rx="20" fill="url(#grad)"/>
      <circle cx="70" cy="18" r="8" fill="rgba(255,255,255,0.16)"/>
      <path d="M12 61 C32 34, 54 34, 76 18" stroke="rgba(255,255,255,0.20)" stroke-width="5" fill="none" stroke-linecap="round"/>
      <text x="14" y="44" fill="{brand['fg']}" font-size="24" font-weight="800" font-family="Plus Jakarta Sans, sans-serif">{mark}</text>
      <text x="14" y="65" fill="rgba(255,255,255,0.76)" font-size="10" font-weight="700" font-family="Plus Jakarta Sans, sans-serif">{symbol}</text>
    </svg>
    """
    return svg.encode("utf-8")


def _render_asset_thumbnail(asset: MarketInstrument, metadata: dict[str, object]) -> None:
    encoded = base64.b64encode(_thumbnail_bytes(asset, metadata)).decode("ascii")
    st.markdown(
        (
            "<div style='max-width:156px;'>"
            f"<img src='data:image/svg+xml;base64,{encoded}' "
            "style='width:100%;max-width:156px;border-radius:16px;display:block;' />"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _fallback_metadata(asset: MarketInstrument, search_result: AssetSearchResult | None = None) -> dict[str, object]:
    existing = _metadata_dict(asset.id)
    if existing:
        return existing
    sector = ""
    country = ""
    if search_result:
        sector = search_result.instrument_type or ""
        country = search_result.country or ""
    return {
        "sector": sector or asset.kind.upper(),
        "country": country or "-",
        "class_label": asset.kind.upper(),
        "risk_profile": "Moderado",
        "benchmark_role": "Ativo monitorado",
        "style_box": "Blend",
        "logo_mark": (asset.symbol or asset.display_name)[:3].upper(),
    }


def _search_result_to_instrument(result: AssetSearchResult) -> MarketInstrument:
    return MarketInstrument(
        id=f"asset_{result.provider}_{result.symbol.replace('/', '_').replace(':', '_')}".lower(),
        kind=AssetService._map_kind(result.instrument_type),
        display_name=result.name or result.symbol,
        symbol=result.symbol,
        currency=result.currency or "USD",
        exchange=result.exchange,
        provider_primary=result.provider,
        provider_fallback="alphavantage" if result.provider != "alphavantage" else "",
    )


def _result_label(result: AssetSearchResult) -> str:
    exchange = f" | {result.exchange}" if result.exchange else ""
    return f"{result.name} ({result.symbol}){exchange}"


def _render_preview(asset: MarketInstrument, metadata: dict[str, object]) -> None:
    with st.container(border=True):
        _render_asset_thumbnail(asset, metadata)
        st.markdown(f"**{asset.display_name}**")
        st.caption(f"{asset.symbol} | {asset.kind.upper()} | {asset.exchange or '-'}")
        st.caption(
            " | ".join(
                [
                    f"Moeda: {asset.currency}",
                    f"Setor: {metadata.get('sector', '-')}",
                    f"Perfil: {metadata.get('risk_profile', '-')}",
                ]
            )
        )
        cols = st.columns(3)
        cols[0].metric("Classe", str(metadata.get("class_label", asset.kind.upper())), border=True)
        cols[1].metric("Pais", str(metadata.get("country", "-")), border=True)
        cols[2].metric("Papel", str(metadata.get("benchmark_role", "-")), border=True)


def _render_positions() -> None:
    data = carregar_dados()
    positions = data.asset_positions
    st.markdown(f"**Ativos adicionados ({len(positions)})**")
    if not positions:
        st.info("Nenhum ativo foi adicionado ainda.")
        return

    metadata_map = db.get_instrument_metadata_map([item.instrument_id for item in positions])
    latest_map = db.get_latest_weekly_price_map([item.instrument_id for item in positions])
    cols = st.columns(2)
    for index, position in enumerate(positions):
        metadata = {}
        metadata_record = metadata_map.get(position.instrument_id)
        if metadata_record and metadata_record.payload_json:
            try:
                metadata = json.loads(metadata_record.payload_json)
            except json.JSONDecodeError:
                metadata = {}
        asset = MarketInstrument(
            id=position.instrument_id,
            display_name=position.display_name,
            symbol=position.symbol,
            kind=position.kind,
            exchange=position.exchange,
            currency=position.currency,
        )
        latest = latest_map.get(position.instrument_id)
        current_value = round(position.quantity * latest.close_brl, 2) if latest else 0.0
        pnl = round(current_value - position.total_cost_brl, 2) if latest else 0.0
        with cols[index % 2]:
            with st.container(border=True):
                _render_asset_thumbnail(asset, metadata)
                st.markdown(f"**{position.display_name}**")
                st.caption(f"{position.symbol} | {position.kind.upper()} | {position.exchange or '-'}")
                st.caption(
                    " | ".join(
                        [
                            f"Quantidade: {position.quantity:g}",
                            f"Custo medio: R$ {position.average_cost_brl:.2f}",
                            f"Setor: {metadata.get('sector', '-')}",
                        ]
                    )
                )
                k1, k2, k3 = st.columns(3)
                k1.metric("Custo total", f"R$ {position.total_cost_brl:,.2f}", border=True)
                k2.metric("Valor atual", f"R$ {current_value:,.2f}" if latest else "-", delta=f"{(pnl / position.total_cost_brl):+.1%}" if latest and position.total_cost_brl > 0 else None, border=True)
                k3.metric("Ultimo cache", latest.week_end_date if latest else "sem serie", border=True)
                if position.notes:
                    st.caption(position.notes)


def _render_position_form(selected_instrument: MarketInstrument, selected_search_result: AssetSearchResult | None, preview_metadata: dict[str, object], data, service: AssetService) -> None:
    _render_preview(selected_instrument, preview_metadata)
    with st.container(border=True):
        st.subheader("Informacoes da posicao")
        with st.form("form_add_asset_position", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            quantity = c1.number_input("Quantidade", min_value=0.0, value=1.0, step=1.0, format="%.4f")
            avg_cost_brl = c2.number_input("Preco medio em BRL", min_value=0.0, value=0.0, step=1.0, format="%.2f")
            sync_weekly = c3.toggle(
                "Atualizar serie semanal",
                value=bool(data.config.twelvedata_api_key or data.config.alphavantage_api_key),
                disabled=not bool(data.config.twelvedata_api_key or data.config.alphavantage_api_key),
            )
            notes = st.text_area("Notas", placeholder="Tese, motivo da compra ou observacoes")
            submitted = st.form_submit_button("Salvar ativo na carteira", type="primary", use_container_width=True)

        if submitted:
            if quantity <= 0:
                st.error("A quantidade precisa ser maior que zero.")
                return

            instrument_to_save = selected_instrument
            if selected_search_result:
                instrument_to_save = service.get_or_create_instrument(selected_search_result)
            elif not db.get_instrument(selected_instrument.id):
                db.upsert_instrument(selected_instrument)

            existing_metadata = _metadata_dict(instrument_to_save.id)
            merged_metadata = {**existing_metadata, **preview_metadata}
            db.upsert_instrument_metadata(
                InstrumentMetadata(
                    instrument_id=instrument_to_save.id,
                    payload_json=json.dumps(merged_metadata),
                    updated_at=datetime.now().isoformat(),
                )
            )

            if sync_weekly:
                service.fetch_weekly_series(instrument_to_save, outputsize=12)

            position = AssetPosition(
                instrument_id=instrument_to_save.id,
                display_name=instrument_to_save.display_name,
                symbol=instrument_to_save.symbol,
                kind=instrument_to_save.kind,
                exchange=instrument_to_save.exchange,
                currency=instrument_to_save.currency,
                quantity=quantity,
                average_cost_brl=avg_cost_brl,
                notes=notes.strip(),
            )
            adicionar_posicao_ativo(position)
            st.success(f"**{position.display_name}** adicionado com sucesso a carteira de ativos.")
            st.info(
                f"Quantidade: {position.quantity:g} | "
                f"Custo medio: R$ {position.average_cost_brl:.2f} | "
                f"Custo total: R$ {position.total_cost_brl:.2f}"
            )


def render() -> None:
    data = carregar_dados()
    service = AssetService(data.config)
    local_assets = service.list_catalog_assets()
    st.session_state.setdefault(SEARCH_RESULTS_KEY, [])
    st.session_state.setdefault(SEARCH_ATTEMPTED_KEY, False)

    st.markdown(
        """
        <div class="app-hero">
            <div class="app-hero-eyebrow">Cadastro</div>
            <div class="app-hero-title">Adicionar ativo financeiro</div>
            <div class="app-hero-copy">
                Registre a posicao do ativo, mantenha miniatura local e aproveite o cache semanal para comparacoes e leitura de carteira.
            </div>
            <div class="app-chip-row">
                <span class="app-chip">Catalogo local ampliado</span>
                <span class="app-chip">Busca por simbolo opcional</span>
                <span class="app-chip">Cache semanal local</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    selected_instrument: MarketInstrument | None = None
    selected_search_result: AssetSearchResult | None = None
    tab_local, tab_search = st.tabs(["Catalogo local", "Buscar por simbolo"])

    with tab_local:
        with st.container(border=True):
            st.caption("Escolha um ativo do banco local preparado para comparacao e carteira.")
            options = {f"{item.display_name} ({item.symbol}) | {item.kind.upper()}": item for item in local_assets}
            if options:
                selected_label = st.selectbox("Ativo do catalogo local", list(options.keys()))
                selected_instrument = options[selected_label]

    with tab_search:
        with st.container(border=True):
            st.caption("Use a busca externa quando quiser cadastrar um simbolo fora do catalogo local.")
            query_col, button_col = st.columns([0.78, 0.22])
            with query_col:
                query = st.text_input("Buscar ativo", placeholder="Ex: GOOGL, PETR4, BTC/USD")
            with button_col:
                search_clicked = st.button("Buscar", use_container_width=True)
            if search_clicked:
                st.session_state[SEARCH_RESULTS_KEY] = service.search_assets(query)
                st.session_state[SEARCH_ATTEMPTED_KEY] = True
            results = st.session_state.get(SEARCH_RESULTS_KEY, [])
            if results:
                options = {_result_label(item): item for item in results}
                selected_label = st.selectbox("Resultados encontrados", list(options.keys()))
                selected_search_result = options[selected_label]
                selected_instrument = _search_result_to_instrument(selected_search_result)
            elif st.session_state.get(SEARCH_ATTEMPTED_KEY):
                st.info("Sem resultados externos no momento. Voce ainda pode usar o catalogo local.")

    if selected_instrument:
        preview_metadata = _fallback_metadata(selected_instrument, selected_search_result)
        _render_position_form(selected_instrument, selected_search_result, preview_metadata, data, service)

    st.divider()
    _render_positions()

    with st.expander("Como usar", expanded=False):
        st.markdown(
            """
Use **Catalogo local** para adicionar rapidamente os ativos que ja deixamos preparados no app.

Use **Buscar por simbolo** quando houver chave de provider configurada e voce quiser trazer um ativo novo.

O app salva a **posicao local** e tenta usar o **cache semanal local** para mostrar valor atual e apoiar a comparacao com skins.
            """
        )
