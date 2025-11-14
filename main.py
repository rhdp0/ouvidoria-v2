import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

# ---------------------------------------------------------
# CONFIGURAÇÃO GERAL
# ---------------------------------------------------------
st.set_page_config(page_title="Dashboard Ouvidoria / Manifestações", layout="wide")

st.markdown(
    """
<style>
.block-container {padding-top: 1.5rem;}
div[data-testid="stMetricValue"] {color:#0F4C81;}
h1, h2, h3 { color:#1f2a44; }
section[data-testid="stSidebar"] {background-color:#f5f7fb}
</style>
""",
    unsafe_allow_html=True,
)

st.title("📣 Dashboard de Manifestações / Ouvidoria")
st.caption("Usando exclusivamente a aba **2025**, que contém TODOS os dados consolidados.")

DEFAULT_PATH = Path("/mnt/data/Controle de Manifestações 2025.xlsx")

# ---------------------------------------------------------
# FUNÇÕES DE NORMALIZAÇÃO E TRATAMENTO
# ---------------------------------------------------------
def _normalize_text(text: str) -> str:
    t = str(text).strip().lower()
    replacements = {
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "é": "e",
        "ê": "e",
        "í": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ú": "u",
        "ü": "u",
        "ç": "c",
    }
    for k, v in replacements.items():
        t = t.replace(k, v)
    t = re.sub(r"\s+", " ", t)
    return t


COL_CANONICAL = {
    "data": "DATA",
    "canal de comunicacao": "CANAL DE COMUNICAÇÃO",
    "tipo de chamado": "TIPO DE CHAMADO",
    "manifestacao": "MANIFESTAÇÃO",
    "registro": "REGISTRO",
    "paciente": "PACIENTE",
    "descricao do ocorrido": "DESCRIÇÃO DO OCORRIDO",
    "solicitado contato": "SOLICITADO CONTATO",
    "setor notificado": "SETOR NOTIFICADO",
    "area": "ÁREA",
    "criticidade": "CRITICIDADE",
    "data do envio ao gestor": "DATA DO ENVIO AO GESTOR",
    "prazo para retorno (dia)": "PRAZO PARA RETORNO (DIA)",
    "status": "STATUS",
    "nota": "NOTA",
    "classificacao nps": "CLASSIFICAÇÃO NPS",
    "data do retorno a ouvidoria": "DATA DO RETORNO A OUVIDORIA",
    "plano de acao": "PLANO DE AÇÃO",
    "data de retorno ao paciente": "DATA DE RETORNO AO PACIENTE",
}


def rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Renomeia colunas da planilha para nomes canônicos."""
    rename_map = {}
    norms = {_normalize_text(k): v for k, v in COL_CANONICAL.items()}
    for col in df.columns:
        n = _normalize_text(col)
        if n in norms:
            rename_map[col] = norms[n]
    df = df.rename(columns=rename_map)
    keep = [c for c in COL_CANONICAL.values() if c in df.columns]
    return df[keep].copy()


def compute_sla(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula SLA e tempos de retorno."""
    df = df.copy()

    # converter datas
    for col in [
        "DATA",
        "DATA DO ENVIO AO GESTOR",
        "DATA DO RETORNO A OUVIDORIA",
        "DATA DE RETORNO AO PACIENTE",
    ]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # prazo em dias
    df["PRAZO DIAS"] = pd.to_numeric(df.get("PRAZO PARA RETORNO (DIA)"), errors="coerce")

    # data limite
    df["DATA LIMITE GESTOR"] = df["DATA DO ENVIO AO GESTOR"] + pd.to_timedelta(
        df["PRAZO DIAS"], unit="D"
    )

    today = pd.Timestamp("today").normalize()
    sla_status = []

    for _, row in df.iterrows():
        envio = row["DATA DO ENVIO AO GESTOR"]
        retorno = row["DATA DO RETORNO A OUVIDORIA"]
        limite = row["DATA LIMITE GESTOR"]

        # sem prazo
        if pd.isna(envio) or pd.isna(limite):
            sla_status.append("Sem prazo definido")
            continue

        # resolvido
        if pd.notna(retorno):
            sla_status.append(
                "Resolvido no prazo" if retorno <= limite else "Resolvido com atraso"
            )
            continue

        # pendente
        if today <= limite:
            sla_status.append("Em andamento no prazo")
        else:
            sla_status.append("Em atraso")

    df["SLA STATUS"] = sla_status

    # tempos
    df["DIAS ATÉ RETORNO OUVIDORIA"] = (
        df["DATA DO RETORNO A OUVIDORIA"] - df["DATA"]
    ).dt.days
    df["DIAS ATÉ RETORNO PACIENTE"] = (
        df["DATA DE RETORNO AO PACIENTE"] - df["DATA"]
    ).dt.days

    return df


