"""Pagina Configuracoes - gerencia API keys e preferencias."""

from __future__ import annotations

import streamlit as st

from app.config import PRICE_PROVIDERS
from app.models import ApiConfig
from app.services.runtime_state import get_provider_state, load_price_cache
from app.services.storage import carregar_dados, salvar_dados


def render() -> None:
    """Renderiza a pagina de configuracoes."""
    st.header("Configuracoes")

    data = carregar_dados()
    cfg = data.config

    st.subheader("API Keys")

    with st.form("form_api_keys"):
        st.markdown("Configure as chaves e o comportamento seguro de busca de precos.")

        csfloat_key = st.text_input(
            "CSFloat API Key",
            value=cfg.csfloat_api_key,
            type="password",
            help="Obtenha em: https://csfloat.com/developers",
        )

        steam_enabled = st.toggle(
            "Permitir Steam Market como fallback",
            value=cfg.steam_enabled,
            help="Se desligado, o app usa apenas providers com API configurada.",
        )

        provider = st.selectbox(
            "Provider preferido",
            options=PRICE_PROVIDERS,
            index=PRICE_PROVIDERS.index(cfg.provider_preferido)
            if cfg.provider_preferido in PRICE_PROVIDERS
            else 0,
            format_func=lambda x: {
                "steam": "Steam Market",
                "csfloat": "CSFloat",
            }[x],
        )

        submitted_keys = st.form_submit_button("Salvar API Keys", type="primary")

    if submitted_keys:
        cfg.csfloat_api_key = csfloat_key.strip()
        cfg.steam_enabled = steam_enabled
        cfg.provider_preferido = "csfloat" if cfg.csfloat_api_key else provider
        salvar_dados(data)
        st.success("API Keys salvas com sucesso.")

    st.divider()

    st.subheader("Taxa IOF")

    with st.form("form_iof"):
        iof = st.number_input(
            "IOF (%)",
            min_value=0.0,
            max_value=50.0,
            value=cfg.iof_percentual,
            step=0.01,
            format="%.2f",
            help="Taxa IOF para compras internacionais com cartao.",
        )

        submitted_iof = st.form_submit_button("Salvar IOF")

    if submitted_iof:
        cfg.iof_percentual = iof
        salvar_dados(data)
        st.success(f"IOF atualizado para {iof:.2f}%")

    st.divider()

    st.subheader("Status dos Providers")

    col1, col2 = st.columns(2)

    with col1:
        steam_state = get_provider_state("steam")
        st.markdown("**Steam Market**")
        if cfg.steam_enabled:
            st.markdown("Ativado como fallback")
        else:
            st.markdown("Desligado")
        if steam_state.cooldown_until_ts > 0:
            st.caption("Cooldown automatico e protecao contra falhas repetidas habilitados.")
        else:
            st.caption("Rate limit conservador e cache persistente ativos.")

    with col2:
        st.markdown("**CSFloat**")
        if cfg.csfloat_api_key:
            st.markdown("Configurado")
        else:
            st.markdown("API key nao configurada")
        st.caption("Fonte principal quando a API key estiver presente.")

    st.divider()

    with st.expander("Como funciona o modo seguro", expanded=False):
        st.markdown(
            """
- O app prioriza CSFloat sempre que existir API key.
- O Steam fica como fallback opcional.
- Precos ficam em cache persistente para evitar chamadas repetidas.
- Falhas repetidas no Steam ativam cooldown automatico.
- O cambio USD/BRL tambem fica em cache.
            """
        )

    st.divider()
    st.subheader("Dados")

    col_a, col_b = st.columns(2)
    with col_a:
        st.metric("Skins cadastradas", len(data.skins))

    with col_b:
        total = sum(s.total_com_iof for s in data.skins)
        st.metric("Investimento total", f"R$ {total:,.2f}")

    st.caption(f"Entradas no cache persistente: {len(load_price_cache())}")

    if st.button("Limpar TODOS os dados", type="secondary"):
        st.warning("Tem certeza? Esta acao e irreversivel.")
        if st.button("Confirmar exclusao total", type="secondary"):
            from app.models import AppData

            salvar_dados(AppData(config=cfg))
            st.success("Todos os dados foram removidos.")
            st.rerun()
