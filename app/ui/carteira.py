"""Pagina Carteira - exibe o portfolio completo de skins."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from app.config import DESGASTES, PLATAFORMAS, PRICE_PROVIDERS, PRICE_STALE_AFTER_HOURS, THUMBNAIL_PAGE_SIZE, TIPOS_ITEM
from app.models import AppData, Skin
from app.services.catalog_service import hydrate_app_data_from_catalog
from app.services.price_providers.base import PriceResult
from app.services.price_service import PriceService
from app.services.storage import atualizar_skin, carregar_dados, remover_skin, salvar_dados
from app.services.thumbnail_service import ThumbnailService

PROVIDER_LABELS = {
    "steam": "Steam Market",
    "csfloat": "CSFloat",
}

UPDATE_MODES = {
    "Pendentes e antigos": "pending_stale",
    "Somente pendentes": "pending_only",
    "Tudo": "all",
}

THUMBNAIL_SERVICE = ThumbnailService()


def _format_datetime(value: str) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%d/%m %H:%M")
    except ValueError:
        return value


def _is_stale(skin: Skin, stale_after_hours: int = PRICE_STALE_AFTER_HOURS) -> bool:
    if not skin.preco_atualizado_em:
        return True
    try:
        atualizado = datetime.fromisoformat(skin.preco_atualizado_em)
    except ValueError:
        return True
    return (datetime.now() - atualizado).total_seconds() >= stale_after_hours * 3600


def _status_label(skin: Skin) -> str:
    if skin.preco_atual <= 0:
        return "Sem preco"
    if skin.preco_stale:
        return "Cache expirado"
    if skin.preco_cache_hit:
        return "Cache"
    return "Ao vivo"


def _badge_status(value: str) -> str:
    mapping = {
        "Ao vivo": "Ao vivo",
        "Cache": "Cache",
        "Cache expirado": "Cache expirado",
        "Sem preco": "Sem preco",
    }
    return mapping.get(value, value)


def _badge_confianca(value: str) -> str:
    return value or "-"


def _aplicar_resultado_preco(skin: Skin, result: PriceResult) -> None:
    skin.preco_atual = result.preco if result.sucesso else skin.preco_atual
    skin.preco_provider = result.provider
    skin.preco_metodo = result.metodo
    skin.preco_amostra = result.amostra
    skin.preco_confianca = result.confianca
    skin.preco_cache_hit = result.cache_hit
    skin.preco_stale = result.stale
    skin.preco_atualizado_em = result.atualizado_em
    if result.imagem_url:
        skin.imagem_url = result.imagem_url


def _render_galeria(skins: list[Skin]) -> None:
    skins_com_imagem = [skin for skin in skins if skin.imagem_url]
    if not skins_com_imagem:
        st.info("Nenhuma miniatura salva ainda. A aba Inventario consegue aplicar um catalogo local opcional ou aproveitar imagens vindas do CSFloat.")
        return

    with st.expander("Galeria das skins", expanded=True):
        controles_1, controles_2, controles_3 = st.columns([1.2, 1.1, 1.7])
        with controles_1:
            exibir_miniaturas = st.toggle("Exibir miniaturas", value=True, key="galeria_exibir_miniaturas")
        total_paginas = max(1, (len(skins_com_imagem) - 1) // THUMBNAIL_PAGE_SIZE + 1)
        with controles_2:
            pagina = st.number_input("Pagina", min_value=1, max_value=total_paginas, value=1, step=1)
        with controles_3:
            st.caption("Modo seguro: a galeria usa cache local e baixa apenas as miniaturas visiveis da CDN permitida.")

        if not exibir_miniaturas:
            st.info("Miniaturas desativadas nesta sessao para manter a carteira ainda mais leve.")
            return

        pagina_int = int(pagina)
        inicio = (pagina_int - 1) * THUMBNAIL_PAGE_SIZE
        fim = inicio + THUMBNAIL_PAGE_SIZE
        pagina_skins = skins_com_imagem[inicio:fim]

        st.caption(f"Exibindo {len(pagina_skins)} de {len(skins_com_imagem)} skin(s) com miniatura.")

        for start in range(0, len(pagina_skins), 4):
            cols = st.columns(4)
            for col, skin in zip(cols, pagina_skins[start:start + 4]):
                with col:
                    image_path = _thumbnail_path(skin)
                    if image_path:
                        st.image(image_path, use_container_width=True)
                    else:
                        st.caption("Miniatura indisponivel no modo seguro")
                    st.caption(skin.nome)
                    st.caption(f"R$ {skin.preco_atual:.2f} | {_status_label(skin)}")


def _thumbnail_path(skin: Skin) -> str | None:
    if not skin.imagem_url:
        return None
    local_path = THUMBNAIL_SERVICE.get_local_path(skin.imagem_url)
    return str(local_path) if local_path else None


def _render_vitrine_compacta(skins: list[Skin], iof_percentual: float) -> None:
    skins_com_imagem = [skin for skin in skins if skin.imagem_url]
    if not skins_com_imagem:
        st.info("Nenhuma miniatura real disponivel na carteira no momento. Va em Inventario para aplicar o catalogo local opcional ou preencher imagens via CSFloat.")
        return

    st.markdown("### Visao visual")
    controles_1, controles_2, controles_3 = st.columns([1.15, 1.05, 1.8])
    with controles_1:
        exibir_vitrine = st.toggle("Miniaturas na carteira", value=True, key="vitrine_exibir")
    total_paginas = max(1, (len(skins_com_imagem) - 1) // THUMBNAIL_PAGE_SIZE + 1)
    with controles_2:
        pagina = st.number_input(
            "Pagina visual",
            min_value=1,
            max_value=total_paginas,
            value=1,
            step=1,
            key="vitrine_pagina",
        )
    with controles_3:
        st.caption("Exibe apenas os itens visiveis da pagina atual e usa cache local seguro para manter a carteira leve.")

    if not exibir_vitrine:
        st.info("A vitrine visual esta desativada nesta sessao.")
        return

    pagina_int = int(pagina)
    inicio = (pagina_int - 1) * THUMBNAIL_PAGE_SIZE
    fim = inicio + THUMBNAIL_PAGE_SIZE
    pagina_skins = skins_com_imagem[inicio:fim]

    st.caption(f"Mostrando {len(pagina_skins)} de {len(skins_com_imagem)} skin(s) com miniatura.")

    for start in range(0, len(pagina_skins), 4):
        cols = st.columns(4)
        for col, skin in zip(cols, pagina_skins[start:start + 4]):
            with col:
                image_path = _thumbnail_path(skin)
                status = _status_label(skin)
                lucro = skin.lucro_com_taxa(iof_percentual)
                variacao = skin.variacao_pct_com_taxa(iof_percentual) * 100

                with st.container(border=True):
                    if image_path:
                        st.image(image_path, use_container_width=True)
                    else:
                        st.caption("Miniatura indisponivel no modo seguro")
                    st.markdown(f"**{skin.nome}**")
                    st.caption(f"{skin.tipo} | {skin.desgaste}")
                    st.caption(f"Compra: R$ {skin.preco_compra:.2f} | Atual: R$ {skin.preco_atual:.2f}")
                    st.caption(f"Lucro: R$ {lucro:.2f} | Variacao: {variacao:+.1f}%")
                    st.caption(f"Status: {status}")


def _hero(data: AppData) -> None:
    pendentes = sum(1 for skin in data.skins if skin.preco_atual <= 0)
    antigos = sum(1 for skin in data.skins if skin.preco_atual > 0 and _is_stale(skin))

    st.markdown(
        f"""
        <div style="
            padding: 1rem 1.1rem;
            margin-top: 0.35rem;
            margin-bottom: 1rem;
            border-radius: 18px;
            background: linear-gradient(135deg, rgba(32,49,66,0.96), rgba(59,85,110,0.92));
            color: #f7fbff;
            box-shadow: 0 18px 36px rgba(32,49,66,0.16);
        ">
            <div style="font-size: 0.84rem; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.74;">Carteira</div>
            <div style="font-size: 1.72rem; font-weight: 800; margin-top: 0.18rem;">Visao consolidada do inventario</div>
            <div style="font-size: 0.95rem; opacity: 0.82; margin-top: 0.28rem;">
                IOF aplicado na exibicao: {data.config.iof_percentual:.2f}% | Pendentes: {pendentes} | Antigos: {antigos}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _metricas_resumo(skins: list[Skin], iof_percentual: float) -> None:
    if not skins:
        st.info("Nenhuma skin cadastrada. Va em Adicionar Skin para comecar.")
        return

    total_investido = sum(s.total_com_iof_com_taxa(iof_percentual) for s in skins)
    valor_atual = sum(s.preco_atual for s in skins)
    lucro_total = valor_atual - total_investido
    variacao = (lucro_total / total_investido * 100) if total_investido > 0 else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Itens", len(skins))
    c2.metric("Investido", f"R$ {total_investido:,.2f}")
    c3.metric("Valor Atual", f"R$ {valor_atual:,.2f}")
    c4.metric("Lucro / Prejuizo", f"R$ {lucro_total:,.2f}", delta=f"{variacao:+.1f}%")


