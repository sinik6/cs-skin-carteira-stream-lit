"""Ponto de entrada da aplicacao CS2 Skin Tracker."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st

from app.config import APP_ICON, APP_NAME
from app.services.db import initialize_database, seed_asset_catalog, seed_weekly_price_cache
from app.services.storage import importar_seed_data


def _inject_global_styles() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Plus Jakarta Sans', sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at top left, rgba(44, 62, 80, 0.08), transparent 28%),
        linear-gradient(180deg, #f8fafc 0%, #eef3f7 100%);
}

.block-container {
    padding-top: 1rem;
    padding-bottom: 1.25rem;
    padding-left: 1rem;
    padding-right: 1rem;
    max-width: 100%;
}

.app-hero {
    padding: 1rem 1.1rem;
    margin-top: 0.35rem;
    margin-bottom: 1rem;
    border-radius: 18px;
    background: linear-gradient(135deg, rgba(32,49,66,0.96), rgba(59,85,110,0.92));
    color: #f7fbff;
    box-shadow: 0 18px 36px rgba(32,49,66,0.16);
}

.app-hero-eyebrow {
    font-size: 0.84rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.74;
}

.app-hero-title {
    font-size: 1.72rem;
    font-weight: 800;
    margin-top: 0.18rem;
}

.app-hero-copy {
    font-size: 0.95rem;
    opacity: 0.82;
    margin-top: 0.28rem;
    line-height: 1.45;
}

.app-chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin-top: 0.75rem;
}

.app-chip {
    display: inline-flex;
    align-items: center;
    padding: 0.28rem 0.6rem;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.12);
    color: #f7fbff;
    font-size: 0.8rem;
    font-weight: 700;
}

.compare-identity {
    border-radius: 18px;
    border: 1px solid rgba(37, 61, 84, 0.10);
    background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(244,248,252,0.94));
    box-shadow: 0 16px 32px rgba(31, 52, 73, 0.08);
    padding: 1rem;
    min-height: 220px;
}

.compare-identity-head {
    display: flex;
    align-items: center;
    gap: 0.9rem;
    margin-bottom: 0.9rem;
}

.compare-logo {
    width: 72px;
    height: 72px;
    border-radius: 20px;
    overflow: hidden;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.22), 0 10px 18px rgba(31,52,73,0.16);
    flex-shrink: 0;
}

.compare-identity-eyebrow {
    color: #58708a;
    font-size: 0.76rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

.compare-identity-title {
    color: #122131;
    font-size: 1.18rem;
    font-weight: 800;
    line-height: 1.15;
    margin-top: 0.12rem;
}

.compare-identity-subtitle {
    color: #5c6f82;
    font-size: 0.86rem;
    margin-top: 0.2rem;
}

.compare-chip-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-top: 0.75rem;
}

.compare-chip {
    display: inline-flex;
    align-items: center;
    padding: 0.32rem 0.6rem;
    border-radius: 999px;
    background: rgba(27, 51, 72, 0.08);
    color: #1a3044;
    font-size: 0.78rem;
    font-weight: 700;
}

.compare-detail-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.55rem 0.8rem;
    margin-top: 0.95rem;
}

.compare-detail-item {
    border-radius: 12px;
    background: rgba(239, 244, 248, 0.88);
    padding: 0.58rem 0.68rem;
}

.compare-detail-label {
    color: #6a7d90;
    font-size: 0.74rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.compare-detail-value {
    color: #122131;
    font-size: 0.95rem;
    font-weight: 800;
    margin-top: 0.16rem;
}

[data-testid="stMetric"] {
    background: rgba(255, 255, 255, 0.84);
    border: 1px solid rgba(44, 62, 80, 0.08);
    border-radius: 14px;
    padding: 0.6rem 0.8rem;
    box-shadow: 0 10px 24px rgba(44, 62, 80, 0.07);
    min-height: 104px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
}

[data-testid="stMetricLabel"] {
    font-weight: 700;
    color: #53667b;
    font-size: 0.88rem;
    min-height: 2.1rem;
    display: flex;
    align-items: flex-start;
}

[data-testid="stMetricValue"] {
    font-size: 1.12rem;
    font-weight: 800;
    color: #13212f;
    line-height: 1.15;
    min-height: 2rem;
    display: flex;
    align-items: center;
}

[data-testid="stMetricDelta"] {
    font-weight: 700;
    font-size: 0.9rem;
    min-height: 1.2rem;
    display: flex;
    align-items: center;
}

.stButton > button {
    border-radius: 12px;
    min-height: 2.8rem;
    font-weight: 700;
}

.stTextInput input,
.stNumberInput input,
.stTextArea textarea,
.stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"] > div {
    background: rgba(232, 239, 246, 0.92) !important;
    border: 1px solid rgba(31, 52, 73, 0.14) !important;
    border-radius: 12px !important;
    color: #13212f !important;
}

.stTextInput input::placeholder,
.stTextArea textarea::placeholder {
    color: #66788a !important;
}

.stTextInput input:focus,
.stNumberInput input:focus,
.stTextArea textarea:focus {
    border-color: rgba(44, 62, 80, 0.34) !important;
    box-shadow: 0 0 0 1px rgba(44, 62, 80, 0.22) !important;
}

[data-baseweb="tag"] {
    background: rgba(32, 49, 66, 0.12) !important;
    color: #203142 !important;
}

.stSelectbox label,
.stMultiSelect label,
.stNumberInput label,
.stTextInput label,
.stTextArea label,
.stToggle label,
.stCheckbox label {
    font-weight: 700 !important;
    color: #33485e !important;
}

[data-testid="stExpander"] {
    border: 1px solid rgba(44, 62, 80, 0.08);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.74);
    box-shadow: 0 10px 28px rgba(44, 62, 80, 0.05);
}

[data-testid="stAlert"] {
    border-radius: 14px;
    border: 1px solid rgba(31, 52, 73, 0.08);
}

[data-testid="stDataFrame"] {
    border: 1px solid rgba(44, 62, 80, 0.08);
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 18px 40px rgba(44, 62, 80, 0.08);
    background: rgba(255, 255, 255, 0.88);
}

[data-testid="stVerticalBlock"] [data-testid="stImage"] img {
    transition: transform 180ms ease, box-shadow 180ms ease, filter 180ms ease;
    border-radius: 14px;
}

[data-testid="stVerticalBlock"] [data-testid="stImage"] img:hover {
    transform: translateY(-3px) scale(1.018);
    box-shadow: 0 16px 28px rgba(32, 49, 66, 0.18);
    filter: saturate(1.06) contrast(1.02);
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #203142 0%, #31475d 100%);
}

[data-testid="stSidebar"][aria-expanded="true"] {
    min-width: 14rem;
    max-width: 14rem;
}

[data-testid="stSidebar"] * {
    color: #f4f7fb !important;
}

[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] p {
    font-size: 0.9rem !important;
}

[data-testid="stSidebar"] h1 {
    font-size: 1.16rem !important;
    margin-bottom: 0.25rem !important;
}

@media (max-width: 1100px) {
    [data-testid="stSidebar"][aria-expanded="true"] {
        min-width: 12.5rem;
        max-width: 12.5rem;
    }
}

@media (prefers-reduced-motion: reduce) {
    [data-testid="stVerticalBlock"] [data-testid="stImage"] img {
        transition: none !important;
        transform: none !important;
    }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _setup_page() -> None:
    """Configuracoes iniciais do Streamlit."""
    st.set_page_config(
        page_title=APP_NAME,
        page_icon=APP_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )

    seed = Path(__file__).parent / "data" / "seed.json"
    asset_seed = Path(__file__).parent / "data" / "asset_seed.json"
    asset_weekly_seed = Path(__file__).parent / "data" / "asset_weekly_seed.json"
    importar_seed_data(seed)
    initialize_database()
    seed_asset_catalog(asset_seed)
    seed_weekly_price_cache(asset_weekly_seed)
    _inject_global_styles()


def _sidebar_nav() -> str:
    """Renderiza o menu lateral e retorna a pagina selecionada."""
    with st.sidebar:
        st.title(f"{APP_ICON} {APP_NAME}")
        st.caption("Acompanhe precos, lucro e a qualidade das estimativas.")
        st.divider()

        pages = {
            "Carteira": "Carteira",
            "Inventario": "Inventario",
            "Comparador": "Comparador",
            "Adicionar Skin": "Adicionar Skin",
            "Adicionar Ativo": "Adicionar Ativo",
            "Configuracoes": "Configuracoes",
        }

        pagina = st.radio(
            "Navegacao",
            options=list(pages.keys()),
            label_visibility="collapsed",
        )

        st.divider()
        st.caption("CS2 Skin Tracker v1.0")
        st.caption("Precos via Steam Market / CSFloat")

    return pages[pagina]


def main() -> None:
    """Funcao principal da aplicacao."""
    _setup_page()
    pagina = _sidebar_nav()

    if pagina == "Carteira":
        from app.ui.carteira import render

        render()
    elif pagina == "Inventario":
        from app.ui.inventario import render

        render()
    elif pagina == "Comparador":
        from app.ui.comparador import render

        render()
    elif pagina == "Adicionar Skin":
        from app.ui.adicionar import render

        render()
    elif pagina == "Adicionar Ativo":
        from app.ui.adicionar_ativo import render

        render()
    elif pagina == "Configuracoes":
        from app.ui.configuracoes import render

        render()


if __name__ == "__main__":
    main()
