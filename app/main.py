"""Ponto de entrada da aplicacao CS2 Skin Tracker."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st

from app.config import APP_ICON, APP_NAME
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
    padding-top: 1.8rem;
    padding-bottom: 2rem;
    max-width: 1480px;
}

[data-testid="stMetric"] {
    background: rgba(255, 255, 255, 0.84);
    border: 1px solid rgba(44, 62, 80, 0.08);
    border-radius: 18px;
    padding: 1rem 1.1rem;
    box-shadow: 0 14px 34px rgba(44, 62, 80, 0.08);
}

[data-testid="stMetricLabel"] {
    font-weight: 700;
    color: #53667b;
}

[data-testid="stMetricValue"] {
    font-size: 1.7rem;
    font-weight: 800;
    color: #13212f;
}

[data-testid="stMetricDelta"] {
    font-weight: 700;
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
.stToggle label {
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

[data-testid="stSidebar"] * {
    color: #f4f7fb !important;
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
    importar_seed_data(seed)
    _inject_global_styles()


def _sidebar_nav() -> str:
    """Renderiza o menu lateral e retorna a pagina selecionada."""
    with st.sidebar:
        st.title(f"{APP_ICON} {APP_NAME}")
        st.caption("Carteira visual para acompanhar preco, lucro e qualidade da estimativa.")
        st.divider()

        pages = {
            "Carteira": "Carteira",
            "Inventario": "Inventario",
            "Adicionar Skin": "Adicionar Skin",
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
    elif pagina == "Adicionar Skin":
        from app.ui.adicionar import render

        render()
    elif pagina == "Configuracoes":
        from app.ui.configuracoes import render

        render()


if __name__ == "__main__":
    main()