def _render_tabela(skins: list[Skin], iof_percentual: float) -> None:
    if not skins:
        st.info("Nenhuma skin corresponde aos filtros.")
        return

    rows = []
    for skin in skins:
        rows.append(
            {
                "Nome": skin.nome,
                "Tipo": skin.tipo,
                "Desgaste": skin.desgaste,
                "Plataforma": skin.plataforma,
                "Status": _badge_status(_status_label(skin)),
                "Fonte": skin.preco_provider or "-",
                "Metodo": skin.preco_metodo or "-",
                "Amostra": skin.preco_amostra if skin.preco_amostra else "-",
                "Confianca": _badge_confianca(skin.preco_confianca),
                "Atualizado": _format_datetime(skin.preco_atualizado_em),
                "Compra": skin.preco_compra,
                "Com IOF": skin.total_com_iof_com_taxa(iof_percentual),
                "Atual": skin.preco_atual,
                "Lucro": skin.lucro_com_taxa(iof_percentual),
                "Variacao": skin.variacao_pct_com_taxa(iof_percentual),
            }
        )

    df = pd.DataFrame(rows)

    def _color_lucro(val):
        if isinstance(val, (int, float)):
            if val < 0:
                return "color: #b42318; background-color: rgba(180, 35, 24, 0.08); font-weight: 700"
            if val > 0:
                return "color: #067647; background-color: rgba(6, 118, 71, 0.08); font-weight: 700"
        return ""

    def _color_variacao(val):
        if isinstance(val, (int, float)):
            if val < 0:
                return "color: #b42318; font-weight: 700"
            if val > 0:
                return "color: #067647; font-weight: 700"
        return ""

    def _color_status(val):
        text = str(val)
        if "Ao vivo" in text:
            return "color: #067647; font-weight: 700"
        if "Cache expirado" in text:
            return "color: #b54708; font-weight: 700"
        if "Cache" in text:
            return "color: #175cd3; font-weight: 700"
        if "Sem preco" in text:
            return "color: #b42318; font-weight: 700"
        return ""

    def _color_confianca(val):
        text = str(val)
        if "Alta" in text:
            return "color: #067647; font-weight: 700"
        if "Media" in text:
            return "color: #175cd3; font-weight: 700"
        if "Baixa" in text:
            return "color: #b54708; font-weight: 700"
        return ""

    styled = (
        df.style.format(
            {
                "Compra": "R$ {:.2f}",
                "Com IOF": "R$ {:.2f}",
                "Atual": "R$ {:.2f}",
                "Lucro": "R$ {:.2f}",
                "Variacao": "{:.1%}",
            }
        )
        .map(_color_lucro, subset=["Lucro"])
        .map(_color_variacao, subset=["Variacao"])
        .map(_color_status, subset=["Status"])
        .map(_color_confianca, subset=["Confianca"])
    )

    st.dataframe(styled, use_container_width=True, hide_index=True, height=640)


