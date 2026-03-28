"""Pagina Adicionar Skin - formulario para cadastro de novas skins."""

from __future__ import annotations

import streamlit as st

from app.config import DESGASTES, PLATAFORMAS, TIPOS_ITEM
from app.models import Skin
from app.services.price_service import PriceService
from app.services.storage import adicionar_skin, carregar_dados


def render() -> None:
    st.header("Adicionar Skin")

    data = carregar_dados()

    with st.form("form_add_skin", clear_on_submit=True):
        st.subheader("Informacoes do Item")

        col1, col2 = st.columns(2)
        nome = col1.text_input("Nome do Item *", placeholder="Ex: AK-47 | Slate")
        tipo = col2.selectbox("Tipo *", TIPOS_ITEM)

        col3, col4, col5 = st.columns(3)
        desgaste = col3.selectbox("Desgaste", DESGASTES, index=5)
        float_val = col4.number_input("Float Value", min_value=0.0, max_value=1.0, value=0.0, format="%.6f")
        stattrak = col5.selectbox("StatTrak", ["Nao", "Sim", "N/A"])

        col6, col7 = st.columns(2)
        pattern = col6.text_input("Pattern / Seed", placeholder="Ex: 661, N/A")
        market_hash = col7.text_input(
            "Market Hash Name (opcional)",
            placeholder="Nome exato no marketplace",
            help="Se vazio, sera gerado automaticamente a partir do nome e desgaste.",
        )

        st.divider()
        st.subheader("Informacoes de Compra")

        col8, col9, col10 = st.columns(3)
        plataforma = col8.selectbox("Plataforma de Compra", PLATAFORMAS)
        preco_compra = col9.number_input("Preco de Compra (R$)", min_value=0.0, value=0.0, format="%.2f")
        iof = col10.selectbox("IOF Aplicavel?", ["Sim", "Nao"], index=0)

        notas = st.text_area("Notas", placeholder="Observacoes opcionais")
        buscar_preco = st.checkbox("Buscar preco atual automaticamente apos salvar", value=True)
        submitted = st.form_submit_button("Salvar Skin", type="primary", use_container_width=True)

    if submitted:
        if not nome.strip():
            st.error("O nome do item e obrigatorio.")
            return

        skin = Skin(
            nome=nome.strip(),
            tipo=tipo,
            desgaste=desgaste,
            float_value=float_val,
            stattrak=stattrak,
            pattern_seed=pattern.strip(),
            plataforma=plataforma,
            preco_compra=preco_compra,
            iof_aplicavel=(iof == "Sim"),
            notas=notas.strip(),
            market_hash_name=market_hash.strip(),
        )

        if buscar_preco:
            with st.spinner("Buscando preco atual..."):
                svc = PriceService(data.config)
                resultado = svc.buscar_preco(skin)

                if resultado.sucesso:
                    skin.preco_atual = resultado.preco
                    skin.preco_provider = resultado.provider
                    skin.preco_metodo = resultado.metodo
                    skin.preco_amostra = resultado.amostra
                    skin.preco_confianca = resultado.confianca
                    skin.preco_cache_hit = resultado.cache_hit
                    skin.preco_stale = resultado.stale
                    skin.preco_atualizado_em = resultado.atualizado_em

                    st.success(f"Preco encontrado via **{resultado.provider}**: R$ {resultado.preco:.2f}")
                    if resultado.metodo:
                        st.caption(
                            f"Metodo: {resultado.metodo} | Amostra: {resultado.amostra or '-'} | Confianca: {resultado.confianca or '-'}"
                        )
                else:
                    st.warning(f"Nao foi possivel buscar o preco: {resultado.erro}")

        adicionar_skin(skin)
        st.success(f"**{skin.nome}** adicionada com sucesso!")

        total_iof = skin.total_com_iof_com_taxa(data.config.iof_percentual)
        st.info(
            f"Compra: R$ {skin.preco_compra:.2f} -> "
            f"c/ IOF: R$ {total_iof:.2f} -> "
            f"Atual: R$ {skin.preco_atual:.2f}"
        )

    with st.expander("Dicas de preenchimento", expanded=False):
        st.markdown(
            """
**Market Hash Name** e o nome exato do item no marketplace.
Se voce nao preencher, o sistema gera automaticamente baseado no nome e desgaste.

**Pattern / Seed** faz mais diferenca em skins especiais. Em itens comuns, o app tende a confiar mais no float e nos comparaveis de mercado.

**IOF** pode ser alterado em Configuracoes e a exibicao da carteira usa o valor configurado.
            """
        )
