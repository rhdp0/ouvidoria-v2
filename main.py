import re
from pathlib import Path
from typing import Iterable, List, Sequence

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
.panel {
    background: #fdfefe;
    border: 1px solid #e6eaf2;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.04);
    border-radius: 12px;
    padding: 18px;
}
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
    "prazo para retorno": "PRAZO PARA RETORNO",
    "prazo para retorno (dia)": "PRAZO PARA RETORNO",
    "status": "STATUS",
    "nota": "NOTA",
    "classificacao nps": "CLASSIFICAÇÃO NPS",
    "data do retorno a ouvidoria": "DATA DO RETORNO A OUVIDORIA",
    "plano de acao": "PLANO DE AÇÃO",
    "data de retorno ao paciente": "DATA DE RETORNO AO PACIENTE",
}


def _is_marked(value) -> bool:
    """Interpreta valores marcados (sim/x/etc.) como verdadeiros."""
    if pd.isna(value):
        return False

    text = _normalize_text(str(value))
    if text in {"", "nao", "na", "n"}:
        return False
    return True


def rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Renomeia colunas da planilha para nomes canônicos."""
    rename_map = {}
    norms = {_normalize_text(k): v for k, v in COL_CANONICAL.items()}
    for col in df.columns:
        n = _normalize_text(col)
        if n in norms:
            rename_map[col] = norms[n]
    df = df.rename(columns=rename_map)
    keep = list(dict.fromkeys(c for c in COL_CANONICAL.values() if c in df.columns))
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
    if "PRAZO PARA RETORNO" in df.columns:
        prazo_numerico = pd.to_numeric(df["PRAZO PARA RETORNO"], errors="coerce")
        df["PRAZO DIAS"] = prazo_numerico.mask(np.abs(prazo_numerico) > 3650)
    else:
        df["PRAZO DIAS"] = pd.Series(pd.NA, index=df.index, dtype="float")

    # data limite
    df["DATA LIMITE GESTOR"] = pd.NaT
    prazo_valido = df["PRAZO DIAS"].notna() & df["DATA DO ENVIO AO GESTOR"].notna()
    df.loc[prazo_valido, "DATA LIMITE GESTOR"] = df.loc[
        prazo_valido, "DATA DO ENVIO AO GESTOR"
    ] + pd.to_timedelta(df.loc[prazo_valido, "PRAZO DIAS"], unit="D")

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
    nps_grupo = pd.Series(pd.NA, index=df.index, dtype="object")

    notas = df["NOTA_NUM"]
    nps_grupo.loc[notas >= 9] = "Promotor"
    nps_grupo.loc[(notas >= 7) & (notas < 9)] = "Neutro"
    nps_grupo.loc[notas <= 6] = "Detrator"

    df["NPS GRUPO"] = nps_grupo
    return df


def add_manifestacao_flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    manifestacao_norm = pd.Series("", index=df.index, dtype="object")
    if "MANIFESTAÇÃO" in df.columns:
        manifestacao_norm = df["MANIFESTAÇÃO"].fillna("").astype(str).map(
            _normalize_text
        )
    df["MANIFESTAÇÃO NORMALIZADA"] = manifestacao_norm

    tipo_norm = pd.Series("", index=df.index, dtype="object")
    if "TIPO DE CHAMADO" in df.columns:
        tipo_norm = df["TIPO DE CHAMADO"].fillna("").astype(str).map(
            _normalize_text
        )
    df["TIPO DE CHAMADO NORMALIZADO"] = tipo_norm
    df["IS_ELOGIO"] = tipo_norm == "elogio"
    return df


def chunked(seq: Sequence, size: int) -> Iterable[List]:
    """Divide uma sequência em blocos de tamanho fixo."""
    if size <= 0:
        raise ValueError("size deve ser maior que zero")
    for i in range(0, len(seq), size):
        yield list(seq[i : i + size])


def render_kpi_grid(kpis: Sequence[dict], per_row: int = 3) -> None:
    """Renderiza métricas em uma grade responsiva usando colunas uniformes."""
    if not kpis:
        return

    with st.container():
        for chunk in chunked(kpis, per_row):
            cols = st.columns(len(chunk))
            for col, data in zip(cols, chunk):
                col.metric(
                    data.get("label", ""),
                    data.get("value", ""),
                    delta=data.get("delta"),
                    delta_color=data.get("delta_color", "normal"),
                    help=data.get("help"),
                )


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
    df = add_manifestacao_flags(df)
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
somente_elogios = st.sidebar.toggle("Somente elogios", value=False)

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
if somente_elogios:
    fdf = fdf[fdf["IS_ELOGIO"]]

if fdf.empty:
    st.warning("Nenhum dado encontrado com os filtros selecionados.")
    st.stop()

reclamacoes_df = fdf[fdf["TIPO DE CHAMADO NORMALIZADO"] == "reclamacao"].copy()

# ---------------------------------------------------------
# KPIs
# ---------------------------------------------------------
st.markdown("## 📊 Visão Geral")

total = len(fdf)
elogios_count = int(fdf.get("IS_ELOGIO", pd.Series(dtype=bool)).sum())
elogios_pct = (elogios_count / total * 100) if total else 0.0
elogios_df = fdf[fdf.get("IS_ELOGIO", pd.Series(dtype=bool))].copy()

manifestacao_col = (
    "MANIFESTAÇÃO NORMALIZADA"
    if "MANIFESTAÇÃO NORMALIZADA" in elogios_df.columns
    else "MANIFESTAÇÃO"
)

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

andamento_count = (fdf["SLA STATUS"] == "Em andamento no prazo").sum()
atraso_count = (fdf["SLA STATUS"] == "Em atraso").sum()

andamento_pct = (andamento_count / total * 100) if total else 0.0
atraso_pct = (atraso_count / total * 100) if total else 0.0

solicitado_count = (
    fdf["SOLICITADO CONTATO"].apply(_is_marked).sum()
    if "SOLICITADO CONTATO" in fdf.columns
    else 0
)
solicitado_pct = (solicitado_count / total * 100) if total else 0.0

retorno_paciente_count = (
    fdf["DATA DE RETORNO AO PACIENTE"].notna().sum()
    if "DATA DE RETORNO AO PACIENTE" in fdf.columns
    else 0
)
retorno_pct = (retorno_paciente_count / total * 100) if total else 0.0

retorno_pos_contato = 0
if {"SOLICITADO CONTATO", "DATA DE RETORNO AO PACIENTE"}.issubset(fdf.columns):
    solicit_mask = fdf["SOLICITADO CONTATO"].apply(_is_marked)
    retorno_pos_contato = fdf["DATA DE RETORNO AO PACIENTE"].notna() & solicit_mask
    retorno_pos_contato = retorno_pos_contato.sum()

plano_count = 0
plano_pct = 0.0
if "PLANO DE AÇÃO" in fdf.columns:
    plano_series = fdf["PLANO DE AÇÃO"].fillna("").astype(str).str.strip()
    plano_count = (plano_series != "").sum()
    plano_pct = (plano_count / total * 100) if total else 0.0

kpi_overview = [
    {"label": "Total de manifestações", "value": total},
    {
        "label": "Elogios (volume)",
        "value": elogios_count,
        "delta": f"{elogios_pct:.1f}% do total",
    },
    {"label": "NPS Geral", "value": f"{nps:.0f}"},
    {"label": "SLA — resolvidos no prazo", "value": f"{sla_pct:.1f}%"},
    {
        "label": "Dias médios até retorno ao paciente",
        "value": f"{media_dias_paciente:.1f} d"
        if not np.isnan(media_dias_paciente)
        else "—",
    },
]

kpi_status = [
    {
        "label": "Casos em andamento no prazo",
        "value": andamento_count,
        "delta": f"{andamento_pct:.1f}% do total",
        "delta_color": "normal",
    },
    {
        "label": "Casos em atraso",
        "value": atraso_count,
        "delta": f"{atraso_pct:.1f}% do total",
        "delta_color": "inverse" if atraso_count > 0 else "normal",
    },
]

if len(base_nps) > 0:
    prom_pct = prom / len(base_nps) * 100
    det_pct = det / len(base_nps) * 100
else:
    prom_pct = det_pct = 0.0

kpi_nps = [
    {
        "label": "Promotores",
        "value": (
            f"{prom} ({prom_pct:.1f}%)" if len(base_nps) > 0 else "0"
        ),
    },
    {
        "label": "Neutros",
        "value": str(neut) if len(base_nps) > 0 else "0",
    },
    {
        "label": "Detratores",
        "value": (
            f"{det} ({det_pct:.1f}%)" if len(base_nps) > 0 else "0"
        ),
    },
]

kpi_extra = [
    {
        "label": "Solicitado contato",
        "value": f"{solicitado_pct:.1f}%",
        "delta": f"{solicitado_count} casos",
    },
    {
        "label": "Retorno ao paciente registrado",
        "value": retorno_paciente_count,
        "delta": (
            f"{retorno_pct:.1f}% do total"
            if retorno_paciente_count > 0
            else "Sem registros"
        ),
    },
    {
        "label": "Planos de ação preenchidos",
        "value": plano_count,
        "delta": (
            f"{plano_pct:.1f}% do total" if plano_count > 0 else "Sem registros"
        ),
    },
]

with st.container():
    st.markdown("### Volume & Satisfação")
    st.caption("Indicadores consolidados considerando apenas os casos filtrados.")
    render_kpi_grid(kpi_overview)

st.divider()

with st.container():
    st.markdown("### Status Operacional")
    st.caption("Percentuais calculados sobre o total filtrado.")
    render_kpi_grid(kpi_status)

st.divider()

with st.container():
    st.markdown("### Perfil NPS")
    st.caption("Base formada apenas por manifestações com nota registrada.")
    render_kpi_grid(kpi_nps)

st.divider()

with st.container():
    st.markdown("### Engajamento & Retornos")
    st.caption("Indicadores complementares relativos aos casos filtrados.")
    render_kpi_grid(kpi_extra)

if retorno_pos_contato > 0:
    st.caption(
        f"• {retorno_pos_contato} manifestações possuem 'Solicitado contato' e já contam com retorno registrado."
    )

st.divider()

with st.container():
    st.markdown("### Distribuição por tipo de chamado")
    st.caption("Indicadores calculados sobre os dados filtrados.")

    st.markdown('<div class="panel">', unsafe_allow_html=True)

    colElo1, colElo2 = st.columns([1, 1.3])

    with colElo1:
        st.subheader("Tipos de chamado", divider=False)
        tipo_counts = (
            fdf["TIPO DE CHAMADO"]
            .fillna("")
            .astype(str)
            .map(_normalize_text)
            .value_counts()
        )
        tipos_exibicao = {
            "elogio": "Elogios",
            "reclamacao": "Reclamações",
            "sugestao": "Sugestões",
        }
        kpi_tipos = []
        for key, label in tipos_exibicao.items():
            count = int(tipo_counts.get(key, 0))
            delta = f"{(count / total * 100):.1f}% do total" if total else "Sem registros"
            kpi_tipos.append({"label": label, "value": count, "delta": delta})
        render_kpi_grid(kpi_tipos, per_row=1)

    with colElo2:
        st.subheader("Distribuição dos tipos", divider=False)
        tipos_chamado = (
            fdf["TIPO DE CHAMADO"]
            .value_counts()
            .reset_index(name="Quantidade")
            .rename(columns={"index": "TIPO DE CHAMADO"})
        )

        if tipos_chamado.empty:
            st.info(
                "Sem dados de tipos de chamado para exibir a distribuição com os filtros atuais."
            )
        else:
            fig_elogios = px.pie(
                tipos_chamado,
                values="Quantidade",
                names="TIPO DE CHAMADO",
                hole=0.45,
                title="Distribuição dos tipos de chamado",
            )
            fig_elogios.update_traces(
                textposition="inside",
                texttemplate="%{label}: %{value} (%{percent:.1%})",
                hovertemplate="<b>%{label}</b><br>Chamados: %{value}<br>Participação: %{percent:.1%}<extra></extra>",
            )
            fig_elogios.update_layout(
                legend_title_text="Tipo de chamado",
                margin=dict(l=20, r=20, t=60, b=80),
                title_x=0.5,
                legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.1),
            )
            st.plotly_chart(fig_elogios, use_container_width=True)

    elogios_motivos = (
        elogios_df[manifestacao_col]
        .replace("", pd.NA)
        .dropna()
        .value_counts()
        .reset_index(name="Quantidade")
        .rename(columns={manifestacao_col: "Manifestação"})
    )

    if elogios_motivos.empty:
        st.info("Sem dados de elogios para detalhar os motivos nos filtros atuais.")
    else:
        fig_motivos = px.bar(
            elogios_motivos,
            x="Manifestação",
            y="Quantidade",
            title="Motivos dos elogios",
            text="Quantidade",
        )
        fig_motivos.update_traces(textposition="outside")
        fig_motivos.update_layout(xaxis_title="Manifestação", yaxis_title="Quantidade")
        st.plotly_chart(fig_motivos, use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------
# EVOLUÇÃO TEMPORAL
# ---------------------------------------------------------
st.markdown("## ⏱️ Evolução Temporal")

with st.expander("Volume agregado e tendência", expanded=True):
    freq_choice = st.radio(
        "Granularidade do agregado",
        ["Mensal", "Trimestral"],
        horizontal=True,
    )

    if {"ANO", "MES"}.issubset(fdf.columns):
        period_df = fdf.dropna(subset=["ANO", "MES"]).copy()
        period_df["ANO"] = period_df["ANO"].astype(int)
        period_df["MES"] = period_df["MES"].astype(int)

        if freq_choice == "Trimestral":
            period_df["TRIMESTRE"] = ((period_df["MES"] - 1) // 3 + 1).astype(int)
            grouped = (
                period_df.groupby(["ANO", "TRIMESTRE"]).size().reset_index(name="Quantidade")
            )
            grouped["LABEL"] = grouped.apply(
                lambda r: f"T{int(r['TRIMESTRE'])}/{int(r['ANO'])}", axis=1
            )
            grouped["PERIODO_DATA"] = pd.PeriodIndex(
                year=grouped["ANO"], quarter=grouped["TRIMESTRE"], freq="Q"
            ).to_timestamp()
            compare_col = "TRIMESTRE"
        else:
            grouped = (
                period_df.groupby(["ANO", "MES", "MES_NOME"])
                .size()
                .reset_index(name="Quantidade")
            )
            grouped["LABEL"] = grouped.apply(
                lambda r: f"{r['MES_NOME']}/{int(r['ANO'])}", axis=1
            )
            grouped["PERIODO_DATA"] = pd.to_datetime(
                dict(year=grouped["ANO"], month=grouped["MES"], day=1)
            )
            compare_col = "MES"

        grouped = grouped.sort_values("PERIODO_DATA")
        grouped["ANO_PREV"] = grouped["ANO"] - 1
        prev = grouped[["ANO", compare_col, "Quantidade"]].rename(
            columns={"ANO": "ANO_PREV", "Quantidade": "Quantidade_Ano_Anterior"}
        )
        grouped = grouped.merge(prev, on=["ANO_PREV", compare_col], how="left")
        grouped["VAR_ABS"] = grouped["Quantidade"] - grouped["Quantidade_Ano_Anterior"]
        grouped["VAR_PCT"] = np.where(
            grouped["Quantidade_Ano_Anterior"] > 0,
            grouped["VAR_ABS"] / grouped["Quantidade_Ano_Anterior"] * 100,
            np.nan,
        )

        if not grouped.empty:
            label_order = list(dict.fromkeys(grouped["LABEL"].tolist()))
            fig_period = px.bar(
                grouped,
                x="LABEL",
                y="Quantidade",
                text="Quantidade",
                title=f"Volume {freq_choice.lower()} de manifestações",
                category_orders={"LABEL": label_order},
            )
            fig_period.update_traces(textposition="outside")
            fig_period.update_layout(
                xaxis_title="Período", yaxis_title="Quantidade", showlegend=False
            )
            st.plotly_chart(fig_period, use_container_width=True)

            last_row = grouped.iloc[-1]
            c_month1, c_month2, c_month3 = st.columns(3)
            c_month1.metric(
                "Volume do período mais recente",
                (
                    int(last_row["Quantidade"])
                    if not pd.isna(last_row["Quantidade"])
                    else "—"
                ),
                delta=f"{last_row['LABEL']}",
            )
            c_month2.metric(
                "Variação absoluta vs ano anterior",
                (
                    f"{int(last_row['VAR_ABS']):+} casos"
                    if not pd.isna(last_row["VAR_ABS"])
                    else "—"
                ),
                delta=(
                    f"Base {int(last_row['Quantidade_Ano_Anterior'])}"
                    if not pd.isna(last_row["Quantidade_Ano_Anterior"])
                    else "Sem histórico"
                ),
            )
            c_month3.metric(
                "Variação percentual vs ano anterior",
                (
                    f"{last_row['VAR_PCT']:.1f}%"
                    if not pd.isna(last_row["VAR_PCT"])
                    else "—"
                ),
                delta=(
                    f"Comparado a {int(last_row['ANO_PREV'])}"
                    if not pd.isna(last_row["ANO_PREV"])
                    else "Sem histórico"
                ),
            )
        else:
            st.info("Não há dados suficientes para compor o agregado do período selecionado.")
    else:
        st.info("Colunas ANO/MÊS não estão disponíveis nos dados filtrados.")

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

    st.markdown("#### Reclamações — motivos mais frequentes")
    if not reclamacoes_df.empty and "MANIFESTAÇÃO" in reclamacoes_df.columns:
        motivos_reclamacao = (
            reclamacoes_df["MANIFESTAÇÃO"]
            .fillna("Não informado")
            .astype(str)
            .str.strip()
            .replace("", "Não informado")
            .value_counts()
            .reset_index(name="Quantidade")
            .rename(columns={"index": "MANIFESTAÇÃO"})
        )

        if not motivos_reclamacao.empty:
            motivos_top = motivos_reclamacao.head(10)
            destaque_motivo = motivos_top.iloc[0]

            col_kpi_motivo, col_chart_motivo = st.columns([1, 3])
            col_kpi_motivo.metric(
                "Motivo líder (reclamações)",
                destaque_motivo["MANIFESTAÇÃO"],
                delta=f"{int(destaque_motivo['Quantidade'])} casos",
            )

            fig_motivos = px.bar(
                motivos_top,
                x="Quantidade",
                y="MANIFESTAÇÃO",
                orientation="h",
                title="Top motivos das reclamações",
                text="Quantidade",
            )
            fig_motivos.update_traces(textposition="outside")
            fig_motivos.update_layout(yaxis_title="Motivo", xaxis_title="Quantidade")
            col_chart_motivo.plotly_chart(fig_motivos, use_container_width=True)
        else:
            st.info("Não há motivos de manifestação preenchidos para reclamações.")
    else:
        st.info("Nenhum registro classificado como reclamação nos filtros atuais.")

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

if "ÁREA" in fdf.columns:
    area_df = (
        fdf["ÁREA"].value_counts().reset_index(name="Quantidade").rename(columns={"index": "ÁREA"})
    )
else:
    area_df = pd.DataFrame()

if not area_df.empty:
    area_df["%"] = area_df["Quantidade"] / total * 100 if total else 0
    st.markdown("### Distribuição por área")
    fig_area = px.bar(
        area_df,
        x="Quantidade",
        y="ÁREA",
        orientation="h",
        text="Quantidade",
        title="Manifestações por área",
    )
    fig_area.update_traces(textposition="outside")
    fig_area.update_layout(yaxis_title="Área", xaxis_title="Quantidade")
    st.plotly_chart(fig_area, use_container_width=True)

    tabela_area = area_df.copy()
    tabela_area["%"] = tabela_area["%"].map(lambda v: f"{v:.1f}%")
    st.dataframe(tabela_area, use_container_width=True, hide_index=True)
else:
    st.info("Sem dados de área para os filtros atuais.")

# ---------------------------------------------------------
# SETORES, SLA E NPS
# ---------------------------------------------------------
st.markdown("## 🏥 Setores, SLA e NPS")

st.markdown("#### Setores com mais reclamações (recorte de reclamações)")
if not reclamacoes_df.empty:
    setores_reclamacao = (
        reclamacoes_df["SETOR NOTIFICADO"]
        .value_counts()
        .reset_index(name="Quantidade")
        .rename(columns={"index": "SETOR NOTIFICADO"})
    )

    if not setores_reclamacao.empty:
        setores_reclamacao = setores_reclamacao.sort_values(
            "Quantidade", ascending=False
        ).head(15)
        destaque = setores_reclamacao.iloc[0]

        col_kpi_reclamacao, col_chart_reclamacao = st.columns([1, 3])

        col_kpi_reclamacao.metric(
            "Setor com mais reclamações",
            destaque["SETOR NOTIFICADO"],
            delta=f"{int(destaque['Quantidade'])} casos",
        )

        fig_reclamacao_setor = px.bar(
            setores_reclamacao,
            x="Quantidade",
            y="SETOR NOTIFICADO",
            orientation="h",
            title="Top setores por volume de reclamações",
            text="Quantidade",
        )
        fig_reclamacao_setor.update_traces(textposition="outside")
        col_chart_reclamacao.plotly_chart(
            fig_reclamacao_setor, use_container_width=True
        )
    else:
        st.info("Sem dados de setor para reclamações nos filtros atuais.")
else:
    st.info("Nenhum registro classificado como reclamação nos filtros atuais.")

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
# SLA E NPS POR CRITICIDADE
# ---------------------------------------------------------
st.markdown("## 🚦 SLA e NPS por criticidade")

colCrit1, colCrit2 = st.columns(2)

with colCrit1:
    if not base_sla.empty:
        sla_crit = (
            base_sla.groupby(["CRITICIDADE", "SLA STATUS"])
            .size()
            .reset_index(name="Quantidade")
        )
        sla_crit = sla_crit.dropna(subset=["CRITICIDADE"])
        if not sla_crit.empty:
            sla_crit["Total Criticidade"] = sla_crit.groupby("CRITICIDADE")[
                "Quantidade"
            ].transform("sum")
            sla_crit["pct"] = sla_crit["Quantidade"] / sla_crit["Total Criticidade"] * 100
            fig_sla_crit = px.bar(
                sla_crit,
                x="CRITICIDADE",
                y="pct",
                color="SLA STATUS",
                text="pct",
                title="SLA dos casos resolvidos por criticidade",
                labels={"pct": "% do total"},
            )
            fig_sla_crit.update_traces(texttemplate="%{text:.1f}%", textposition="inside")
            fig_sla_crit.update_layout(
                yaxis_title="% dos casos",
                legend_title="SLA",
                barmode="stack",
            )
            st.plotly_chart(fig_sla_crit, use_container_width=True)

            tabela_sla = sla_crit[
                ["CRITICIDADE", "SLA STATUS", "Quantidade", "pct"]
            ].copy()
            tabela_sla["pct"] = tabela_sla["pct"].map(lambda v: f"{v:.1f}%")
            st.dataframe(
                tabela_sla,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Criticidades com SLA resolvido não estão disponíveis nos filtros atuais.")
    else:
        st.info("Não há registros resolvidos para análise de SLA por criticidade.")

with colCrit2:
    if not base_nps.empty:
        nps_crit = (
            base_nps.dropna(subset=["CRITICIDADE", "NOTA_NUM"])
            .groupby("CRITICIDADE")
            .agg(Notas=("NOTA_NUM", "count"), Media_NPS=("NOTA_NUM", "mean"))
            .reset_index()
        )
        if not nps_crit.empty:
            fig_nps_crit = px.bar(
                nps_crit,
                x="CRITICIDADE",
                y="Media_NPS",
                text="Media_NPS",
                title="Nota média de NPS por criticidade",
            )
            fig_nps_crit.update_traces(texttemplate="%{text:.1f}", textposition="outside")
            fig_nps_crit.update_layout(yaxis_title="Nota média")
            st.plotly_chart(fig_nps_crit, use_container_width=True)

            tabela_nps = nps_crit.copy()
            tabela_nps["Media_NPS"] = tabela_nps["Media_NPS"].map(
                lambda v: f"{v:.2f}"
            )
            tabela_nps = tabela_nps.rename(
                columns={"Notas": "Registros avaliados", "Media_NPS": "NPS médio"}
            )
            st.dataframe(tabela_nps, use_container_width=True, hide_index=True)
        else:
            st.info("Não há criticidades com notas de NPS preenchidas.")
    else:
        st.info("Não há dados suficientes de NPS para análise por criticidade.")

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