def _filtrar_para_atualizacao(skins: list[Skin], update_mode: str) -> list[Skin]:
    if update_mode == "all":
        return skins
    if update_mode == "pending_only":
        return [skin for skin in skins if skin.preco_atual <= 0]
    return [skin for skin in skins if skin.preco_atual <= 0 or _is_stale(skin)]


def _atualizar_precos(
    data: AppData,
    provider_escolhido: str,
    update_mode: str,
    considerar_float: bool = False,
    margem_float: float = 0.01,
    considerar_pattern: bool = False,
) -> None:
    if not data.skins:
        st.warning("Nenhuma skin para atualizar.")
        return

    skins_alvo = _filtrar_para_atualizacao(data.skins, update_mode)
    if not skins_alvo:
        st.info("Nenhuma skin precisa ser atualizada neste modo.")
        return

    config_busca = data.config.model_copy(update={"provider_preferido": provider_escolhido})
    svc = PriceService(
        config_busca,
        considerar_float=considerar_float,
        margem_float=margem_float,
        considerar_pattern=considerar_pattern,
    )

    if not svc.providers_disponiveis:
        st.error("Nenhum provider de preco disponivel. Configure uma API key em Configuracoes.")
        return

    st.info(f"Atualizando {len(skins_alvo)} item(ns) com cache persistente e fallback seguro.")
    progress = st.progress(0, text="Iniciando...")
    erros = []

    def on_progress(atual: int, total: int, nome: str) -> None:
        progress.progress(atual / total, text=f"({atual}/{total}) {nome}")

    resultados = svc.buscar_precos_lote(skins_alvo, on_progress=on_progress)

    atualizados = 0
    for skin in data.skins:
        result = resultados.get(skin.id)
        if result and result.sucesso and result.preco > 0:
            _aplicar_resultado_preco(skin, result)
            atualizados += 1
        elif result and not result.sucesso:
            erros.append(f"**{skin.nome}**: {result.erro}")

    salvar_dados(data)
    progress.empty()

    if atualizados > 0:
        st.success(f"{atualizados} preco(s) atualizados com sucesso.")

    if erros:
        with st.expander(f"{len(erros)} erro(s) na busca", expanded=False):
            for erro in erros:
                st.write(f"- {erro}")


