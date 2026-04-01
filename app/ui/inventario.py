"""Pagina Inventario - grade visual e detalhe das skins."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from app.config import CATALOG_SNAPSHOT_FILE, PRICE_STALE_AFTER_HOURS, THUMBNAIL_PAGE_SIZE
from app.models import AppData, Skin
from app.services.catalog_sync import sync_catalog_snapshot
from app.services.catalog_service import get_catalog_entry_for_skin, hydrate_app_data_from_catalog
from app.services.storage import carregar_dados, salvar_dados
from app.services.thumbnail_service import ThumbnailService

THUMBNAIL_SERVICE = ThumbnailService()
DETAIL_SESSION_KEY = "inventario_skin_detalhe_id"


def _format_datetime(value: str) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value


def _status_label(skin: Skin) -> str:
    if skin.preco_atual <= 0:
        return "Sem preco"
    if skin.preco_stale:
        return "Cache expirado"
    if skin.preco_cache_hit:
        return "Cache"
    return "Ao vivo"


def _thumbnail_path(skin: Skin) -> str | None:
    image_url = skin.imagem_url
    if not image_url:
        entry = get_catalog_entry_for_skin(skin)
        image_url = entry.get("image", "") if entry else ""
    if not image_url:
        return None
    local_path = THUMBNAIL_SERVICE.get_local_path(image_url)
    return str(local_path) if local_path else None


def _hero(data: AppData) -> None:
    com_miniatura = sum(1 for skin in data.skins if skin.imagem_url)
    pendentes = sum(1 for skin in data.skins if not skin.imagem_url)
    st.markdown(
        f"""
        <div style="
            padding: 1rem 1.1rem;
            margin-top: 0.35rem;
            margin-bottom: 1rem;
            border-radius: 18px;
            background: linear-gradient(135deg, rgba(24,40,54,0.96), rgba(48,72,95,0.92));
            color: #f7fbff;
            box-shadow: 0 18px 36px rgba(32,49,66,0.16);
        ">
            <div style="font-size: 0.84rem; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.74;">Inventario</div>
            <div style="font-size: 1.72rem; font-weight: 800; margin-top: 0.18rem;">Grade visual de skins</div>
            <div style="font-size: 0.95rem; opacity: 0.82; margin-top: 0.28rem;">
                Total: {len(data.skins)} | Com miniatura: {com_miniatura} | Sem miniatura: {pendentes}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_placeholder(skin: Skin) -> None:
    st.markdown(
        f"""
        <div style="
            height: 160px;
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            background: linear-gradient(145deg, rgba(227,235,242,0.9), rgba(212,223,233,0.95));
            border: 1px solid rgba(32,49,66,0.08);
            color: #32485e;
            padding: 1rem;
            font-weight: 700;
        ">
            <div>
                <div style="font-size: 0.8rem; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.72;">Sem miniatura</div>
                <div style="font-size: 1rem; margin-top: 0.4rem;">{skin.tipo}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _sync_catalog() -> None:
    try:
        result = sync_catalog_snapshot(force_refresh=False)
    except Exception as exc:
        st.error(f"Nao foi possivel sincronizar o catalogo local: {exc}")
        return

    if result.total_current_skins == 0:
        st.info("Nao ha skins cadastradas para montar um catalogo local.")
        return

    if result.matched_skins == 0:
        st.warning("O catalogo foi sincronizado, mas nenhuma skin atual encontrou correspondencia.")
        return

    st.success(
        f"Catalogo sincronizado com sucesso. "
        f"{result.matched_skins}/{result.total_current_skins} skin(s) casadas usando {len(result.source_files)} fonte(s)."
    )
    if result.hydrated_skins > 0:
        st.caption(f"{result.hydrated_skins} skin(s) foram enriquecidas com market hash e miniaturas.")
    elif result.unmatched_skins:
        st.caption("As skins restantes continuam operando sem catalogo local, sem bloquear o app.")
    else:
        st.caption("Os dados locais ja estavam alinhados com o catalogo salvo.")


def _render_grid(skins: list[Skin], iof_percentual: float) -> None:
    if not skins:
        st.info("Nenhuma skin corresponde aos filtros.")
        return

    mostrar_sem_foto = st.toggle("Incluir skins sem foto", value=True, key="inventario_mostrar_sem_foto")
    st.caption("A grade usa cache local para fotos validas e fallback visual limpo para itens ainda sem miniatura.")

    skins_filtradas = skins if mostrar_sem_foto else [skin for skin in skins if skin.imagem_url]
    if not skins_filtradas:
        st.info("Nenhuma skin com miniatura disponivel para esta visualizacao.")
        return

    total_paginas = max(1, (len(skins_filtradas) - 1) // THUMBNAIL_PAGE_SIZE + 1)
    pagina = st.number_input(
        "Pagina do inventario",
        min_value=1,
        max_value=total_paginas,
        value=1,
        step=1,
    )
    pagina_int = int(pagina)
    inicio = (pagina_int - 1) * THUMBNAIL_PAGE_SIZE
    fim = inicio + THUMBNAIL_PAGE_SIZE
    pagina_skins = skins_filtradas[inicio:fim]

    for start in range(0, len(pagina_skins), 4):
        cols = st.columns(4)
        for col, skin in zip(cols, pagina_skins[start:start + 4]):
            with col:
                with st.container(border=True):
                    image_path = _thumbnail_path(skin)
                    if image_path:
                        st.image(image_path, use_container_width=True)
                    else:
                        _render_placeholder(skin)
                    st.markdown(f"**{skin.nome}**")
                    st.caption(f"{skin.tipo} | {skin.desgaste}")
                    st.caption(f"Atual: R$ {skin.preco_atual:.2f} | {_status_label(skin)}")
                    st.caption(f"Lucro: R$ {skin.lucro_com_taxa(iof_percentual):.2f}")
                    if st.button("Ver detalhes", key=f"detalhar_{skin.id}", use_container_width=True):
                        st.session_state[DETAIL_SESSION_KEY] = skin.id


def _render_details(data: AppData, iof_percentual: float) -> None:
    selected_id = st.session_state.get(DETAIL_SESSION_KEY)
    if not selected_id and data.skins:
        selected_id = data.skins[0].id
        st.session_state[DETAIL_SESSION_KEY] = selected_id

    skin = next((item for item in data.skins if item.id == selected_id), None)
    if not skin:
        return
    catalog_entry = get_catalog_entry_for_skin(skin) or {}

    st.divider()
    st.markdown("### Detalhes da skin")

    col1, col2 = st.columns([1.1, 1.6])
    with col1:
        image_path = _thumbnail_path(skin)
        if image_path:
            st.image(image_path, use_container_width=True)
        else:
            _render_placeholder(skin)
    with col2:
        st.markdown(f"## {skin.nome}")
        st.caption(f"{skin.tipo} | {skin.desgaste} | Status do preco: {_status_label(skin)}")
        tab1, tab2, tab3 = st.tabs(["Resumo", "Mercado", "Cadastro"])

        with tab1:
            m1, m2, m3 = st.columns(3)
            m1.metric("Compra", f"R$ {skin.preco_compra:.2f}")
            m2.metric("Atual", f"R$ {skin.preco_atual:.2f}")
            m3.metric("Lucro", f"R$ {skin.lucro_com_taxa(iof_percentual):.2f}", delta=f"{skin.variacao_pct_com_taxa(iof_percentual):+.1%}")

        with tab2:
            st.write(f"Provider: **{skin.preco_provider or '-'}**")
            st.write(f"Metodo: **{skin.preco_metodo or '-'}**")
            st.write(f"Confianca: **{skin.preco_confianca or '-'}**")
            st.write(f"Amostra: **{skin.preco_amostra or '-'}**")
            st.write(f"Atualizado: **{_format_datetime(skin.preco_atualizado_em)}**")
            st.write(f"Market Hash Name: **{skin.gerar_market_hash_name()}**")
            st.write(f"Raridade: **{catalog_entry.get('rarity', {}).get('name', '-')}**")
            st.write(f"Categoria CS2: **{catalog_entry.get('category', {}).get('name', '-')}**")
            st.write(f"Pintura / Pattern: **{catalog_entry.get('pattern', {}).get('name', '-')}**")

        with tab3:
            st.write(f"Plataforma de compra: **{skin.plataforma or '-'}**")
            st.write(f"Float: **{skin.float_value:.6f}**")
            st.write(f"StatTrak: **{skin.stattrak}**")
            st.write(f"Pattern / Seed: **{skin.pattern_seed or '-'}**")
            st.write(f"IOF aplicavel: **{'Sim' if skin.iof_aplicavel else 'Nao'}**")
            st.write(f"Criado em: **{_format_datetime(skin.criado_em)}**")
            st.write(f"Notas: **{skin.notas or '-'}**")
            st.write(f"Nome no catalogo: **{catalog_entry.get('name', '-')}**")
            st.write(f"Arquivo de origem: **{catalog_entry.get('source_file', '-')}**")

        if catalog_entry.get("description"):
            st.caption(catalog_entry["description"])


def render() -> None:
    data = carregar_dados()
    if hydrate_app_data_from_catalog(data):
        salvar_dados(data)
        data = carregar_dados()

    _hero(data)

    controles_1, controles_2, controles_3 = st.columns([1.6, 1.2, 1.2])
    busca = controles_1.text_input("Buscar skin", placeholder="Nome, tipo, plataforma ou market hash")
    filtro_status = controles_2.selectbox("Status", ["Todos", "Ao vivo", "Cache", "Cache expirado", "Sem preco"])
    apenas_stale = controles_3.toggle("Somente antigas", value=False)

    acao_1, acao_2 = st.columns([1.3, 2.7])
    with acao_1:
        if st.button("Sincronizar catalogo", type="primary", use_container_width=True):
            _sync_catalog()
            data = carregar_dados()
    with acao_2:
        if CATALOG_SNAPSHOT_FILE.exists():
            st.caption("O inventario usa um catalogo local enxuto, com cache e sincronizacao manual, para preencher miniaturas e detalhes sem depender da API externa em tempo real.")
        else:
            st.caption("Sem catalogo local sincronizado ainda. O app continua funcionando e pode montar um snapshot enxuto sob demanda, baixando apenas as fontes necessarias.")

    busca_normalizada = busca.strip().lower()
    filtradas = []
    for skin in data.skins:
        bucket = " ".join(
            [
                skin.nome,
                skin.tipo,
                skin.plataforma,
                skin.market_hash_name,
                skin.gerar_market_hash_name(),
            ]
        ).lower()
        if busca_normalizada and busca_normalizada not in bucket:
            continue
        if filtro_status != "Todos" and _status_label(skin) != filtro_status:
            continue
        if apenas_stale and skin.preco_atualizado_em:
            try:
                atualizado = datetime.fromisoformat(skin.preco_atualizado_em)
                stale = (datetime.now() - atualizado).total_seconds() >= PRICE_STALE_AFTER_HOURS * 3600
                if not stale:
                    continue
            except ValueError:
                pass
        filtradas.append(skin)

    _render_grid(filtradas, data.config.iof_percentual)
    _render_details(data, data.config.iof_percentual)
