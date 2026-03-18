import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests
from datetime import datetime, timedelta

# 1. CONFIGURAÇÃO
st.set_page_config(page_title="MacroPerform BI", layout="wide", page_icon="📈")

# 2. MOTOR DE DADOS MACRO
@st.cache_data(ttl=3600)
def buscar_dados_bcb(codigo_sgs, data_inicio):
    try:
        url = f'https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo_sgs}/dados?formato=json&dataInicial={data_inicio}'
        response = requests.get(url, timeout=10)
        df = pd.DataFrame(response.json())
        df['data'] = pd.to_datetime(df['data'], format='%d/%m/%Y')
        df['valor'] = df['valor'].astype(float)
        df.set_index('data', inplace=True)
        return df
    except:
        return pd.DataFrame()

# 3. MOTOR DE ATIVOS (LISTA VITRINE)
@st.cache_data(ttl=86400)
def carregar_listagem_ativos():
    # Esta é a vitrine principal. Fácil de clicar.
    lista_vitrine = [
        "^BVSP", "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "BBAS3.SA",
        "CYRE3.SA", "B3SA3.SA", "WEGE3.SA", "MGLU3.SA", "RENT3.SA", 
        "HGLG11.SA", "KNRI11.SA", "MXRF11.SA", "BCFF11.SA", "BTC-USD", "AAPL"
    ]
    return sorted(lista_vitrine)

# --- SIDEBAR (DESIGN HÍBRIDO) ---
st.sidebar.header("⚙️ Painel de Controle")

lista_opcoes = carregar_listagem_ativos()

# Componente 1: A Vitrine (Para facilitar a vida)
selecao_vitrine = st.sidebar.multiselect(
    "1. Selecione na lista:", 
    options=lista_opcoes, 
    default=["^BVSP", "PETR4.SA"]
)

# Componente 2: O Campo Livre (Para ações raras)
ticker_extra = st.sidebar.text_input(
    "2. Não achou? Digite o código aqui (Ex: ARZZ3.SA):", 
    value=""
)

# --- UNIFICANDO AS ESCOLHAS ---
# Juntamos o que ele clicou com o que ele digitou
selecionados = list(selecao_vitrine)
if ticker_extra:
    # Pega o texto, separa por vírgula, limpa os espaços e deixa maiúsculo
    extras = [t.strip().upper() for t in ticker_extra.split(",") if t.strip()]
    selecionados.extend(extras)

# Remove duplicatas (caso ele digite algo que já clicou)
selecionados = list(set(selecionados))

data_ini = st.sidebar.date_input("Início da Análise", datetime.now() - timedelta(days=5*365))
data_fim = st.sidebar.date_input("Fim da Análise", datetime.now())