def _secao_editar(data: AppData) -> None:
    if not data.skins:
        return

    opcoes = {f"{s.nome} ({s.desgaste}) - R$ {s.preco_compra:.2f}": s.id for s in data.skins}

    with st.expander("Editar skin", expanded=False):
        escolha = st.selectbox("Selecione a skin para editar:", list(opcoes.keys()), key="edit_select")
        skin_id = opcoes[escolha]
        skin = next(s for s in data.skins if s.id == skin_id)

        with st.form("form_edit_skin"):
            col1, col2 = st.columns(2)
            nome = col1.text_input("Nome", value=skin.nome)
            tipo = col2.selectbox("Tipo", TIPOS_ITEM, index=TIPOS_ITEM.index(skin.tipo) if skin.tipo in TIPOS_ITEM else 0)

            col3, col4, col5 = st.columns(3)
            desgaste = col3.selectbox("Desgaste", DESGASTES, index=DESGASTES.index(skin.desgaste) if skin.desgaste in DESGASTES else 0)
            float_val = col4.number_input("Float Value", min_value=0.0, max_value=1.0, value=skin.float_value, format="%.6f")
            stattrak = col5.selectbox("StatTrak", ["Nao", "Sim", "N/A"], index=["Nao", "Sim", "N/A"].index(skin.stattrak) if skin.stattrak in ["Nao", "Sim", "N/A"] else 0)

            col6, col7 = st.columns(2)
            pattern = col6.text_input("Pattern / Seed", value=skin.pattern_seed)
            market_hash = col7.text_input("Market Hash Name", value=skin.market_hash_name)

            col8, col9, col10 = st.columns(3)
            plataforma = col8.selectbox("Plataforma", PLATAFORMAS, index=PLATAFORMAS.index(skin.plataforma) if skin.plataforma in PLATAFORMAS else 0)
            preco_compra = col9.number_input("Preco de Compra (R$)", min_value=0.0, value=skin.preco_compra, format="%.2f")
            iof = col10.selectbox("IOF Aplicavel?", ["Sim", "Nao"], index=0 if skin.iof_aplicavel else 1)

            notas = st.text_area("Notas", value=skin.notas)
            submitted = st.form_submit_button("Salvar Alteracoes", type="primary", use_container_width=True)

        if submitted:
            skin.nome = nome.strip()
            skin.tipo = tipo
            skin.desgaste = desgaste
            skin.float_value = float_val
            skin.stattrak = stattrak
            skin.pattern_seed = pattern.strip()
            skin.market_hash_name = market_hash.strip()
            skin.plataforma = plataforma
            skin.preco_compra = preco_compra
            skin.iof_aplicavel = iof == "Sim"
            skin.notas = notas.strip()
            atualizar_skin(skin)
            st.success(f"{skin.nome} atualizada com sucesso.")
            st.rerun()


