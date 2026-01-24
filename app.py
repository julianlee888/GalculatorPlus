import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import scipy.optimize
from datetime import datetime

# ============================================================
# 🔐 Firebase 設定 - 從 Streamlit Secrets 讀取（安全方式）
# ============================================================
def get_firebase_config():
    """從 Streamlit Secrets 讀取 Firebase 設定"""
    try:
        # 嘗試從 Streamlit Secrets 讀取（部署環境）
        return {
            "apiKey": st.secrets["firebase"]["apiKey"],
            "authDomain": st.secrets["firebase"]["authDomain"],
            "projectId": st.secrets["firebase"]["projectId"],
            "storageBucket": st.secrets["firebase"]["storageBucket"],
            "messagingSenderId": st.secrets["firebase"]["messagingSenderId"],
            "appId": st.secrets["firebase"]["appId"]
        }
    except Exception:
        # 本地開發時顯示錯誤提示
        st.error("⚠️ 找不到 Firebase 設定！請設定 Streamlit Secrets。")
        st.info("""
        **本地開發時**，請在專案目錄建立 `.streamlit/secrets.toml` 檔案：
        ```toml
        [firebase]
        apiKey = "your-api-key"
        authDomain = "your-project.firebaseapp.com"
        projectId = "your-project-id"
        storageBucket = "your-project.appspot.com"
        messagingSenderId = "123456789"
        appId = "1:xxx:web:xxx"
        ```
        
        **部署到 Streamlit Cloud 時**，請在 App Settings → Secrets 中設定。
        """)
        st.stop()

# ============================================================
# 🔐 認證相關函數
# ============================================================
def get_login_html(config):
    """產生 Firebase 登入頁面 HTML"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                display: flex; justify-content: center; align-items: center;
                min-height: 500px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }}
            .login-container {{
                background: rgba(255,255,255,0.95);
                padding: 40px 50px; border-radius: 20px;
                box-shadow: 0 25px 50px rgba(0,0,0,0.25);
                text-align: center; max-width: 400px; width: 90%;
            }}
            .logo {{ font-size: 64px; margin-bottom: 10px; }}
            h1 {{ color: #333; margin-bottom: 10px; font-size: 28px; }}
            .subtitle {{ color: #666; margin-bottom: 30px; font-size: 14px; }}
            .google-btn {{
                display: inline-flex; align-items: center; justify-content: center; gap: 12px;
                background: #fff; border: 2px solid #ddd; padding: 14px 28px;
                border-radius: 50px; cursor: pointer; font-size: 16px; font-weight: 500;
                color: #333; transition: all 0.3s ease; width: 100%;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            .google-btn:hover {{
                background: #f8f9fa; border-color: #4285f4;
                box-shadow: 0 5px 20px rgba(66,133,244,0.3); transform: translateY(-2px);
            }}
            .google-btn img {{ width: 24px; height: 24px; }}
            .loading {{ display: none; color: #666; margin-top: 20px; }}
            .loading.active {{ display: block; }}
            .spinner {{
                border: 3px solid #f3f3f3; border-top: 3px solid #4285f4;
                border-radius: 50%; width: 24px; height: 24px;
                animation: spin 1s linear infinite; margin: 10px auto;
            }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            .error {{ color: #e74c3c; margin-top: 15px; font-size: 14px; display: none; }}
            .footer {{ margin-top: 30px; color: #999; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="login-container">
            <div class="logo">🐔</div>
            <h1>金雞計算機</h1>
            <p class="subtitle">Galculator+ 投資回測工具</p>
            <button class="google-btn" onclick="signInWithGoogle()">
                <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="Google">
                使用 Google 帳號登入
            </button>
            <div class="loading" id="loading"><div class="spinner"></div><p>正在登入中...</p></div>
            <p class="error" id="error"></p>
            <p class="footer">登入即表示您同意使用條款</p>
        </div>
        <script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-app-compat.js"></script>
        <script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-auth-compat.js"></script>
        <script>
            const firebaseConfig = {{
                apiKey: "{config['apiKey']}",
                authDomain: "{config['authDomain']}",
                projectId: "{config['projectId']}",
                storageBucket: "{config['storageBucket']}",
                messagingSenderId: "{config['messagingSenderId']}",
                appId: "{config['appId']}"
            }};
            firebase.initializeApp(firebaseConfig);
            const auth = firebase.auth();
            const provider = new firebase.auth.GoogleAuthProvider();
            
            async function signInWithGoogle() {{
                const btn = document.querySelector('.google-btn');
                const loading = document.getElementById('loading');
                const error = document.getElementById('error');
                btn.style.display = 'none';
                loading.classList.add('active');
                error.style.display = 'none';
                try {{
                    const result = await auth.signInWithPopup(provider);
                    const user = result.user;
                    sendUserData(user);
                }} catch (err) {{
                    console.error('登入錯誤:', err);
                    btn.style.display = 'inline-flex';
                    loading.classList.remove('active');
                    error.textContent = '登入失敗: ' + err.message;
                    error.style.display = 'block';
                }}
            }}
            
            async function sendUserData(user) {{
                const token = await user.getIdToken();
                const userData = JSON.stringify({{
                    uid: user.uid, email: user.email,
                    displayName: user.displayName, photoURL: user.photoURL, token: token
                }});
                // 使用 URL hash 傳遞資料
                window.parent.location.hash = 'auth=' + btoa(unescape(encodeURIComponent(userData)));
                window.parent.location.reload();
            }}
            
            // 檢查是否已登入
            auth.onAuthStateChanged((user) => {{
                if (user) {{ sendUserData(user); }}
            }});
        </script>
    </body>
    </html>
    """

