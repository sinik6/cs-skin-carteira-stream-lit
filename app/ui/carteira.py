"""Pagina Carteira - exibe o portfolio completo de skins."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from app.config import DESGASTES, PLATAFORMAS, PRICE_PROVIDERS, TIPOS_ITEM
from app.models import AppData, Skin
from app.services.price_providers.base import PriceResult
from app.services.price_service import PriceService
from app.services.storage import atualizar_skin, carregar_dados, remover_skin, salvar_dados

PROVIDER_LABELS = {
    "steam": "Steam Market",
    "csfloat": "CSFloat",
}


def _format_datetime(value: str) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%d/%m %H:%M")
    except ValueError:
        return value


def _badge_status(value: str) -> str:
    mapping = {
        "Ao vivo": "● Ao vivo",
        "Cache": "● Cache",
        "Cache expirado": "● Cache expirado",
        "Sem preco": "● Sem preco",
    }
    return mapping.get(value, value)


def _badge_confianca(value: str) -> str:
    mapping = {
        "Alta": "Alta",
        "Media": "Media",
        "Baixa": "Baixa",
    }
    return mapping.get(value, value or "-")


def _aplicar_resultado_preco(skin: Skin, result: PriceResult) -> None:
    skin.preco_atual = result.preco if result.sucesso else skin.preco_atual
    skin.preco_provider = result.provider
    skin.preco_metodo = result.metodo
    skin.preco_amostra = result.amostra
    skin.preco_confianca = result.confianca
    skin.preco_cache_hit = result.cache_hit
    skin.preco_stale = result.stale
    skin.preco_atualizado_em = result.atualizado_em


def _hero(iof_percentual: float) -> None:
    st.markdown(
        f"""
        <div style="
            padding: 1.1rem 1.2rem;
            margin-bottom: 1rem;
            border-radius: 18px;
            background: linear-gradient(135deg, rgba(32,49,66,0.96), rgba(59,85,110,0.92));
            color: #f7fbff;
            box-shadow: 0 22px 42px rgba(32,49,66,0.18);
        ">
            <div style="font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.74;">Carteira</div>
            <div style="font-size: 1.85rem; font-weight: 800; margin-top: 0.2rem;">Visao consolidada do inventario</div>
            <div style="font-size: 0.98rem; opacity: 0.82; margin-top: 0.35rem;">
                A tabela abaixo combina valor atual, metodo da estimativa e nivel de confianca. IOF aplicado na exibicao: {iof_percentual:.2f}%.
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


def _tabela_skins(skins: list[Skin], iof_percentual: float) -> None:
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
                "StatTrak": skin.stattrak,
                "Plataforma": skin.plataforma,
                "Status": _badge_status(skin.status_preco()),
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
        if "Ao vivo" in str(val):
            return "color: #067647; font-weight: 700"
        if "Cache expirado" in str(val):
            return "color: #b54708; font-weight: 700"
        if "Cache" in str(val):
            return "color: #175cd3; font-weight: 700"
        if "Sem preco" in str(val):
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


def _atualizar_precos(
    data: AppData,
    provider_escolhido: str,
    considerar_float: bool = False,
    margem_float: float = 0.01,
    considerar_pattern: bool = False,
) -> None:
    if not data.skins:
        st.warning("Nenhuma skin para atualizar.")
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

    st.info("Buscando precos com cache persistente e fallback seguro.")
    progress = st.progress(0, text="Iniciando...")
    erros = []

    def on_progress(atual: int, total: int, nome: str) -> None:
        progress.progress(atual / total, text=f"({atual}/{total}) {nome}")

    resultados = svc.buscar_precos_lote(data.skins, on_progress=on_progress)

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

    _hero(data.config.iof_percentual)

    col1, col2, col3, col4, col5 = st.columns([2.1, 1.2, 1.2, 1.5, 1.4])
    with col1:
        provider_escolhido = st.selectbox(
            "Provider base",
            options=PRICE_PROVIDERS,
            index=PRICE_PROVIDERS.index(data.config.provider_preferido)
            if data.config.provider_preferido in PRICE_PROVIDERS
            else 0,
            format_func=lambda x: PROVIDER_LABELS.get(x, x),
        )
    with col2:
        considerar_float = st.toggle("Considerar float", value=False)
    with col3:
        considerar_pattern = st.toggle("Considerar pattern", value=False)
    with col4:
        margem_float = (
            st.number_input("Margem float", min_value=0.001, max_value=0.5, value=0.01, step=0.005, format="%.3f")
            if considerar_float
            else 0.01
        )
    with col5:
        st.markdown("<div style='height: 30px'></div>", unsafe_allow_html=True)
        if st.button("Atualizar precos", type="primary", use_container_width=True):
            _atualizar_precos(data, provider_escolhido, considerar_float, margem_float, considerar_pattern)
            data = carregar_dados()

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
                and s.status_preco() in status_filtro
                and (not confianca_filtro or s.preco_confianca in confianca_filtro or not s.preco_confianca)
            ]

        _tabela_skins(filtradas, data.config.iof_percentual)

    _secao_editar(data)
    _secao_remover(data)