def _secao_remover(data: AppData) -> None:
    opcoes = {f"{s.nome} ({s.desgaste}) - R$ {s.preco_compra:.2f}": s.id for s in data.skins}
    if not opcoes:
        return

    with st.expander("Remover skin", expanded=False):
        escolha = st.selectbox("Selecione a skin para remover:", list(opcoes.keys()), key="remove_select")
        if st.button("Remover", type="secondary"):
            remover_skin(opcoes[escolha])
            st.success(f"Skin '{escolha}' removida!")
            st.rerun()


def render() -> None:
    data = carregar_dados()
    if hydrate_app_data_from_catalog(data):
        salvar_dados(data)
        data = carregar_dados()

    _hero(data)

    row1_col1, row1_col2, row1_col3 = st.columns([1.8, 1.2, 1.2])
    with row1_col1:
        provider_escolhido = st.selectbox(
            "Provider base",
            options=PRICE_PROVIDERS,
            index=PRICE_PROVIDERS.index(data.config.provider_preferido)
            if data.config.provider_preferido in PRICE_PROVIDERS
            else 0,
            format_func=lambda x: PROVIDER_LABELS.get(x, x),
        )
    with row1_col2:
        considerar_float = st.toggle("Considerar float", value=False)
    with row1_col3:
        considerar_pattern = st.toggle("Considerar pattern", value=False)

    row2_col1, row2_col2, row2_col3 = st.columns([1.4, 1.4, 1.1])
    with row2_col1:
        update_mode_label = st.selectbox("Modo de atualizacao", options=list(UPDATE_MODES.keys()))
        update_mode = UPDATE_MODES[update_mode_label]
    with row2_col2:
        margem_float = (
            st.number_input("Margem float", min_value=0.001, max_value=0.5, value=0.01, step=0.005, format="%.3f")
            if considerar_float
            else 0.01
        )
    with row2_col3:
        st.markdown("<div style='height: 30px'></div>", unsafe_allow_html=True)
        if st.button("Atualizar precos", type="primary", use_container_width=True):
            _atualizar_precos(data, provider_escolhido, update_mode, considerar_float, margem_float, considerar_pattern)
            data = carregar_dados()

    st.caption("Atualizacao segura: por padrao, o app prioriza itens pendentes e antigos para reduzir chamadas desnecessarias.")

    st.divider()
    _metricas_resumo(data.skins, data.config.iof_percentual)
    st.divider()

    if data.skins:
        with st.expander("Filtros da carteira", expanded=False):
            fc1, fc2, fc3, fc4 = st.columns(4)
            tipos = sorted({s.tipo for s in data.skins})
            tipo_filtro = fc1.multiselect("Tipo", tipos, default=tipos)
            plataformas = sorted({s.plataforma for s in data.skins if s.plataforma})
            plat_filtro = fc2.multiselect("Plataforma", plataformas, default=plataformas)
            status_filtro = fc3.multiselect(
                "Status do preco",
                ["Ao vivo", "Cache", "Cache expirado", "Sem preco"],
                default=["Ao vivo", "Cache", "Cache expirado", "Sem preco"],
            )
            confiancas = sorted({s.preco_confianca for s in data.skins if s.preco_confianca})
            confianca_filtro = fc4.multiselect("Confianca", confiancas, default=confiancas or [])

            filtradas = [
                s
                for s in data.skins
                if s.tipo in tipo_filtro
                and s.plataforma in plat_filtro
                and _status_label(s) in status_filtro
                and (not confianca_filtro or s.preco_confianca in confianca_filtro or not s.preco_confianca)
            ]

        _render_vitrine_compacta(filtradas, data.config.iof_percentual)
        st.divider()
        _render_tabela(filtradas, data.config.iof_percentual)
        _render_galeria(filtradas)

    _secao_editar(data)
    _secao_remover(data)