def parse_auth_from_url():
    """從 URL hash 解析認證資訊"""
    import urllib.parse
    import base64
    import json
    try:
        # Streamlit 的 query params
        query_params = st.query_params
        if 'auth' in query_params:
            encoded = query_params['auth']
            decoded = base64.b64decode(encoded).decode('utf-8')
            return json.loads(decoded)
    except:
        pass
    return None

def show_user_sidebar():
    """在側邊欄顯示使用者資訊"""
    user = st.session_state.get('user')
    if user:
        with st.sidebar:
            st.markdown("---")
            col1, col2 = st.columns([1, 3])
            with col1:
                if user.get('photoURL'):
                    st.image(user['photoURL'], width=40)
                else:
                    st.markdown("👤")
            with col2:
                st.markdown(f"**{user.get('displayName', '使用者')}**")
                st.caption(user.get('email', ''))
            if st.button("🚪 登出", use_container_width=True, key="logout_btn"):
                st.session_state.authenticated = False
                st.session_state.user = None
                st.query_params.clear()
                st.rerun()

def check_authentication():
    """檢查並處理認證狀態"""
    # 初始化 session state
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'user' not in st.session_state:
        st.session_state.user = None
    
    # 嘗試從 URL 解析認證資訊
    user_data = parse_auth_from_url()
    if user_data:
        st.session_state.authenticated = True
        st.session_state.user = user_data
    
    return st.session_state.authenticated


def xirr(cash_flows):
    try:
        dates, amounts = zip(*cash_flows)
        if len(dates) < 2: return 0.0
        min_date = min(dates)
        days = [(d - min_date).days for d in dates]
        def npv(rate):
            if rate <= -1.0: return float('inf')
            return np.sum(np.array(amounts) / np.power(1 + rate, np.array(days) / 365.0))
        try:
            result = scipy.optimize.newton(npv, 0.1, maxiter=50)
            # Optimization #2: Cap XIRR to reasonable range
            return max(-1.0, min(10.0, result))  # -100% to +1000%
        except:
            return 0.0
    except:
        return 0.0

# ============================================================
# 🚀 應用程式入口
# ============================================================
st.set_page_config(page_title="金雞計算機Galculator+", page_icon="🐔", layout="wide", initial_sidebar_state="expanded")

# 檢查登入狀態
is_authenticated = check_authentication()

if not is_authenticated:
    # 顯示登入頁面
    st.title("🐔 金雞計算機Galculator+")
    st.markdown("**作者：[豬力安](https://richedu168.blogspot.com/)**")
    st.markdown("---")
    st.info("👋 歡迎使用金雞計算機！請先登入以繼續使用。")
    
    # 取得 Firebase 設定並嵌入登入頁面
    firebase_config = get_firebase_config()
    components.html(get_login_html(firebase_config), height=550, scrolling=False)
    st.stop()

