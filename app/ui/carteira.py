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


def _format_currency(value: float) -> str:
    return f"R$ {value:,.2f}"


def _format_pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


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

    st.markdown("### Miniaturas da carteira")
    controles_1, controles_2, controles_3 = st.columns([1.15, 1.05, 1.8])
    with controles_1:
        exibir_vitrine = st.toggle("Exibir miniaturas", value=True, key="vitrine_exibir")
    total_paginas = max(1, (len(skins_com_imagem) - 1) // THUMBNAIL_PAGE_SIZE + 1)
    with controles_2:
        pagina = st.number_input(
            "Pagina",
            min_value=1,
            max_value=total_paginas,
            value=1,
            step=1,
            key="vitrine_pagina",
        )
    with controles_3:
        st.caption("Exibe apenas os itens visiveis da pagina atual e usa cache local seguro para manter a carteira leve.")

    if not exibir_vitrine:
        st.info("A galeria de miniaturas esta desativada nesta sessao.")
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
                lucro = skin.lucro_com_taxa(iof_percentual)
                variacao = skin.variacao_pct_com_taxa(iof_percentual) * 100

                with st.container(border=True):
                    if image_path:
                        st.image(image_path, use_container_width=True)
                    else:
                        st.caption("Miniatura indisponivel no modo seguro")
                    st.markdown(f"**{skin.nome}**")
                    st.caption(f"{skin.tipo} | {skin.desgaste}")
                    st.markdown(
                        f"""
                        <div style="margin-top: 0.35rem;">
                            <div style="display: flex; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.25rem;">
                                <div>
                                    <div style="font-size: 0.72rem; color: #6b7b8c; text-transform: uppercase; letter-spacing: 0.04em;">Compra</div>
                                    <div style="font-size: 0.95rem; font-weight: 700; color: #31475d;">R$ {skin.preco_compra:.2f}</div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-size: 0.72rem; color: #6b7b8c; text-transform: uppercase; letter-spacing: 0.04em;">Atual</div>
                                    <div style="font-size: 1.02rem; font-weight: 800; color: #13212f;">R$ {skin.preco_atual:.2f}</div>
                                </div>
                            </div>
                            <div style="display: flex; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.45rem;">
                                <div>
                                    <div style="font-size: 0.72rem; color: #6b7b8c; text-transform: uppercase; letter-spacing: 0.04em;">Lucro</div>
                                    <div style="font-size: 0.92rem; font-weight: 700; color: {'#067647' if lucro >= 0 else '#b42318'};">R$ {lucro:.2f}</div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-size: 0.72rem; color: #6b7b8c; text-transform: uppercase; letter-spacing: 0.04em;">Variacao</div>
                                    <div style="font-size: 0.92rem; font-weight: 700; color: {'#067647' if variacao >= 0 else '#b42318'};">{variacao:+.1f}%</div>
                                </div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )


def _hero(data: AppData) -> None:
    pendentes = sum(1 for skin in data.skins if skin.preco_atual <= 0)
    antigos = sum(1 for skin in data.skins if skin.preco_atual > 0 and _is_stale(skin))
    avaliadas = sum(1 for skin in data.skins if skin.preco_atual > 0)
    monitoradas = len(data.skins)

    st.markdown(
        f"""
        <div class="app-hero">
            <div class="app-hero-eyebrow">Carteira</div>
            <div class="app-hero-title">Mesa de investimento em skins CS2</div>
            <div class="app-hero-copy">
                Acompanhe patrimonio, concentracao, liquidez e qualidade das estimativas da sua carteira de skins sem abrir mao do modo seguro de consulta.
            </div>
            <div class="app-chip-row">
                <span class="app-chip">Carteira monitorada: {monitoradas}</span>
                <span class="app-chip">Com preco: {avaliadas}</span>
                <span class="app-chip">IOF: {data.config.iof_percentual:.2f}%</span>
                <span class="app-chip">Pendentes: {pendentes}</span>
                <span class="app-chip">Antigos: {antigos}</span>
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
    media_compra = total_investido / len(skins) if skins else 0.0
    skins_com_preco = [s for s in skins if s.preco_atual > 0]
    media_atual = (
        sum(s.preco_atual for s in skins_com_preco) / len(skins_com_preco)
        if skins_com_preco
        else 0.0
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Itens", len(skins))
    c2.metric("Investido", f"R$ {total_investido:,.2f}")
    c3.metric("Valor Atual", f"R$ {valor_atual:,.2f}")
    c4.metric("Lucro / Prejuizo", f"R$ {lucro_total:,.2f}", delta=f"{variacao:+.1f}%")
    c5.metric("Ticket Medio", f"R$ {media_compra:,.2f}")
    c6.metric("Media Atual", f"R$ {media_atual:,.2f}")

    if not skins_com_preco:
        st.caption("Preco medio atual fica disponivel assim que pelo menos um item tiver preco buscado.")


def _build_portfolio_dataframe(skins: list[Skin], iof_percentual: float) -> pd.DataFrame:
    rows = []
    for skin in skins:
        compra_total = skin.total_com_iof_com_taxa(iof_percentual)
        lucro = skin.lucro_com_taxa(iof_percentual)
        variacao = skin.variacao_pct_com_taxa(iof_percentual)
        rows.append(
            {
                "id": skin.id,
                "nome": skin.nome,
                "tipo": skin.tipo,
                "desgaste": skin.desgaste,
                "plataforma": skin.plataforma or "Nao informado",
                "status": _status_label(skin),
                "fonte": skin.preco_provider or "-",
                "metodo": skin.preco_metodo or "-",
                "amostra": skin.preco_amostra if skin.preco_amostra else 0,
                "confianca": skin.preco_confianca or "-",
                "atualizado": _format_datetime(skin.preco_atualizado_em),
                "compra": skin.preco_compra,
                "compra_total": compra_total,
                "atual": skin.preco_atual,
                "lucro": lucro,
                "variacao": variacao,
                "peso_atual": 0.0,
                "peso_investido": 0.0,
                "float_value": skin.float_value,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    total_atual = float(df["atual"].sum())
    total_investido = float(df["compra_total"].sum())
    if total_atual > 0:
        df["peso_atual"] = df["atual"] / total_atual
    if total_investido > 0:
        df["peso_investido"] = df["compra_total"] / total_investido
    return df


def _render_dashboard_analitico(skins: list[Skin], iof_percentual: float) -> None:
    df = _build_portfolio_dataframe(skins, iof_percentual)
    if df.empty:
        return

    total_atual = float(df["atual"].sum())
    total_investido = float(df["compra_total"].sum())
    sem_preco = int((df["atual"] <= 0).sum())
    cache_expirado = int((df["status"] == "Cache expirado").sum())
    peso_maior = float(df["peso_atual"].max()) if total_atual > 0 else 0.0
    maior_posicao = df.sort_values("atual", ascending=False).iloc[0]
    lucro_positivo = int((df["lucro"] > 0).sum())
    lucro_negativo = int((df["lucro"] < 0).sum())

    st.markdown("### Painel da carteira")
    with st.container(border=True):
        h1, h2, h3, h4, h5 = st.columns(5)
        h1.metric("Patrimonio monitorado", f"R$ {total_atual:,.2f}")
        h2.metric("Custo consolidado", f"R$ {total_investido:,.2f}")
        h3.metric("Sem preco", sem_preco)
        h4.metric("Stale", cache_expirado)
        h5.metric("Maior posicao", maior_posicao["nome"], delta=f"{peso_maior:.1%}")

    tab1, tab2, tab3 = st.tabs(["Visao Geral", "Composicao", "Ranking"])

    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Top posicoes por valor atual**")
            top_positions = (
                df[df["atual"] > 0][["nome", "atual"]]
                .sort_values("atual", ascending=False)
                .head(8)
                .set_index("nome")
            )
            if not top_positions.empty:
                st.bar_chart(top_positions)
            else:
                st.info("As maiores posicoes aparecem aqui assim que houver precos validos.")

        with col2:
            st.markdown("**Contribuicao de lucro por item**")
            profit_view = (
                df[["nome", "lucro"]]
                .sort_values("lucro", ascending=False)
                .head(8)
                .set_index("nome")
            )
            st.bar_chart(profit_view)

        with st.container(border=True):
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Itens no verde", lucro_positivo)
            s2.metric("Itens no vermelho", lucro_negativo)
            s3.metric("Cobertura de preco", f"{((len(df) - sem_preco) / len(df)):.1%}")
            s4.metric(
                "Concentracao top 3",
                f"{df.sort_values('peso_atual', ascending=False).head(3)['peso_atual'].sum():.1%}" if total_atual > 0 else "0.0%",
            )

    with tab2:
        row1_col1, row1_col2 = st.columns(2)
        with row1_col1:
            st.markdown("**Alocacao por tipo**")
            by_type = df.groupby("tipo", dropna=False)["atual"].sum().sort_values(ascending=False)
            if by_type.sum() > 0:
                st.bar_chart(by_type)
            else:
                st.info("A alocacao por tipo aparece quando a carteira tiver precos atuais.")

        with row1_col2:
            st.markdown("**Alocacao por plataforma de compra**")
            by_platform = df.groupby("plataforma", dropna=False)["compra_total"].sum().sort_values(ascending=False)
            st.bar_chart(by_platform)

        row2_col1, row2_col2 = st.columns(2)
        with row2_col1:
            st.markdown("**Distribuicao por fonte de preco**")
            by_source = df.groupby("fonte", dropna=False)["id"].count().sort_values(ascending=False)
            st.bar_chart(by_source)
        with row2_col2:
            st.markdown("**Qualidade das estimativas**")
            by_confidence = df.groupby("confianca", dropna=False)["id"].count().sort_values(ascending=False)
            st.bar_chart(by_confidence)

    with tab3:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Maiores vencedoras**")
            winners = (
                df.sort_values(["lucro", "variacao"], ascending=False)
                [["nome", "tipo", "atual", "lucro", "variacao", "peso_atual"]]
                .head(7)
            )
            st.dataframe(
                winners,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "atual": st.column_config.NumberColumn("Atual", format="R$ %.2f"),
                    "lucro": st.column_config.NumberColumn("Lucro", format="R$ %.2f"),
                    "variacao": st.column_config.NumberColumn("Variacao", format="%.2f%%"),
                    "peso_atual": st.column_config.NumberColumn("Peso", format="%.2f%%"),
                },
            )

        with c2:
            st.markdown("**Maiores pressões da carteira**")
            losers = (
                df.sort_values(["lucro", "variacao"], ascending=True)
                [["nome", "tipo", "atual", "lucro", "variacao", "peso_atual"]]
                .head(7)
            )
            st.dataframe(
                losers,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "atual": st.column_config.NumberColumn("Atual", format="R$ %.2f"),
                    "lucro": st.column_config.NumberColumn("Lucro", format="R$ %.2f"),
                    "variacao": st.column_config.NumberColumn("Variacao", format="%.2f%%"),
                    "peso_atual": st.column_config.NumberColumn("Peso", format="%.2f%%"),
                },
            )

        with st.container(border=True):
            st.markdown("**Radar de concentracao**")
            concentration = (
                df.sort_values("peso_atual", ascending=False)
                [["nome", "tipo", "peso_atual", "lucro", "status"]]
                .head(10)
            )
            st.dataframe(
                concentration,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "peso_atual": st.column_config.NumberColumn("Peso Atual", format="%.2f%%"),
                    "lucro": st.column_config.NumberColumn("Lucro", format="R$ %.2f"),
                },
            )


def _render_portfolio_brief(skins: list[Skin], iof_percentual: float) -> None:
    df = _build_portfolio_dataframe(skins, iof_percentual)
    if df.empty:
        return

    total_atual = float(df["atual"].sum())
    total_investido = float(df["compra_total"].sum())
    lucro_total = total_atual - total_investido
    cobertura = ((len(df) - int((df["atual"] <= 0).sum())) / len(df)) if len(df) else 0.0
    top3 = df.sort_values("peso_atual", ascending=False).head(3)
    top3_share = float(top3["peso_atual"].sum()) if total_atual > 0 else 0.0
    melhor = df.sort_values("variacao", ascending=False).iloc[0]
    pior = df.sort_values("variacao", ascending=True).iloc[0]

    st.markdown("### Leitura rapida da carteira")
    c1, c2 = st.columns([1.5, 1])
    with c1:
        st.markdown(
            f"""
            <div style="padding: 1rem 1.05rem; border-radius: 18px; background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(245,248,251,0.94)); border: 1px solid rgba(32,49,66,0.08); box-shadow: 0 14px 32px rgba(32,49,66,0.06);">
                <div style="font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.08em; color: #607286; font-weight: 800;">Resumo patrimonial</div>
                <div style="margin-top: 0.35rem; font-size: 1.55rem; line-height: 1.15; font-weight: 800; color: #13212f;">{_format_currency(total_atual)}</div>
                <div style="margin-top: 0.25rem; color: #4d6278; font-size: 0.94rem;">
                    Patrimonio monitorado contra custo consolidado de <strong>{_format_currency(total_investido)}</strong>,
                    com resultado total de <strong style="color: {'#067647' if lucro_total >= 0 else '#b42318'};">{_format_currency(lucro_total)}</strong>.
                </div>
                <div style="margin-top: 0.75rem; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.65rem;">
                    <div style="padding: 0.7rem 0.8rem; border-radius: 14px; background: rgba(231,236,242,0.78);">
                        <div style="font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: #607286;">Cobertura</div>
                        <div style="margin-top: 0.18rem; font-size: 1rem; font-weight: 800; color: #13212f;">{cobertura:.1%}</div>
                    </div>
                    <div style="padding: 0.7rem 0.8rem; border-radius: 14px; background: rgba(231,236,242,0.78);">
                        <div style="font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: #607286;">Top 3</div>
                        <div style="margin-top: 0.18rem; font-size: 1rem; font-weight: 800; color: #13212f;">{top3_share:.1%}</div>
                    </div>
                    <div style="padding: 0.7rem 0.8rem; border-radius: 14px; background: rgba(231,236,242,0.78);">
                        <div style="font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: #607286;">Rentabilidade</div>
                        <div style="margin-top: 0.18rem; font-size: 1rem; font-weight: 800; color: {'#067647' if lucro_total >= 0 else '#b42318'};">{((lucro_total / total_investido) if total_investido > 0 else 0.0):+.1%}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        with st.container(border=True):
            st.markdown("**Destaques do book**")
            st.caption(f"Melhor assimetria: {melhor['nome']}")
            st.write(f"Variacao: **{_format_pct(float(melhor['variacao']))}**")
            st.caption(f"Maior pressao: {pior['nome']}")
            st.write(f"Variacao: **{_format_pct(float(pior['variacao']))}**")
            st.caption("Leitura inspirada em carteira analitica, mas aplicada ao mercado de skins.")


def _render_insights(skins: list[Skin], iof_percentual: float) -> None:
    df = _build_portfolio_dataframe(skins, iof_percentual)
    if df.empty:
        return

    total_atual = float(df["atual"].sum())
    top3 = df.sort_values("peso_atual", ascending=False).head(3)
    top3_share = float(top3["peso_atual"].sum()) if total_atual > 0 else 0.0
    stale_count = int((df["status"] == "Cache expirado").sum())
    sem_preco = int((df["atual"] <= 0).sum())
    dominante_tipo = df.groupby("tipo", dropna=False)["compra_total"].sum().sort_values(ascending=False)
    dominante_fonte = df.groupby("fonte", dropna=False)["id"].count().sort_values(ascending=False)

    insights = [
        f"A carteira esta mais exposta a **{dominante_tipo.index[0]}**, que lidera o capital alocado no momento." if not dominante_tipo.empty else "",
        f"As 3 maiores posicoes concentram **{top3_share:.1%}** do valor monitorado, o que pede atencao para risco de concentracao." if top3_share > 0 else "",
        f"Existem **{stale_count}** item(ns) com cache expirado e **{sem_preco}** sem preco, reduzindo a leitura em tempo util." if stale_count or sem_preco else "A cobertura de precos esta limpa no recorte atual, sem stale relevante.",
        f"A fonte predominante das estimativas e **{dominante_fonte.index[0]}**, o que ajuda a entender a dependencia do book atual." if not dominante_fonte.empty else "",
    ]
    insights = [item for item in insights if item]

    st.markdown("### Insights da carteira")
    cols = st.columns(2)
    for idx, insight in enumerate(insights[:4]):
        with cols[idx % 2]:
            with st.container(border=True):
                st.markdown(insight)


def _render_controls_panel(data: AppData) -> tuple[str, bool, bool, str, float, bool, list[Skin]]:
    with st.container(border=True):
        st.markdown("### Gestao da carteira")
        row1_col1, row1_col2, row1_col3 = st.columns([1.8, 1.2, 1.2])
        with row1_col1:
            provider_escolhido = st.selectbox(
                "Fonte principal de preco",
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
            update_mode_label = st.selectbox("Escopo da atualizacao", options=list(UPDATE_MODES.keys()))
            update_mode = UPDATE_MODES[update_mode_label]
        with row2_col2:
            margem_float = (
                st.number_input("Margem float", min_value=0.001, max_value=0.5, value=0.01, step=0.005, format="%.3f")
                if considerar_float
                else 0.01
            )
        with row2_col3:
            st.markdown("<div style='height: 30px'></div>", unsafe_allow_html=True)
            atualizar = st.button("Atualizar valores", type="primary", use_container_width=True)

        st.caption("Atualizacao segura: o app prioriza itens pendentes e antigos para reduzir chamadas desnecessarias e preservar cooldown dos providers.")

    filtradas: list[Skin] = data.skins
    if data.skins:
        with st.expander("Filtros da carteira", expanded=False):
            fc1, fc2, fc3, fc4 = st.columns(4)
            tipos = sorted({s.tipo for s in data.skins})
            tipo_filtro = fc1.multiselect("Tipo", tipos, default=tipos)
            plataformas = sorted({s.plataforma for s in data.skins if s.plataforma})
            plat_filtro = fc2.multiselect("Plataforma", plataformas, default=plataformas)
            status_filtro = fc3.multiselect(
                "Status",
                ["Ao vivo", "Cache", "Cache expirado", "Sem preco"],
                default=["Ao vivo", "Cache", "Cache expirado", "Sem preco"],
            )
            confiancas = sorted({s.preco_confianca for s in data.skins if s.preco_confianca})
            confianca_filtro = fc4.multiselect("Qualidade", confiancas, default=confiancas or [])

            filtradas = [
                s
                for s in data.skins
                if s.tipo in tipo_filtro
                and s.plataforma in plat_filtro
                and _status_label(s) in status_filtro
                and (not confianca_filtro or s.preco_confianca in confianca_filtro or not s.preco_confianca)
            ]

    return provider_escolhido, considerar_float, considerar_pattern, update_mode, margem_float, atualizar, filtradas


def _render_tabela(skins: list[Skin], iof_percentual: float) -> None:
    if not skins:
        st.info("Nenhuma skin corresponde aos filtros.")
        return

    df = _build_portfolio_dataframe(skins, iof_percentual).rename(
        columns={
            "nome": "Nome",
            "tipo": "Tipo",
            "desgaste": "Desgaste",
            "plataforma": "Plataforma",
            "status": "Status",
            "fonte": "Fonte",
            "metodo": "Metodo",
            "amostra": "Amostra",
            "confianca": "Confianca",
            "atualizado": "Atualizado",
            "compra": "Compra",
            "compra_total": "Com IOF",
            "atual": "Atual",
            "lucro": "Lucro",
            "variacao": "Variacao",
            "peso_atual": "Peso Atual",
        }
    )
    df["Status"] = df["Status"].map(_badge_status)
    df["Confianca"] = df["Confianca"].map(_badge_confianca)
    df["Amostra"] = df["Amostra"].replace({0: "-"})
    df = df[
        [
            "Nome",
            "Tipo",
            "Desgaste",
            "Plataforma",
            "Status",
            "Fonte",
            "Metodo",
            "Amostra",
            "Confianca",
            "Atualizado",
            "Compra",
            "Com IOF",
            "Atual",
            "Peso Atual",
            "Lucro",
            "Variacao",
        ]
    ]

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
                "Peso Atual": "{:.1%}",
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

    _hero(data)
    provider_escolhido, considerar_float, considerar_pattern, update_mode, margem_float, atualizar, filtradas = _render_controls_panel(data)
    if atualizar:
        _atualizar_precos(data, provider_escolhido, update_mode, considerar_float, margem_float, considerar_pattern)
        st.rerun()
    if data.skins:
        st.divider()
        _render_portfolio_brief(filtradas, data.config.iof_percentual)
        st.divider()
        _metricas_resumo(filtradas, data.config.iof_percentual)
        st.caption("As medias seguem os filtros aplicados na carteira.")
        st.divider()
        _render_dashboard_analitico(filtradas, data.config.iof_percentual)
        _render_insights(filtradas, data.config.iof_percentual)
        st.caption("Painel com linguagem de investimento aplicada ao mercado de skins, usando apenas dados locais e consultas protegidas.")
        st.divider()

        _render_vitrine_compacta(filtradas, data.config.iof_percentual)
        st.divider()
        _render_tabela(filtradas, data.config.iof_percentual)
        _render_galeria(filtradas)
    else:
        st.divider()
        _metricas_resumo(data.skins, data.config.iof_percentual)

    _secao_editar(data)
    _secao_remover(data)