# --- LÓGICA DE PROCESSAMENTO ---
if selecionados:
    with st.spinner('Sincronizando com a Bolsa...'):
        # 1. Download
        precos_brutos = yf.download(selecionados, start=data_ini, end=data_fim)['Close']
        df_precos = pd.DataFrame(precos_brutos)
        
        # BLINDAGEM MÁXIMA: Remove ativos que voltaram totalmente vazios (Ex: BVMF.SA)
        df_precos.dropna(axis=1, how='all', inplace=True)
        
        # Se após limpar os vazios, não sobrar nada, ele para e avisa o usuário
        if df_precos.empty:
            st.error("🚨 Nenhum ativo válido encontrado. Verifique se os códigos estão corretos (Ex: BVMF.SA mudou para B3SA3.SA).")
            st.stop() # Interrompe o código aqui para não quebrar a tela

        df_precos.index = pd.to_datetime(df_precos.index).tz_localize(None)

        # Atualiza a lista de selecionados apenas com os que realmente funcionaram
        ativos_validos = df_precos.columns.tolist()

        # 2. Busca Macro
        fmt_data = data_ini.strftime('%d/%m/%Y')
        cdi = buscar_dados_bcb(12, fmt_data)
        ipca = buscar_dados_bcb(433, fmt_data)

        # 3. Normalização
        df_base100 = (df_precos / df_precos.iloc[0]).ffill() * 100
        
        # 4. Cruzamento
        df_final = df_base100.copy()
        if not cdi.empty:
            cdi['Acum_CDI'] = (1 + (cdi['valor'] / 100)).cumprod() * 100
            df_final = df_final.join(cdi['Acum_CDI'])
        if not ipca.empty:
            ipca['Acum_IPCA'] = (1 + (ipca['valor'] / 100)).cumprod() * 100
            df_final = df_final.join(ipca['Acum_IPCA'])
        
        df_final = df_final.ffill()

    # --- INTERFACE ---
    st.title("📊 MacroPerform: Inteligência de Dados")
    
    # KPIs
    kpi_cols = st.columns(len(ativos_validos) + 1)
    for i, ticker in enumerate(ativos_validos):
        try:
            val = df_final[ticker].dropna().iloc[-1]
            kpi_cols[i].metric(ticker, f"R$ {val:.2f}", f"{val-100:.1f}%")
        except: continue
    
    if 'Acum_IPCA' in df_final.columns:
        try:
            val_inf = df_final['Acum_IPCA'].dropna().iloc[-1]
            kpi_cols[-1].metric("Inflação (IPCA)", f"R$ {val_inf:.2f}", f"{val_inf-100:.1f}%", delta_color="inverse")
        except: pass

    # Gráfico Performance
    st.subheader("Avaliação de Performance (Base R$ 100)")
    fig_perf = go.Figure()
    for col in df_base100.columns:
        fig_perf.add_trace(go.Scatter(x=df_final.index, y=df_final[col], name=col))
    
    if 'Acum_IPCA' in df_final.columns:
        ipca_clean = df_final['Acum_IPCA'].dropna()
        fig_perf.add_trace(go.Scatter(x=ipca_clean.index, y=ipca_clean, name="IPCA", 
                                     line=dict(color='red', width=3, dash='dash')))
    
    fig_perf.update_layout(hovermode="x unified", template="plotly_white", height=500)
    st.plotly_chart(fig_perf, use_container_width=True)

    # Risco
    st.markdown("---")
    r1, r2 = st.columns(2)
    with r1:
        st.subheader("Matriz de Correlação")
        if len(ativos_validos) > 1:
            st.plotly_chart(go.Figure(data=go.Heatmap(z=df_precos.pct_change().corr(), x=df_precos.columns, y=df_precos.columns, colorscale='RdBu', zmin=-1, zmax=1)), use_container_width=True)
        else:
            st.info("Selecione mais de um ativo válido.")
    with r2:
        st.subheader("Volatilidade Anualizada (%)")
        vol = (df_precos.pct_change().std() * (252**0.5) * 100).sort_values()
        st.plotly_chart(go.Figure(go.Bar(x=vol.values, y=vol.index, orientation='h', marker_color='teal')), use_container_width=True)

    # Simulador
    st.markdown("---")
    st.subheader("Simulador de Evolução Patrimonial")
    s1, s2 = st.columns([1, 2])
    with s1:
        v_aporte = st.number_input("Aporte Mensal (R$)", value=500, step=100)
        ativo_sim = st.selectbox("Simular em:", ativos_validos)
    with s2:
        try:
            ret_m = df_precos[ativo_sim].resample('ME').last().pct_change().fillna(0)
            saldo, hist = 0, []
            for r in ret_m:
                saldo = (saldo + v_aporte) * (1 + r)
                hist.append(saldo)
            st.metric("Patrimônio Final", f"R$ {saldo:,.2f}", f"Lucro: R$ {saldo - (len(ret_m)*v_aporte):,.2f}")
            st.plotly_chart(go.Figure(go.Scatter(x=ret_m.index, y=hist, fill='tozeroy', name="Saldo", line=dict(color='green'))), use_container_width=True)
        except: st.warning("Dados insuficientes.")
else:
    st.info("👈 Selecione ou digite ativos na barra lateral.")