# ============================================================
# ✅ 已登入 - 顯示主應用程式
# ============================================================
st.title("🐔 金雞計算機Galculator+")
st.markdown("**作者：[豬力安](https://richedu168.blogspot.com/)**")
st.markdown("---")
show_user_sidebar()

with st.sidebar:
    st.header("⚙️ 參數設定")
    currency_label = "元"
    
    with st.expander("💰 資金設定", expanded=True):
        initial_capital = st.number_input(f"初始投資金額 ({currency_label})", min_value=0, value=0, step=10000)
        monthly_investment = st.number_input(f"每月定期定額金額 ({currency_label})", min_value=0, value=2000, step=1000)
        
    with st.expander("📅 回測時間", expanded=True):
        default_start = datetime(1990, 1, 1)
        default_end = datetime.now()
        start_date = st.date_input("開始日期", default_start, min_value=datetime(1900, 1, 1))
        end_date = st.date_input("結束日期", default_end)
        # Optimization #5: Date validation
        if start_date >= end_date:
            st.error("⚠️ 開始日期必須早於結束日期")
        date_ok = (start_date < end_date)

    st.markdown("---")
    st.subheader("📊 投資組合設定")
    
    if 'portfolios' not in st.session_state:
        st.session_state.portfolios = [{"name": "預設組合", "assets": [{"ticker": "QQQ", "weight": 100}], "withdrawal_enabled": False}]
    
    for p in st.session_state.portfolios:
        if 'withdrawal_enabled' not in p: p['withdrawal_enabled'] = False
        if 'w_rate' not in p: p['w_rate'] = 4.0
        if 'w_inflation' not in p: p['w_inflation'] = 2.0
        if 'w_start_year' not in p: p['w_start_year'] = 1

    selected_portfolio_idx = st.selectbox("選擇編輯的投資組合", range(len(st.session_state.portfolios)), format_func=lambda i: st.session_state.portfolios[i]['name'])

    col_p1, col_p2, col_p3 = st.columns(3)
    with col_p1:
        if st.button("➕ 新增組合") and len(st.session_state.portfolios) < 10:
            st.session_state.portfolios.append({"name": f"組合 {len(st.session_state.portfolios)+1}", "assets": [{"ticker": "QQQ", "weight": 100}], "withdrawal_enabled": False, "w_rate": 4.0, "w_inflation": 2.0, "w_start_year": 1})
            st.rerun()
    with col_p2:
        if st.button("©️ 複製組合") and len(st.session_state.portfolios) < 10:
            src = st.session_state.portfolios[selected_portfolio_idx]
            st.session_state.portfolios.append({"name": src["name"] + " (副本)", "assets": [{"ticker": a["ticker"], "weight": a["weight"]} for a in src["assets"]], "withdrawal_enabled": src.get("withdrawal_enabled", False), "w_rate": src.get("w_rate", 4.0), "w_inflation": src.get("w_inflation", 2.0), "w_start_year": src.get("w_start_year", 1)})
            st.rerun()
    with col_p3:
        if st.button("➖ 刪除組合") and len(st.session_state.portfolios) > 1:
            st.session_state.portfolios.pop(selected_portfolio_idx)
            st.rerun()

    if selected_portfolio_idx >= len(st.session_state.portfolios):
        selected_portfolio_idx = len(st.session_state.portfolios) - 1

    curr_p = st.session_state.portfolios[selected_portfolio_idx]
    curr_p['name'] = st.text_input("組合名稱", curr_p['name'])
    curr_p['withdrawal_enabled'] = st.checkbox("啟用退休提領機制", value=curr_p['withdrawal_enabled'])
    
    if curr_p['withdrawal_enabled']:
        st.markdown("👇 **提領參數設定**")
        curr_p['w_rate'] = st.number_input("年提領率 (%)", 0.0, 100.0, float(curr_p.get('w_rate', 4.0)), step=0.1, key=f"wr_{selected_portfolio_idx}")
        curr_p['w_inflation'] = st.number_input("預估年通膨率 (%)", 0.0, 20.0, float(curr_p.get('w_inflation', 2.0)), step=0.1, key=f"wi_{selected_portfolio_idx}")
        curr_p['w_start_year'] = st.number_input("提領開始年份 (第 N 年)", 1, 100, int(curr_p.get('w_start_year', 1)), key=f"ws_{selected_portfolio_idx}")
        st.caption(f"📅 預計提領開始年份：{start_date.year + curr_p['w_start_year'] - 1} 年")

    assets = curr_p['assets']
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        if st.button("➕ 增加資產") and len(assets) < 10: assets.append({"ticker": "SPY", "weight": 0})
    with col_a2:
        if st.button("➖ 減少資產") and len(assets) > 1: assets.pop()
            
    total_weight = 0
    for i, asset in enumerate(assets):
        cols = st.columns([1, 1])
        with cols[0]:
            asset["ticker"] = st.text_input(f"資產 {i+1}", asset["ticker"], key=f"t_{selected_portfolio_idx}_{i}").upper()
        with cols[1]:
            asset["weight"] = st.number_input(f"權重 (%)", 0, 100, asset["weight"], key=f"w_{selected_portfolio_idx}_{i}")
        total_weight += asset["weight"]
    
    weight_ok = (total_weight == 100)
    if not weight_ok: st.error(f"⚠️ 目前權重：{total_weight}% (需為100%)")
    else: st.success("✅ 權重正確 (100%)")
    
    # Optimization #1: Check for zero capital
    capital_ok = (initial_capital > 0 or monthly_investment > 0)
    if not capital_ok:
        st.warning("💰 初始投資和定期定額都為 0，結果將無意義")

    with st.expander("⚙️ 再平衡設定", expanded=True):
        enable_rebalance = st.checkbox("啟用年度再平衡", value=True)

    # Move button to sidebar bottom
    st.markdown("---")
    # Disable button if weight wrong OR dates invalid
    can_run = weight_ok and date_ok
    run_backtest = st.button("🚀 開始計算", type="primary", disabled=not can_run, use_container_width=True)