MONTH_NAMES = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}


def add_date_parts(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ANO"] = df["DATA"].dt.year
    df["MES"] = df["DATA"].dt.month
    df["MES_NOME"] = df["MES"].map(MONTH_NAMES)
    return df


def add_nps_group(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["NOTA_NUM"] = pd.to_numeric(df.get("NOTA"), errors="coerce")
    df["NPS GRUPO"] = np.where(
        df["NOTA_NUM"] >= 9,
        "Promotor",
        np.where(
            df["NOTA_NUM"] >= 7,
            "Neutro",
            np.where(df["NOTA_NUM"] <= 6, "Detrator", np.nan),
        ),
    )
    return df


# ---------------------------------------------------------
# CARREGAR APENAS A ABA 2025
# ---------------------------------------------------------
def load_tab_2025(file_like) -> pd.DataFrame:
    try:
        xls = pd.ExcelFile(file_like)
    except Exception as e:
        st.error(f"Erro ao abrir arquivo: {e}")
        return pd.DataFrame()

    if "2025" not in xls.sheet_names:
        st.error("A aba '2025' não foi encontrada no arquivo enviado.")
        return pd.DataFrame()

    df = xls.parse("2025")
    df = rename_columns(df)
    if df.empty:
        return df

    df = compute_sla(df)
    df = add_date_parts(df)
    df = add_nps_group(df)
    return df


# ---------------------------------------------------------
# SIDEBAR – UPLOAD
# ---------------------------------------------------------
st.sidebar.header("📂 Fonte de Dados")

uploaded = st.sidebar.file_uploader("Envie o Excel com a aba '2025'", type=["xlsx"])

if uploaded:
    df = load_tab_2025(uploaded)
    fonte = "Upload do usuário"
elif DEFAULT_PATH.exists():
    df = load_tab_2025(DEFAULT_PATH)
    fonte = f"Arquivo padrão: {DEFAULT_PATH.name}"
else:
    st.error("Nenhum arquivo encontrado e nenhum upload foi enviado.")
    st.stop()

if df.empty:
    st.error("A aba 2025 não possui dados válidos.")
    st.stop()

st.sidebar.success(f"Usando dados: {fonte}")

# ---------------------------------------------------------
# FILTROS
# ---------------------------------------------------------
st.sidebar.header("🔎 Filtros")

anos = sorted(df["ANO"].dropna().unique().tolist())
meses = [m for m in MONTH_NAMES.values() if m in df["MES_NOME"].dropna().unique()]

sel_anos = st.sidebar.multiselect("Ano", anos, default=anos)
sel_meses = st.sidebar.multiselect("Mês", meses, default=meses)

canais_unicos = sorted(df["CANAL DE COMUNICAÇÃO"].dropna().unique().tolist())
tipos_unicos = sorted(df["TIPO DE CHAMADO"].dropna().unique().tolist())
crit_unicas = sorted(df["CRITICIDADE"].dropna().unique().tolist())
setores_unicos = sorted(df["SETOR NOTIFICADO"].dropna().unique().tolist())

sel_canais = st.sidebar.multiselect("Canal", canais_unicos)
sel_tipos = st.sidebar.multiselect("Tipo de Chamado", tipos_unicos)
sel_crit = st.sidebar.multiselect("Criticidade", crit_unicas)
sel_setor = st.sidebar.multiselect("Setor", setores_unicos)

fdf = df.copy()

if sel_anos:
    fdf = fdf[fdf["ANO"].isin(sel_anos)]
if sel_meses:
    fdf = fdf[fdf["MES_NOME"].isin(sel_meses)]
if sel_canais:
    fdf = fdf[fdf["CANAL DE COMUNICAÇÃO"].isin(sel_canais)]
if sel_tipos:
    fdf = fdf[fdf["TIPO DE CHAMADO"].isin(sel_tipos)]
if sel_crit:
    fdf = fdf[fdf["CRITICIDADE"].isin(sel_crit)]
if sel_setor:
    fdf = fdf[fdf["SETOR NOTIFICADO"].isin(sel_setor)]

if fdf.empty:
    st.warning("Nenhum dado encontrado com os filtros selecionados.")
    st.stop()

# ---------------------------------------------------------
# KPIs
# ---------------------------------------------------------
st.markdown("## 📊 Visão Geral")

total = len(fdf)

base_nps = fdf[fdf["NPS GRUPO"].notna()].copy()
if len(base_nps) > 0:
    prom = (base_nps["NPS GRUPO"] == "Promotor").sum()
    neut = (base_nps["NPS GRUPO"] == "Neutro").sum()
    det = (base_nps["NPS GRUPO"] == "Detrator").sum()
    nps = ((prom / len(base_nps)) - (det / len(base_nps))) * 100
else:
    prom = neut = det = 0
    nps = 0.0

base_sla = fdf[fdf["SLA STATUS"].isin(["Resolvido no prazo", "Resolvido com atraso"])].copy()
if len(base_sla) > 0:
    no_prazo = (base_sla["SLA STATUS"] == "Resolvido no prazo").sum()
    sla_pct = no_prazo / len(base_sla) * 100
else:
    sla_pct = 0.0

media_dias_paciente = fdf["DIAS ATÉ RETORNO PACIENTE"].mean()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total de manifestações", total)
c2.metric("NPS Geral", f"{nps:.0f}")
c3.metric("SLA — resolvidos no prazo", f"{sla_pct:.1f}%")
if not np.isnan(media_dias_paciente):
    c4.metric("Dias médios até retorno ao paciente", f"{media_dias_paciente:.1f} d")
else:
    c4.metric("Dias médios até retorno ao paciente", "—")

kc1, kc2, kc3 = st.columns(3)
if len(base_nps) > 0:
    kc1.metric("Promotores", f"{prom} ({prom / len(base_nps) * 100:.1f}%)")
    kc2.metric("Neutros", str(neut))
    kc3.metric("Detratores", f"{det} ({det / len(base_nps) * 100:.1f}%)")
else:
    kc1.metric("Promotores", "0")
    kc2.metric("Neutros", "0")
    kc3.metric("Detratores", "0")

# ---------------------------------------------------------
# EVOLUÇÃO TEMPORAL
# ---------------------------------------------------------
st.markdown("## ⏱️ Evolução Temporal")

if fdf["DATA"].notna().any():
    evol = fdf.groupby("DATA").size().reset_index(name="Quantidade")
    evol = evol.sort_values("DATA")
    fig_evol = px.line(
        evol,
        x="DATA",
        y="Quantidade",
        markers=True,
        title="Evolução diária das manifestações",
    )
    fig_evol.update_layout(xaxis_title="Data", yaxis_title="Quantidade")
    st.plotly_chart(fig_evol, use_container_width=True)
else:
    st.info("Coluna DATA vazia; não é possível montar a série temporal.")

# ---------------------------------------------------------
# DISTRIBUIÇÕES PRINCIPAIS
# ---------------------------------------------------------
st.markdown("## 🧭 Distribuições principais")

colA, colB = st.columns(2)

with colA:
    canal_df = (
        fdf["CANAL DE COMUNICAÇÃO"]
        .value_counts()
        .reset_index(name="Quantidade")
        .rename(columns={"index": "CANAL DE COMUNICAÇÃO"})
    )
    if not canal_df.empty:
        fig_canal = px.bar(
            canal_df,
            x="CANAL DE COMUNICAÇÃO",
            y="Quantidade",
            title="Manifestações por canal de comunicação",
            text="Quantidade",
        )
        fig_canal.update_traces(textposition="outside")
        st.plotly_chart(fig_canal, use_container_width=True)
    else:
        st.info("Sem dados para canais de comunicação nos filtros atuais.")

with colB:
    tipo_df = (
        fdf["TIPO DE CHAMADO"]
        .value_counts()
        .reset_index(name="Quantidade")
        .rename(columns={"index": "TIPO DE CHAMADO"})
    )
    if not tipo_df.empty:
        fig_tipo = px.bar(
            tipo_df,
            x="TIPO DE CHAMADO",
            y="Quantidade",
            title="Manifestações por tipo de chamado",
            text="Quantidade",
        )
        fig_tipo.update_traces(textposition="outside")
        st.plotly_chart(fig_tipo, use_container_width=True)
    else:
        st.info("Sem dados para tipo de chamado nos filtros atuais.")

colC, colD = st.columns(2)

with colC:
    crit_df = (
        fdf["CRITICIDADE"]
        .value_counts()
        .reset_index(name="Quantidade")
        .rename(columns={"index": "CRITICIDADE"})
    )
    if not crit_df.empty:
        fig_crit = px.bar(
            crit_df,
            x="CRITICIDADE",
            y="Quantidade",
            title="Criticidade das manifestações",
            text="Quantidade",
        )
        fig_crit.update_traces(textposition="outside")
        st.plotly_chart(fig_crit, use_container_width=True)
    else:
        st.info("Sem dados de criticidade nos filtros atuais.")

with colD:
    status_df = (
        fdf["STATUS"]
        .value_counts()
        .reset_index(name="Quantidade")
        .rename(columns={"index": "STATUS"})
    )
    if not status_df.empty:
        fig_status = px.bar(
            status_df,
            x="STATUS",
            y="Quantidade",
            title="Status das manifestações",
            text="Quantidade",
        )
        fig_status.update_traces(textposition="outside")
        st.plotly_chart(fig_status, use_container_width=True)
    else:
        st.info("Sem dados de status nos filtros atuais.")

# ---------------------------------------------------------
# SETORES, SLA E NPS
# ---------------------------------------------------------
st.markdown("## 🏥 Setores, SLA e NPS")

colE, colF = st.columns(2)

with colE:
    setor_vol = (
        fdf["SETOR NOTIFICADO"]
        .value_counts()
        .reset_index(name="Quantidade")
        .rename(columns={"index": "SETOR NOTIFICADO"})
        .head(15)
    )
    if not setor_vol.empty:
        fig_setor = px.bar(
            setor_vol,
            x="Quantidade",
            y="SETOR NOTIFICADO",
            orientation="h",
            title="Top setores por volume de manifestações",
            text="Quantidade",
        )
        fig_setor.update_traces(textposition="outside")
        st.plotly_chart(fig_setor, use_container_width=True)
    else:
        st.info("Sem dados de setor nos filtros atuais.")

with colF:
    if not base_nps.empty:
        nps_setor = (
            base_nps.groupby("SETOR NOTIFICADO")["NOTA_NUM"]
            .mean()
            .reset_index(name="NPS médio")
            .sort_values("NPS médio", ascending=False)
            .head(15)
        )
        if not nps_setor.empty:
            fig_nps_setor = px.bar(
                nps_setor,
                x="NPS médio",
                y="SETOR NOTIFICADO",
                orientation="h",
                title="NPS médio por setor notificado",
                text="NPS médio",
            )
            fig_nps_setor.update_traces(
                texttemplate="%{x:.1f}", textposition="outside"
            )
            st.plotly_chart(fig_nps_setor, use_container_width=True)
        else:
            st.info("Sem dados de NPS por setor nos filtros atuais.")
    else:
        st.info("Não há dados suficientes de NPS para análise por setor.")

colG, colH = st.columns(2)

with colG:
    sla_dist = (
        fdf["SLA STATUS"]
        .value_counts()
        .reset_index(name="Quantidade")
        .rename(columns={"index": "SLA STATUS"})
    )
    if not sla_dist.empty:
        fig_sla_dist = px.bar(
            sla_dist,
            x="SLA STATUS",
            y="Quantidade",
            title="Distribuição dos status de SLA",
            text="Quantidade",
        )
        fig_sla_dist.update_traces(textposition="outside")
        st.plotly_chart(fig_sla_dist, use_container_width=True)
    else:
        st.info("Sem dados de SLA nos filtros atuais.")

with colH:
    if not base_sla.empty:
        sla_setor = (
            base_sla.groupby("SETOR NOTIFICADO")["SLA STATUS"]
            .value_counts(normalize=True)
            .rename("pct")
            .reset_index()
        )
        sla_setor = sla_setor[sla_setor["SLA STATUS"] == "Resolvido no prazo"]
        sla_setor["pct"] = sla_setor["pct"] * 100
        sla_setor = sla_setor.sort_values("pct", ascending=False).head(15)
        if not sla_setor.empty:
            fig_sla_setor = px.bar(
                sla_setor,
                x="pct",
                y="SETOR NOTIFICADO",
                orientation="h",
                title="% de resolvidos no prazo por setor",
                text="pct",
            )
            fig_sla_setor.update_traces(
                texttemplate="%{x:.1f}%", textposition="outside"
            )
            st.plotly_chart(fig_sla_setor, use_container_width=True)
        else:
            st.info("Sem dados de SLA resolvido no prazo por setor.")
    else:
        st.info("Não há registros resolvidos com prazo para análise de SLA por setor.")

# ---------------------------------------------------------
# NPS – DISTRIBUIÇÃO
# ---------------------------------------------------------
st.markdown("## ❤️ Distribuição de NPS")

if not base_nps.empty:
    dist_nps = (
        base_nps["NPS GRUPO"]
        .value_counts()
        .reset_index(name="Quantidade")
        .rename(columns={"index": "NPS GRUPO"})
    )
    fig_nps = px.bar(
        dist_nps,
        x="NPS GRUPO",
        y="Quantidade",
        title="Distribuição de NPS (Promotor / Neutro / Detrator)",
        text="Quantidade",
    )
    fig_nps.update_traces(textposition="outside")
    st.plotly_chart(fig_nps, use_container_width=True)
else:
    st.info("Não há registros com NPS preenchido nos filtros atuais.")

# ---------------------------------------------------------
# DETRATORES – TABELA FOCO
# ---------------------------------------------------------
st.markdown("## ⚠️ Foco em Detratores")

detratores_df = fdf[fdf["NPS GRUPO"] == "Detrator"].copy()
if detratores_df.empty:
    st.info("Nenhum detrator encontrado nos filtros atuais.")
else:
    cols_det = [
        c
        for c in [
            "DATA",
            "CANAL DE COMUNICAÇÃO",
            "TIPO DE CHAMADO",
            "MANIFESTAÇÃO",
            "PACIENTE",
            "SETOR NOTIFICADO",
            "CRITICIDADE",
            "STATUS",
            "NOTA",
            "NPS GRUPO",
            "DESCRIÇÃO DO OCORRIDO",
            "PLANO DE AÇÃO",
            "DATA DE RETORNO AO PACIENTE",
        ]
        if c in detratores_df.columns
    ]
    detratores_df = detratores_df.sort_values("DATA", ascending=False)
    st.dataframe(detratores_df[cols_det], use_container_width=True)

    csv_det = detratores_df[cols_det].to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "⬇️ Baixar lista de detratores (CSV)",
        data=csv_det,
        file_name="detratores_filtrados.csv",
        mime="text/csv",
    )

# ---------------------------------------------------------
# TABELA DETALHADA + DOWNLOAD GERAL
# ---------------------------------------------------------
st.markdown("## 📋 Detalhamento completo (dados filtrados)")

st.dataframe(fdf, use_container_width=True)

csv_all = fdf.to_csv(index=False, encoding="utf-8-sig")
st.download_button(
    "⬇️ Baixar dados filtrados (CSV)",
    data=csv_all,
    file_name="manifestacoes_filtradas.csv",
    mime="text/csv",
)