@st.cache_data
def fetch_data(tickers, start, end):
    try:
        data = yf.download(list(set(tickers)), start=start, end=end, progress=False)
        return data, None, list(set(tickers))
    except Exception as e:
        return None, str(e), []

def get_stock_data(df, dt, ticker):
    try:
        def get_val(col):
            if isinstance(df.columns, pd.MultiIndex):
                if (col, ticker) in df.columns:
                    val = df.loc[dt, (col, ticker)]
                    return val if not pd.isna(val) else float('nan')
            else:
                if col in df.columns:
                    val = df.loc[dt, col]
                    return val if not pd.isna(val) else float('nan')
            return float('nan')
        p_open, p_close, p_adj_close = get_val('Open'), get_val('Close'), get_val('Adj Close')
        if pd.isna(p_adj_close): p_adj_close = p_close if not pd.isna(p_close) else p_open
        p_adj_open = p_open
        if not pd.isna(p_open) and not pd.isna(p_close) and not pd.isna(p_adj_close) and p_close != 0:
            p_adj_open = p_open * (p_adj_close / p_close)
        elif pd.isna(p_open):
            p_adj_open = p_adj_close
        return {'adj_close': 0.0 if pd.isna(p_adj_close) else float(p_adj_close), 'adj_open': 0.0 if pd.isna(p_adj_open) else float(p_adj_open)}
    except:
        return {'adj_close': 0.0, 'adj_open': 0.0}

if run_backtest:
    all_tickers = set()
    for p in st.session_state.portfolios:
        for a in p['assets']:
            # Optimization: Strict uppercase handling
            tk = a['ticker'].upper()
            if tk != 'CASH0': all_tickers.add(tk)
    all_tickers = list(all_tickers)
    
    # Check if we have any assets (tickers or CASH0)
    has_cash0 = any(a['ticker'].upper() == 'CASH0' for p in st.session_state.portfolios for a in p['assets'])
    
    if not all_tickers and not has_cash0:
        st.error("請至少新增一個有效資產！")
        st.session_state.results = None
    else:
        with st.spinner("正在計算中..."):
            market_data, error, fetched_tickers = fetch_data(all_tickers, start_date, end_date)
            if error:
                st.error(f"錯誤: {error}")
                st.session_state.results = None
            elif market_data is None or len(market_data) == 0:
                st.error("無資料")
                st.session_state.results = None
            else:
                market_data = market_data.ffill()
                # Optimization: Reuse already collected tickers set
                all_active_tickers = set(all_tickers)
                
                valid_starts, debug_info = [], {}
                for t in all_active_tickers:
                    try:
                        if isinstance(market_data.columns, pd.MultiIndex):
                            if ('Adj Close', t) in market_data.columns: fvi = market_data[('Adj Close', t)].first_valid_index()
                            elif ('Close', t) in market_data.columns: fvi = market_data[('Close', t)].first_valid_index()
                            else: fvi = None
                        else:
                            fvi = market_data['Adj Close'].first_valid_index() if 'Adj Close' in market_data.columns else None
                        if fvi: 
                            valid_starts.append(fvi)
                            debug_info[t] = fvi.strftime('%Y-%m-%d')
                    except: pass
                
                # Optimization: Fix crash if no valid data found
                if not valid_starts:
                    st.error("❌ 無法取得有效股價資料。請檢查代碼是否正確，或確認該期間有交易數據。")
                    st.session_state.results = None
                    st.stop()

                common_start = max(valid_starts)
                results_list, monthly_dfs, annual_returns_data = [], {}, {}
                # Color palette for consistent coloring across charts
                color_palette = ['#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3', '#FF6692', '#B6E880', '#FF97FF', '#FECB52']
                portfolio_idx = 0
                figs = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.7, 0.3], subplot_titles=("資產成長趨勢", "年度報酬率 (%)"))

                for p in st.session_state.portfolios:
                    dates = market_data.index[market_data.index >= common_start]
                    if len(dates) == 0: continue
                    
                    cash_account = float(initial_capital)
                    holdings = {a['ticker']: {'shares': 0.0, 'cash_asset_currency': 0.0} for a in p['assets']}
                    alloc_map = {a['ticker']: a['weight']/100.0 for a in p['assets']}
                    total_invested = float(initial_capital)
                    history, xirr_flows = [], []
                    if initial_capital > 0: xirr_flows.append((dates[0], -initial_capital))
                    
                    w_enabled = p.get('withdrawal_enabled', False)
                    w_rate = p.get('w_rate', 4.0) / 100.0
                    w_inf = p.get('w_inflation', 2.0) / 100.0
                    w_start = int(p.get('w_start_year', 1))
                    curr_yr, yr_cnt, ann_budg, cum_wd, prev_mo = -1, 0, 0, 0, -1
                    
                    for d in dates:
                        if d.year != curr_yr:
                            if curr_yr != -1:
                                yr_cnt += 1
                                if ann_budg > 0: ann_budg *= (1 + w_inf)
                            curr_yr = d.year
                            if w_enabled and (yr_cnt + 1) >= w_start and ann_budg == 0:
                                val = cash_account
                                for t,h in holdings.items():
                                    if t == 'CASH0': val += h['cash_asset_currency']
                                    else:
                                        pr = get_stock_data(market_data, d, t)
                                        val += (h['shares'] * pr['adj_close']) + h['cash_asset_currency']
                                ann_budg = val * w_rate
                        
                        is_buy = (d.month != prev_mo)
                        if is_buy: prev_mo = d.month
                        todays_wd = 0
                        
                        if is_buy and w_enabled and ann_budg > 0:
                            tgt = ann_budg / 12.0
                            if cash_account >= tgt:
                                cash_account -= tgt
                                todays_wd = tgt
                            else:
                                need = tgt - cash_account
                                todays_wd += cash_account
                                cash_account = 0
                                for t,h in holdings.items():
                                    if need <= 0: break
                                    pr = get_stock_data(market_data, d, t)
                                    val_base = h['cash_asset_currency']
                                    if val_base >= need:
                                        h['cash_asset_currency'] -= need
                                        todays_wd += need
                                        need = 0
                                    else:
                                        need -= val_base
                                        todays_wd += val_base
                                        h['cash_asset_currency'] = 0
                                        if t!='CASH0' and pr['adj_open']>0:
                                            s_need = need / pr['adj_open']
                                            max_sell = int(h['shares'])
                                            sell = min(int(np.ceil(s_need)), max_sell)
                                            if sell > 0:
                                                proceeds = sell * pr['adj_open']
                                                h['shares'] -= sell
                                                if proceeds >= need:
                                                    cash_account += (proceeds - need)
                                                    todays_wd += need
                                                    need = 0
                                                else:
                                                    todays_wd += proceeds
                                                    need -= proceeds
                            cum_wd += todays_wd
                            if todays_wd > 0: xirr_flows.append((d, todays_wd))
                        
                        # Optimization #4: Skip rebalance in first year (yr_cnt must be > 0)
                        if is_buy and enable_rebalance and d.month == 1 and yr_cnt > 0:
                            cur_vals, tot_pv, rebal_prs = {}, cash_account, {}
                            for t,h in holdings.items():
                                if t=='CASH0': 
                                    cur_vals[t] = h['cash_asset_currency']
                                    tot_pv += h['cash_asset_currency']
                                else:
                                    pr = get_stock_data(market_data, d, t)
                                    rebal_prs[t] = pr['adj_open']
                                    cur_vals[t] = h['shares'] * pr['adj_open']
                                    tot_pv += cur_vals[t]
                            
                            for t in holdings:
                                diff = cur_vals[t] - tot_pv * alloc_map[t]
                                if diff > 0:
                                    if t=='CASH0':
                                        amt = min(diff, holdings[t]['cash_asset_currency'])
                                        holdings[t]['cash_asset_currency'] -= amt
                                        cash_account += amt
                                    elif rebal_prs.get(t, 0) > 0:
                                        n = int(diff / rebal_prs[t])
                                        if n > 0:
                                            holdings[t]['shares'] -= n
                                            cash_account += n * rebal_prs[t]
                            for t in holdings:
                                diff = tot_pv * alloc_map[t] - cur_vals[t]
                                if diff > 0:
                                    if t=='CASH0':
                                        amt = min(diff, cash_account)
                                        holdings[t]['cash_asset_currency'] += amt
                                        cash_account -= amt
                                    elif rebal_prs.get(t, 0) > 0:
                                        amt = min(diff, cash_account)
                                        n = int(amt / rebal_prs[t])
                                        if n > 0:
                                            holdings[t]['shares'] += n
                                            cash_account -= n * rebal_prs[t]

                        if is_buy:
                            if monthly_investment > 0:
                                cash_account += monthly_investment
                                total_invested += monthly_investment
                                xirr_flows.append((d, -monthly_investment))
                            pot = cash_account
                            cash_account = 0
                            for t,h in holdings.items():
                                amt = pot * alloc_map[t]
                                h['cash_asset_currency'] += amt
                                if t!='CASH0':
                                    pr = get_stock_data(market_data, d, t)
                                    if pr['adj_open'] > 0:
                                        n = int(h['cash_asset_currency'] // pr['adj_open'])
                                        if n > 0:
                                            h['shares'] += n
                                            h['cash_asset_currency'] -= n * pr['adj_open']
                        
                        pv = cash_account
                        for t,h in holdings.items():
                            if t=='CASH0': pv += h['cash_asset_currency']
                            else:
                                pr = get_stock_data(market_data, d, t)
                                pv += (h['shares'] * pr['adj_close']) + h['cash_asset_currency']
                        history.append({'Date': d, 'Total Value': pv, 'Invested Capital': total_invested, 'Withdrawal': todays_wd})
                    
                    df_res = pd.DataFrame(history).set_index('Date')
                    if not df_res.empty:
                        final_v = df_res['Total Value'].iloc[-1]
                        if final_v > 0: xirr_flows.append((dates[-1], final_v))
                        yr_diff = (df_res.index[-1] - df_res.index[0]).days / 365.25
                        dur_str = f"{yr_diff:.1f} 年 ({df_res.index[0].strftime('%Y-%m')} ~ {df_res.index[-1].strftime('%Y-%m')})"
                        
                        # MDD with detailed timing
                        roll_max = df_res['Total Value'].cummax()
                        dd = (df_res['Total Value'] - roll_max) / roll_max
                        mdd = dd.min()
                        if mdd < 0:
                            mdd_date = dd.idxmin()
                            # Find peak date before MDD
                            peak_date = roll_max[:mdd_date].idxmax()
                            # Find recovery date (if any)
                            post_mdd = df_res.loc[mdd_date:, 'Total Value']
                            recovery_mask = post_mdd >= roll_max[mdd_date]
                            if recovery_mask.any():
                                recovery_date = post_mdd[recovery_mask].index[0]
                                recovery_days = (recovery_date - mdd_date).days
                                mdd_str = f"{mdd*100:.2f}% (📉{peak_date.strftime('%Y-%m')} → 📍{mdd_date.strftime('%Y-%m')} → 📈{recovery_date.strftime('%Y-%m')}, 回復{recovery_days}天)"
                            else:
                                mdd_str = f"{mdd*100:.2f}% (📉{peak_date.strftime('%Y-%m')} → 📍{mdd_date.strftime('%Y-%m')}, 尚未回復)"
                        else:
                            mdd_str = "0.00%"

                        results_list.append({"組合名稱": p['name'], "回測時間": dur_str, "總投入本金": total_invested, "資產終值": final_v, "總提領金額": cum_wd, "總損益": (final_v + cum_wd) - total_invested, "XIRR": f"{xirr(xirr_flows)*100:.2f}%", "MDD": mdd_str})
                        
                        try: monthly_dfs[p['name']] = df_res.resample('ME').agg({'Total Value':'last', 'Invested Capital':'last', 'Withdrawal':'sum'})
                        except: monthly_dfs[p['name']] = df_res.resample('M').agg({'Total Value':'last', 'Invested Capital':'last', 'Withdrawal':'sum'})
                        
                        # Use consistent color for this portfolio
                        port_color = color_palette[portfolio_idx % len(color_palette)]
                        figs.add_trace(go.Scatter(x=df_res.index, y=df_res['Total Value'], mode='lines', name=f"{p['name']} (市值)", line=dict(color=port_color)), row=1, col=1)
                        wd_pts = df_res[df_res['Withdrawal'] > 0]
                        if not wd_pts.empty:
                            figs.add_trace(go.Scatter(x=wd_pts.index, y=wd_pts['Total Value'], mode='markers', marker=dict(size=5,color='red'), showlegend=False), row=1, col=1)

                        years = sorted(df_res.index.year.unique())
                        ann_ret_x, ann_ret_y, ann_ret_labels = [], [], {}
                        
                        for i, y in enumerate(years):
                            df_y = df_res[df_res.index.year == y]
                            if df_y.empty: continue
                            end_val = df_y['Total Value'].iloc[-1]
                            if i == 0:
                                start_val = df_y['Total Value'].iloc[0]
                            else:
                                df_prev = df_res[df_res.index.year == years[i-1]]
                                start_val = df_prev['Total Value'].iloc[-1] if not df_prev.empty else df_y['Total Value'].iloc[0]
                            ret = (end_val / start_val) - 1 if start_val > 0 else 0
                            ann_ret_x.append(datetime(y, 7, 1))
                            ann_ret_y.append(ret * 100)  # Convert to percentage
                            ann_ret_labels[y] = ret

                        # Use same color as the line chart for this portfolio
                        figs.add_trace(go.Bar(x=ann_ret_x, y=ann_ret_y, name=f"{p['name']} (年報酬%)", marker_color=port_color, opacity=0.7), row=2, col=1)
                        annual_returns_data[p['name']] = ann_ret_labels
                        portfolio_idx += 1

                figs.update_xaxes(dtick="M12", tickformat="%Y")
                figs.update_yaxes(ticksuffix="%", row=2, col=1)  # Add % suffix to Y-axis
                st.session_state.results = {'summary': results_list, 'monthly_data': monthly_dfs, 'annual_returns': annual_returns_data, 'fig': figs, 'common_start': common_start, 'debug': debug_info}

if st.session_state.get('results'):
    res = st.session_state.results
    
    with st.expander("ℹ️ 核心邏輯說明（給新手的白話文版）", expanded=False):
        st.markdown("""
### 🐔 這個計算機在幹嘛？
想像你有一隻會下金蛋的母雞（投資組合），這個工具幫你模擬：**如果從過去某個時間點開始養這隻雞，現在會變多大隻？**

---

### 📌 關鍵功能說明

#### 1️⃣ 定期定額 = 每月餵雞飼料 🌾
- 每個月固定投入一筆錢買股票
- 系統會用**真實的歷史開盤價**來計算你買了幾股
- 買不到整數股的零錢會留著，下個月繼續買

#### 2️⃣ 還原股價 = 公平計算真實報酬 📊
- 股票會配息、會拆股，歷史價格需要「還原」才準確
- 例如：一張 100 元的股票配 5 元現金，還原後等於你用 95 元買到
- 這樣才能正確計算你的真實獲利

#### 3️⃣ CASH0 = 現金部位 💵
- 在資產代號輸入 `CASH0` 代表「現金不投資」
- 例如：80% QQQ + 20% CASH0 = 只投八成，兩成放著

#### 4️⃣ 再平衡 = 每年整理雞舍 🔄
- 每年一月，系統會自動調整各資產比例回到你設定的目標
- 例如：設定 50:50，但漲跌後變成 60:40，就會賣掉一些漲多的，買進跌多的
- 這是經典的「賣高買低」策略

#### 5️⃣ 提領機制 = 退休後每月領蛋 🥚
- 開啟後，系統會模擬你退休領錢的情境
- **現金優先**：先從帳戶現金領
- **賣股補足**：現金不夠就賣股票
- **通膨調整**：每年領的錢會隨通膨增加

---

### 📈 看報告時的重點指標

| 指標 | 白話解釋 |
|------|----------|
| **XIRR** | 你的真實年化報酬率（考慮每筆進出的時間點） |
| **MDD** | 最大回撤 = 從高點跌到最慘時虧了多少%（抗壓測試）|
| **年度報酬率** | 當年底淨值 ÷ 當年初淨值 - 1 |

---

### ⚠️ 提領模式下的報酬率說明

當你開啟「退休提領機制」時，年度報酬率的計算方式是：

**年度報酬率 = (年底帳戶淨值 ÷ 年初帳戶淨值) - 1**

🔔 **重點**：這個數字**不包含**你領走的錢！

舉例：
- 年初帳戶有 100 萬
- 這一年你領走了 4 萬
- 年底帳戶剩 102 萬
- 年度報酬率 = (102 ÷ 100) - 1 = **+2%**

但實際上，如果把領走的錢也算進來：
- 總財富 = 102 + 4 = 106 萬
- 真實報酬 = (106 ÷ 100) - 1 = **+6%**

💡 **為什麼這樣設計？** 因為年度報酬率主要是讓你觀察「帳戶還剩多少」的變化趨勢，判斷資產是否足夠支撐退休提領。如果想看「投資效率」，請參考 **XIRR** 指標，它會正確計算每筆進出（包含提領）的時間價值。

---

💡 **小提醒**：過去績效不代表未來，但可以幫你了解不同策略在歷史大事件（網路泡沫、金融海嘯、COVID）中的表現！
        """)

    if res['debug']:
        with st.expander("🔎 日期診斷"):
            st.write(res['debug'])
            st.info(f"統一回測起算日：{res['common_start'].strftime('%Y-%m-%d')}")

    # Fix: Use stored tab state to prevent resetting to first tab
    if 'active_tab' not in st.session_state:
        st.session_state.active_tab = "📈 資產成長圖"

    # Use radio button as a stable navigation substitute for st.tabs
    # This ensures the active view remains selected even after inner widget interactions trigger reruns
    active_tab = st.radio(
        "選擇檢視模式", 
        ["📈 資產成長圖", "📊 績效指標", "📝 詳細數據"], 
        horizontal=True, 
        label_visibility="collapsed",
        key='active_tab'
    )
    st.markdown("---")
    
    if active_tab == "📈 資產成長圖":
        res['fig'].update_layout(height=800, hovermode="x unified", title="資產成長完整分析")
        st.plotly_chart(res['fig'], use_container_width=True)
        
    elif active_tab == "📊 績效指標":
        st.markdown("### 🏆 總體績效")
        st.dataframe(pd.DataFrame(res['summary']).style.format({"總投入本金":"{:,.0f}", "資產終值":"{:,.0f}", "總提領金額":"{:,.0f}", "總損益":"{:,.0f}"}))
        st.markdown("### 📅 歷年報酬率明細")
        st.caption("計算方式：當年底淨值 ÷ 當年初淨值 - 1")
        if res.get('annual_returns'):
            df_ann = pd.DataFrame(res['annual_returns'])
            if not df_ann.empty:
                df_ann.index = df_ann.index.map(str)
                st.dataframe(df_ann.style.format("{:.2%}"))
        
    elif active_tab == "📝 詳細數據":
        opts = list(res['monthly_data'].keys())
        # Fix: Ensure selection stability
        idx = 0
        if 'view_portfolio_selector' in st.session_state:
            curr = st.session_state.view_portfolio_selector
            if curr in opts:
                idx = opts.index(curr)
        
        sel = st.selectbox("選擇投資組合", opts, index=idx, key='view_portfolio_selector')
        if sel: st.dataframe(res['monthly_data'][sel].style.format("{:,.0f}"))
