import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import scipy.optimize
from datetime import datetime, timedelta
import re


TICKER_PATTERN = re.compile(r"^[A-Z0-9.^=-]{1,20}$")
TAIWAN_CODE_PATTERN = re.compile(r"^\d{4,6}[A-Z]?$")
KNOWN_MINIMUM_SAFE_DATES = {
    "00631L.TW": pd.Timestamp("2015-08-24"),
}


def normalize_ticker(value):
    """Normalize a user-entered symbol and auto-add Taiwan's listed suffix."""
    ticker = str(value or '').strip().upper()
    if ticker != 'CASH0' and TAIWAN_CODE_PATTERN.fullmatch(ticker):
        return f"{ticker}.TW", True
    return ticker, False


def apply_known_yahoo_repairs(data, tickers):
    """Repair confirmed Yahoo split discontinuities without guessing unknown ones."""
    if data is None or data.empty or "0050.TW" not in tickers:
        return data, []

    repaired = data.copy()
    cutoff = pd.Timestamp("2014-01-02")
    before_cutoff = repaired.index < cutoff
    if not before_cutoff.any():
        return repaired, []

    price_columns = ('Open', 'High', 'Low', 'Close', 'Adj Close')
    if isinstance(repaired.columns, pd.MultiIndex):
        for column_name in price_columns:
            column = (column_name, "0050.TW")
            if column in repaired.columns:
                repaired.loc[before_cutoff, column] = repaired.loc[before_cutoff, column] / 4.0
        volume_column = ('Volume', "0050.TW")
        if volume_column in repaired.columns:
            repaired.loc[before_cutoff, volume_column] = repaired.loc[before_cutoff, volume_column] * 4.0
    elif len(tickers) == 1:
        for column_name in price_columns:
            if column_name in repaired.columns:
                repaired.loc[before_cutoff, column_name] = repaired.loc[before_cutoff, column_name] / 4.0
        if 'Volume' in repaired.columns:
            repaired.loc[before_cutoff, 'Volume'] = repaired.loc[before_cutoff, 'Volume'] * 4.0

    return repaired, ["0050.TW：已修正 Yahoo 在 2014-01-02 前漏套用的 4:1 分割還原。"]


def find_suspicious_price_jumps(data, tickers):
    """Find extreme adjusted-price jumps that likely indicate bad corporate-action data."""
    issues = []
    for ticker in tickers:
        series = None
        if isinstance(data.columns, pd.MultiIndex):
            for column_name in ('Adj Close', 'Close'):
                if (column_name, ticker) in data.columns:
                    series = data[(column_name, ticker)]
                    break
        elif len(tickers) == 1:
            for column_name in ('Adj Close', 'Close'):
                if column_name in data.columns:
                    series = data[column_name]
                    break
        if series is None:
            continue

        if ticker in KNOWN_MINIMUM_SAFE_DATES:
            series = series[series.index >= KNOWN_MINIMUM_SAFE_DATES[ticker]]
        threshold = 0.30 if ticker.endswith(('.TW', '.TWO')) else 0.50
        jumps = series.dropna().pct_change(fill_method=None).abs()
        suspicious = jumps[jumps > threshold]
        for event_date, change in suspicious.items():
            issues.append(f"{ticker} 在 {event_date:%Y-%m-%d} 出現 {change:.1%} 的異常跳價")
    return issues


def sheet_safe_text(value):
    """Prevent spreadsheet formula execution for identity-provider text."""
    text = str(value or '')
    if text.startswith(('=', '+', '-', '@')):
        return "'" + text
    return text

# ============================================================
# 📊 Google Sheets 使用者記錄功能
# ============================================================
def record_user_login(debug=False):
    """記錄使用者登入到 Google Sheets
    
    Args:
        debug: 如果為 True，會在側邊欄顯示除錯訊息
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        # 檢查是否已記錄過（避免每次 rerun 都記錄）
        if st.session_state.get('user_recorded', False):
            if debug:
                st.sidebar.success("✅ 使用者已記錄過")
            return
        
        # 從 secrets 讀取 Google Sheets 設定
        if 'gsheets' not in st.secrets:
            if debug:
                st.sidebar.warning("⚠️ 未設定 [gsheets]，跳過記錄")
            return
        
        if debug:
            st.sidebar.info("🔄 正在連接 Google Sheets...")
        
        # 設定憑證
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets'
        ]
        
        # 從 secrets 取得服務帳戶憑證
        credentials_dict = {
            "type": st.secrets["gsheets"]["type"],
            "project_id": st.secrets["gsheets"]["project_id"],
            "private_key_id": st.secrets["gsheets"]["private_key_id"],
            "private_key": st.secrets["gsheets"]["private_key"],
            "client_email": st.secrets["gsheets"]["client_email"],
            "client_id": st.secrets["gsheets"]["client_id"],
            "auth_uri": st.secrets["gsheets"]["auth_uri"],
            "token_uri": st.secrets["gsheets"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["gsheets"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["gsheets"]["client_x509_cert_url"]
        }
        
        credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
        client = gspread.authorize(credentials)
        
        if debug:
            st.sidebar.info("🔄 正在開啟試算表...")
        
        # 開啟試算表
        spreadsheet_id = st.secrets["gsheets"]["spreadsheet_id"]
        sheet = client.open_by_key(spreadsheet_id).sheet1
        
        # 取得使用者資訊
        user_email = sheet_safe_text(getattr(st.user, 'email', 'unknown'))
        user_name = sheet_safe_text(getattr(st.user, 'name', '') or user_email)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if debug:
            st.sidebar.info(f"🔄 使用者: {user_email}")
        
        # 檢查使用者是否已存在（新版 gspread 的 find 返回 None 而非拋出例外）
        cell = sheet.find(user_email, in_column=1)
        if cell:
            # 使用者存在，更新最後登入時間和登入次數
            row = cell.row
            current_count = int(sheet.cell(row, 5).value or 0)
            sheet.update_cell(row, 4, now)  # 更新最後登入時間
            sheet.update_cell(row, 5, current_count + 1)  # 更新登入次數
            if debug:
                st.sidebar.success(f"✅ 已更新使用者記錄（第 {row} 列）")
        else:
            # 新使用者，新增一列
            sheet.append_row([user_email, user_name, now, now, 1])
            if debug:
                st.sidebar.success("✅ 已新增使用者記錄")
        
        # 標記已記錄
        st.session_state.user_recorded = True
        
    except Exception as e:
        # 顯示錯誤訊息以便除錯
        if debug:
            st.sidebar.error(f"❌ Google Sheets 錯誤: {str(e)}")


def xirr(cash_flows):
    try:
        dates, amounts = zip(*cash_flows)
        if len(dates) < 2 or not any(amount < 0 for amount in amounts) or not any(amount > 0 for amount in amounts):
            return None
        min_date = min(dates)
        days = [(d - min_date).days for d in dates]
        def npv(rate):
            if rate <= -1.0: return float('inf')
            return np.sum(np.array(amounts) / np.power(1 + rate, np.array(days) / 365.0))
        try:
            cash_flow_scale = max(sum(abs(amount) for amount in amounts), 1.0)
            if abs(npv(0.0)) <= cash_flow_scale * 1e-10:
                return 0.0
            result = scipy.optimize.newton(npv, 0.1, maxiter=50)
            return float(result) if np.isfinite(result) and result > -1.0 else None
        except (RuntimeError, OverflowError, ZeroDivisionError, ValueError, FloatingPointError):
            return None
    except (TypeError, ValueError):
        return None


def validate_portfolios(portfolios):
    """Return user-facing validation errors for all portfolios."""
    errors = []
    names = []

    for portfolio_index, portfolio in enumerate(portfolios, start=1):
        name = str(portfolio.get('name', '')).strip()
        display_name = name or f"組合 {portfolio_index}"
        names.append(name.casefold())

        if not name:
            errors.append(f"{display_name}：請輸入組合名稱")

        assets = portfolio.get('assets', [])
        tickers = [str(asset.get('ticker', '')).strip().upper() for asset in assets]
        if any(not ticker for ticker in tickers):
            errors.append(f"{display_name}：資產代碼不可空白")

        invalid_formats = sorted({ticker for ticker in tickers if ticker and not TICKER_PATTERN.fullmatch(ticker)})
        if invalid_formats:
            errors.append(f"{display_name}：資產代碼格式不正確（{', '.join(invalid_formats)}）")

        duplicate_tickers = sorted({ticker for ticker in tickers if ticker and tickers.count(ticker) > 1})
        if duplicate_tickers:
            errors.append(f"{display_name}：資產代碼重複（{', '.join(duplicate_tickers)}）")

        total_weight = sum(int(asset.get('weight', 0)) for asset in assets)
        if total_weight != 100:
            errors.append(f"{display_name}：權重合計為 {total_weight}%，必須等於 100%")

    duplicate_names = sorted({name for name in names if name and names.count(name) > 1})
    if duplicate_names:
        errors.append("投資組合名稱不可重複")

    return errors


def first_valid_price_index(data, ticker):
    """Find the first usable adjusted/close price for a downloaded ticker."""
    if data is None or data.empty:
        return None

    if isinstance(data.columns, pd.MultiIndex):
        for column_name in ('Adj Close', 'Close'):
            if (column_name, ticker) in data.columns:
                return data[(column_name, ticker)].first_valid_index()
        return None

    for column_name in ('Adj Close', 'Close'):
        if column_name in data.columns:
            return data[column_name].first_valid_index()
    return None


def update_unit_nav(previous_value, ending_value, net_external_flow, previous_nav):
    """Calculate a cash-flow-neutral daily NAV using start-of-day flows."""
    adjusted_start = previous_value + net_external_flow
    if adjusted_start <= 0 or previous_nav <= 0:
        return previous_nav
    period_return = (ending_value - adjusted_start) / adjusted_start
    return previous_nav * (1 + period_return)

# ============================================================
# 🚀 應用程式入口
# ============================================================
st.set_page_config(page_title="金雞計算機Galculator+", page_icon="🐔", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
:root { --gp-green: #175c45; --gp-gold: #c99720; --gp-ink: #17221e; }
.stApp { color: var(--gp-ink); }
.block-container { max-width: 1120px; padding-top: 1.5rem; padding-bottom: 3rem; }
h1 { font-size: 2.15rem !important; line-height: 1.25 !important; }
h2 { font-size: 1.55rem !important; line-height: 1.35 !important; }
h3 { font-size: 1.25rem !important; }
p, label, [data-testid="stCaptionContainer"] { line-height: 1.65 !important; }
[data-testid="stWidgetLabel"] p { font-size: 1.05rem !important; font-weight: 650 !important; }
.stButton > button, .stDownloadButton > button {
    min-height: 48px; border-radius: 6px; font-size: 1.05rem; font-weight: 700;
}
.stTextInput input, .stNumberInput input, [data-baseweb="select"] > div {
    min-height: 48px; font-size: 1.05rem !important;
}
[data-testid="stMetricValue"] { font-size: 1.85rem !important; }
[data-testid="stMetricLabel"] { font-size: 1rem !important; }
[data-testid="stRadio"] [role="radiogroup"] { flex-wrap: wrap; gap: .4rem 1rem; }
[data-testid="stAlert"] { border-radius: 6px; }
@media (max-width: 768px) {
    .block-container { padding: .8rem .75rem 2rem; }
    h1 { font-size: 1.7rem !important; }
    h2 { font-size: 1.35rem !important; }
    .stButton > button { width: 100%; }
    [data-testid="stMetricValue"] { font-size: 1.55rem !important; }
}
</style>
""", unsafe_allow_html=True)

def get_login_provider():
    """Return a named OIDC provider when secrets use [auth.google]."""
    auth_config = st.secrets.get("auth", {})
    if hasattr(auth_config, "get") and auth_config.get("google"):
        return "google"
    return None

def login_with_google():
    provider = get_login_provider()
    if provider:
        st.login(provider)
    else:
        st.login()

# ============================================================
# 🔐 使用 Streamlit 原生 OIDC 認證 (Google OAuth)
# ============================================================
# 檢查是否已登入
if not st.user.is_logged_in:
    # 顯示登入頁面
    st.markdown("""
    <style>
    .login-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 48px 20px;
        background: #175c45;
        border-top: 6px solid #c99720;
        border-radius: 8px;
        margin: 40px auto;
        max-width: 500px;
        box-shadow: 0 12px 28px rgba(0,0,0,0.18);
    }
    .login-logo { font-size: 80px; margin-bottom: 20px; }
    .login-title { color: white; font-size: 36px; font-weight: bold; margin-bottom: 10px; }
    .login-subtitle { color: rgba(255,255,255,0.8); font-size: 16px; margin-bottom: 30px; }
    </style>
    <div class="login-container">
        <div class="login-logo">🐔</div>
        <div class="login-title">金雞計算機</div>
        <div class="login-subtitle">Galculator+ 投資回測工具</div>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.button("🔐 使用 Google 帳號登入", on_click=login_with_google, use_container_width=True, type="primary")
        auth_debug_enabled = st.secrets.get("debug_auth", False) or st.secrets.get("auth", {}).get("debug_auth", False)
        if auth_debug_enabled:
            st.caption(f"Auth debug: is_logged_in={st.user.is_logged_in}, provider={get_login_provider() or 'default'}, user_keys={list(st.user.to_dict().keys())}")
        
        # 隱私權說明
        st.caption("🔒 登入即表示您同意我們的隱私權政策")
        
        with st.expander("📋 隱私權說明", expanded=False):
            st.markdown("""
            **我們收集的資料：**
            - 您的 Google 帳號 Email
            - 您的 Google 帳號顯示名稱
            - 登入時間記錄
            
            **資料用途：**
            - 提供個人化服務體驗
            - 寄送產品更新、活動資訊或投資相關內容
            - 服務改善與統計分析
            
            **資料保護：**
            - 我們不會將您的資料出售給第三方
            - 資料安全儲存於 Google 服務
            
            **您的權利：**
            - 您可隨時要求查看、更正或刪除您的個人資料
            - 如需退訂行銷郵件，請點擊郵件中的取消訂閱連結
            - 如有疑問或希望查看、更正、刪除資料，請聯繫：[ju888.lee@gmail.com](mailto:ju888.lee@gmail.com)
            """)
    st.stop()

# ============================================================
# ✅ 已登入 - 記錄使用者並顯示資訊
# ============================================================
# 記錄使用者到 Google Sheets
record_user_login()

def show_user_sidebar():
    """在側邊欄顯示使用者資訊"""
    with st.sidebar:
        st.markdown("---")
        col1, col2 = st.columns([1, 3])
        with col1:
            if hasattr(st.user, 'picture') and st.user.picture:
                st.image(st.user.picture, width=40)
            else:
                st.markdown("👤")
        with col2:
            name = getattr(st.user, 'name', None) or getattr(st.user, 'email', '使用者')
            st.markdown(f"**{name}**")
            if hasattr(st.user, 'email'):
                st.caption(st.user.email)
        st.button("🚪 登出", on_click=st.logout, use_container_width=True)

# ============================================================
# ✅ 已登入 - 顯示主應用程式
# ============================================================
st.title("🐔 金雞計算機Galculator+")
st.caption("用歷史資料比較投資方式。過去績效不代表未來表現。")
show_user_sidebar()

st.header("開始設定")
st.write("依照下面四個步驟設定，完成後按下「開始計算」。")
currency_label = "元"

setup_col1, setup_col2 = st.columns(2)
with setup_col1:
    with st.expander("步驟 1｜投入多少錢", expanded=True):
        initial_capital = st.number_input(f"初始投資金額 ({currency_label})", min_value=0, value=0, step=10000)
        monthly_investment = st.number_input(f"每月定期定額金額 ({currency_label})", min_value=0, value=2000, step=1000)

with setup_col2:
    with st.expander("步驟 2｜選擇回測期間", expanded=True):
        default_start = datetime(1990, 1, 1)
        default_end = datetime.now()
        start_date = st.date_input("開始日期", default_start, min_value=datetime(1900, 1, 1), max_value=datetime.now())
        end_date = st.date_input("結束日期", default_end, min_value=datetime(1900, 1, 1), max_value=datetime.now())
        if start_date >= end_date:
            st.error("⚠️ 開始日期必須早於結束日期")
        date_ok = (start_date < end_date)

st.markdown("---")
st.subheader("步驟 3｜設定投資組合")

if 'portfolios' not in st.session_state:
    st.session_state.portfolios = [{"name": "預設組合", "assets": [{"ticker": "QQQ", "weight": 100}], "withdrawal_enabled": False}]

for p in st.session_state.portfolios:
    if 'withdrawal_enabled' not in p: p['withdrawal_enabled'] = False
    if 'w_rate' not in p: p['w_rate'] = 4.0
    if 'w_inflation' not in p: p['w_inflation'] = 2.0
    if 'w_start_year' not in p: p['w_start_year'] = 1

selected_portfolio_idx = st.selectbox("目前編輯的投資組合", range(len(st.session_state.portfolios)), format_func=lambda i: st.session_state.portfolios[i]['name'])

col_p1, col_p2, col_p3 = st.columns(3)
with col_p1:
    if st.button("➕ 新增組合", use_container_width=True) and len(st.session_state.portfolios) < 10:
        st.session_state.portfolios.append({"name": f"組合 {len(st.session_state.portfolios)+1}", "assets": [{"ticker": "QQQ", "weight": 100}], "withdrawal_enabled": False, "w_rate": 4.0, "w_inflation": 2.0, "w_start_year": 1})
        st.rerun()
with col_p2:
    if st.button("📋 複製組合", use_container_width=True) and len(st.session_state.portfolios) < 10:
        src = st.session_state.portfolios[selected_portfolio_idx]
        st.session_state.portfolios.append({"name": src["name"] + " (副本)", "assets": [{"ticker": a["ticker"], "weight": a["weight"]} for a in src["assets"]], "withdrawal_enabled": src.get("withdrawal_enabled", False), "w_rate": src.get("w_rate", 4.0), "w_inflation": src.get("w_inflation", 2.0), "w_start_year": src.get("w_start_year", 1)})
        st.rerun()
with col_p3:
    if st.button("🗑️ 刪除組合", use_container_width=True, disabled=len(st.session_state.portfolios) <= 1):
        st.session_state.portfolios.pop(selected_portfolio_idx)
        for portfolio_index in range(10):
            st.session_state.pop(f"name_{portfolio_index}", None)
            st.session_state.pop(f"preset_{portfolio_index}", None)
            for asset_index in range(10):
                st.session_state.pop(f"t_{portfolio_index}_{asset_index}", None)
                st.session_state.pop(f"w_{portfolio_index}_{asset_index}", None)
        st.rerun()

if selected_portfolio_idx >= len(st.session_state.portfolios):
    selected_portfolio_idx = len(st.session_state.portfolios) - 1

curr_p = st.session_state.portfolios[selected_portfolio_idx]
curr_p['name'] = st.text_input("組合名稱", curr_p['name'], key=f"name_{selected_portfolio_idx}")

preset_options = {
    "自行設定": None,
    "台灣大型股｜0050 100%": [{"ticker": "0050.TW", "weight": 100}],
    "美國大型股｜SPY 100%": [{"ticker": "SPY", "weight": 100}],
    "美國科技股｜QQQ 100%": [{"ticker": "QQQ", "weight": 100}],
    "股債平衡｜SPY 60% + BND 40%": [{"ticker": "SPY", "weight": 60}, {"ticker": "BND", "weight": 40}],
    "穩健配置｜SPY 40% + BND 40% + 現金 20%": [{"ticker": "SPY", "weight": 40}, {"ticker": "BND", "weight": 40}, {"ticker": "CASH0", "weight": 20}],
}
preset_col1, preset_col2 = st.columns([2, 1])
with preset_col1:
    selected_preset = st.selectbox("常用組合範例", list(preset_options), key=f"preset_{selected_portfolio_idx}")
with preset_col2:
    st.write("")
    if st.button("套用這個範例", use_container_width=True, disabled=preset_options[selected_preset] is None):
        curr_p['assets'] = [asset.copy() for asset in preset_options[selected_preset]]
        for asset_index in range(10):
            st.session_state.pop(f"t_{selected_portfolio_idx}_{asset_index}", None)
            st.session_state.pop(f"w_{selected_portfolio_idx}_{asset_index}", None)
        st.rerun()

assets = curr_p['assets']
st.info("臺灣上市商品可直接輸入 0050、2330 或 00631L，系統會自動補上 `.TW`。上櫃商品請完整輸入，例如 `6488.TWO`。")
st.caption("股價資料來自 Yahoo Finance；計算前請確認下方顯示的實際查詢代碼。")
col_a1, col_a2 = st.columns(2)
with col_a1:
    if st.button("➕ 增加一項資產", use_container_width=True) and len(assets) < 10:
        assets.append({"ticker": "SPY", "weight": 0})
        st.rerun()
with col_a2:
    if st.button("➖ 移除最後一項", use_container_width=True, disabled=len(assets) <= 1):
        removed_index = len(assets) - 1
        assets.pop()
        st.session_state.pop(f"t_{selected_portfolio_idx}_{removed_index}", None)
        st.session_state.pop(f"w_{selected_portfolio_idx}_{removed_index}", None)
        st.rerun()

total_weight = 0
for i, asset in enumerate(assets):
    cols = st.columns([2, 1])
    with cols[0]:
        entered_ticker = st.text_input(f"第 {i+1} 項資產代碼", asset["ticker"], key=f"t_{selected_portfolio_idx}_{i}")
        asset["ticker"], suffix_added = normalize_ticker(entered_ticker)
        if suffix_added:
            st.caption(f"實際查詢：{asset['ticker']}（已自動補上 .TW）")
    with cols[1]:
        asset["weight"] = st.number_input(f"比例 (%)", 0, 100, asset["weight"], key=f"w_{selected_portfolio_idx}_{i}")
    total_weight += asset["weight"]

with st.expander("進階設定｜退休提領與年度再平衡", expanded=False):
    curr_p['withdrawal_enabled'] = st.checkbox("啟用退休提領機制", value=curr_p['withdrawal_enabled'])
    if curr_p['withdrawal_enabled']:
        curr_p['w_rate'] = st.number_input("年提領率 (%)", 0.0, 100.0, float(curr_p.get('w_rate', 4.0)), step=0.1, key=f"wr_{selected_portfolio_idx}")
        curr_p['w_inflation'] = st.number_input("預估年通膨率 (%)", 0.0, 20.0, float(curr_p.get('w_inflation', 2.0)), step=0.1, key=f"wi_{selected_portfolio_idx}")
        curr_p['w_start_year'] = st.number_input("提領開始年份 (第 N 年)", 1, 100, int(curr_p.get('w_start_year', 1)), key=f"ws_{selected_portfolio_idx}")
        st.caption(f"📅 預計提領開始年份：{start_date.year + curr_p['w_start_year'] - 1} 年")
    enable_rebalance = st.checkbox("每年一月調整回原本比例", value=True)

portfolio_errors = validate_portfolios(st.session_state.portfolios)
selected_tickers = {
    asset['ticker']
    for portfolio in st.session_state.portfolios
    for asset in portfolio['assets']
}
data_window_errors = []
data_window_notices = []
for ticker, safe_date in KNOWN_MINIMUM_SAFE_DATES.items():
    if ticker not in selected_tickers or start_date >= safe_date.date():
        continue
    if end_date < safe_date.date():
        data_window_errors.append(
            f"{ticker}：Yahoo 在 {safe_date:%Y-%m-%d} 前的歷史價格有多處錯置，這段期間無法可靠回測"
        )
    else:
        data_window_notices.append(
            f"{ticker}：Yahoo 早期資料有多處錯置，實際回測將自動從 {safe_date:%Y-%m-%d} 開始"
        )
portfolio_errors.extend(data_window_errors)
if portfolio_errors:
    st.error("請先修正以下設定：\n\n- " + "\n- ".join(portfolio_errors))
else:
    st.success("✅ 所有投資組合設定正確")
if data_window_notices:
    st.warning("資料品質提醒：\n\n- " + "\n- ".join(data_window_notices))

capital_ok = (initial_capital > 0 or monthly_investment > 0)
if not capital_ok:
    st.warning("初始投資和每月投入不可同時為 0 元")

st.markdown("---")
st.subheader("步驟 4｜確認並開始計算")
years = max(0, end_date.year - start_date.year)
portfolio_summary = "；".join(
    f"{p['name']}：" + "、".join(f"{a['ticker']} {a['weight']}%" for a in p['assets'])
    for p in st.session_state.portfolios
)
st.info(f"初始投入 {initial_capital:,.0f} 元，每月投入 {monthly_investment:,.0f} 元，回測約 {years} 年。\n\n{portfolio_summary}")
can_run = not portfolio_errors and date_ok and capital_ok
run_backtest = st.button("🚀 開始計算", type="primary", disabled=not can_run, use_container_width=True)

@st.cache_data(ttl=3600, max_entries=64)
def fetch_data(tickers, start, end):
    try:
        if not tickers:
            return pd.DataFrame(), None, [], [], []
        unique_tickers = sorted(set(tickers))
        data = yf.download(
            unique_tickers,
            start=start,
            end=end + timedelta(days=1),
            progress=False,
            auto_adjust=False,
            actions=True,
            repair=True,
            timeout=15,
        )
        data, repair_notices = apply_known_yahoo_repairs(data, unique_tickers)
        quality_issues = find_suspicious_price_jumps(data, unique_tickers)
        return data, None, unique_tickers, repair_notices, quality_issues
    except Exception as e:
        return None, str(e), [], [], []

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
    except (KeyError, TypeError, ValueError):
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
            market_data, error, fetched_tickers, repair_notices, quality_issues = fetch_data(all_tickers, start_date, end_date)
            if error:
                st.error(f"錯誤: {error}")
                st.session_state.results = None
            elif all_tickers and (market_data is None or len(market_data) == 0):
                st.error("無資料")
                st.session_state.results = None
            else:
                if repair_notices:
                    st.info("資料修正：\n\n- " + "\n- ".join(repair_notices))
                if quality_issues:
                    st.error(
                        "偵測到疑似漏算分割、反分割或錯價，為避免產生誤導結果，已停止計算：\n\n- "
                        + "\n- ".join(quality_issues[:5])
                        + "\n\n請縮短回測期間，或將商品代碼與日期寄到 ju888.lee@gmail.com 協助確認。"
                    )
                    st.session_state.results = None
                    st.stop()
                market_data = market_data.ffill() if not market_data.empty else market_data
                all_active_tickers = set(all_tickers)

                valid_starts, debug_info = [], {}
                for t in all_active_tickers:
                    fvi = first_valid_price_index(market_data, t)
                    if fvi:
                        if t in KNOWN_MINIMUM_SAFE_DATES:
                            fvi = max(fvi, KNOWN_MINIMUM_SAFE_DATES[t])
                        valid_starts.append(fvi)
                        debug_info[t] = fvi.strftime('%Y-%m-%d')

                invalid_tickers = sorted(all_active_tickers - set(debug_info))
                if invalid_tickers:
                    st.error(f"❌ 找不到有效股價資料：{', '.join(invalid_tickers)}。請檢查代碼或回測期間。")
                    st.session_state.results = None
                    st.stop()

                if valid_starts:
                    common_start = max(valid_starts)
                    dates = market_data.index[market_data.index >= common_start]
                else:
                    # A CASH0-only portfolio does not require Yahoo market data.
                    dates = pd.bdate_range(start=start_date, end=end_date)
                    common_start = dates[0] if len(dates) else pd.Timestamp(start_date)

                if len(dates) == 0:
                    st.error("❌ 所選日期範圍內沒有可計算的工作日。")
                    st.session_state.results = None
                    st.stop()

                results_list, monthly_dfs, annual_returns_data = [], {}, {}
                # Color palette for consistent coloring across charts
                color_palette = ['#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3', '#FF6692', '#B6E880', '#FF97FF', '#FECB52']
                portfolio_idx = 0
                figs = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.7, 0.3], subplot_titles=("資產成長趨勢", "年度報酬率 (%)"))

                for p in st.session_state.portfolios:
                    cash_account = float(initial_capital)
                    holdings = {a['ticker']: {'shares': 0.0, 'cash_asset_currency': 0.0} for a in p['assets']}
                    alloc_map = {a['ticker']: a['weight']/100.0 for a in p['assets']}
                    total_invested = float(initial_capital)
                    history, xirr_flows = [], []
                    previous_value, unit_nav = None, 100.0
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
                        todays_contribution = 0
                        
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
                                todays_contribution = monthly_investment
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
                        if previous_value is not None:
                            unit_nav = update_unit_nav(previous_value, pv, todays_contribution - todays_wd, unit_nav)
                        history.append({'Date': d, 'Total Value': pv, 'Invested Capital': total_invested, 'Withdrawal': todays_wd, 'Unit NAV': unit_nav})
                        previous_value = pv
                    
                    df_res = pd.DataFrame(history).set_index('Date')
                    if not df_res.empty:
                        final_v = df_res['Total Value'].iloc[-1]
                        if final_v > 0: xirr_flows.append((dates[-1], final_v))
                        yr_diff = (df_res.index[-1] - df_res.index[0]).days / 365.25
                        dur_str = f"{yr_diff:.1f} 年 ({df_res.index[0].strftime('%Y-%m')} ~ {df_res.index[-1].strftime('%Y-%m')})"
                        
                        # MDD with detailed timing
                        roll_max = df_res['Unit NAV'].cummax()
                        dd = (df_res['Unit NAV'] - roll_max) / roll_max
                        mdd = dd.min()
                        if mdd < 0:
                            mdd_date = dd.idxmin()
                            # Find peak date before MDD
                            peak_date = roll_max[:mdd_date].idxmax()
                            # Find recovery date (if any)
                            post_mdd = df_res.loc[mdd_date:, 'Unit NAV']
                            recovery_mask = post_mdd >= roll_max[mdd_date]
                            if recovery_mask.any():
                                recovery_date = post_mdd[recovery_mask].index[0]
                                recovery_days = (recovery_date - mdd_date).days
                                mdd_str = f"{mdd*100:.2f}% (📉{peak_date.strftime('%Y-%m')} → 📍{mdd_date.strftime('%Y-%m')} → 📈{recovery_date.strftime('%Y-%m')}, 回復{recovery_days}天)"
                            else:
                                mdd_str = f"{mdd*100:.2f}% (📉{peak_date.strftime('%Y-%m')} → 📍{mdd_date.strftime('%Y-%m')}, 尚未回復)"
                        else:
                            mdd_str = "0.00%"

                        xirr_value = xirr(xirr_flows)
                        xirr_display = f"{xirr_value*100:.2f}%" if xirr_value is not None else "無法計算"
                        results_list.append({"組合名稱": p['name'], "回測時間": dur_str, "總投入本金": total_invested, "資產終值": final_v, "總提領金額": cum_wd, "總損益": (final_v + cum_wd) - total_invested, "XIRR": xirr_display, "MDD": mdd_str})
                        
                        monthly_dfs[p['name']] = df_res.resample('ME').agg({'Total Value':'last', 'Invested Capital':'last', 'Withdrawal':'sum'})
                        
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
                            end_val = df_y['Unit NAV'].iloc[-1]
                            if i == 0:
                                start_val = df_y['Unit NAV'].iloc[0]
                            else:
                                df_prev = df_res[df_res.index.year == years[i-1]]
                                start_val = df_prev['Unit NAV'].iloc[-1] if not df_prev.empty else df_y['Unit NAV'].iloc[0]
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
| **MDD** | 最大回撤 = 排除投入與提領後，從高點跌到最慘時虧了多少%（抗壓測試）|
| **年度報酬率** | 使用單位淨值計算，排除投入與提領對績效的影響 |

---

### ⚠️ 提領模式下的報酬率說明

年度報酬率與 MDD 使用「單位淨值」計算。每次投入或提領時，系統會先排除這筆外部現金流的影響，再計算投資本身的漲跌，因此不會把新增本金誤認成獲利，也不會把退休提領誤認成虧損。

如果想查看整段期間、包含每筆投入與提領時間的個人化報酬率，請參考 **XIRR** 指標。

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
        st.markdown("### 🏆 績效重點")
        for summary_row in res['summary']:
            st.markdown(f"#### {summary_row['組合名稱']}")
            mdd_value = summary_row['MDD'].split(' ', 1)[0]
            metric_col1, metric_col2 = st.columns(2)
            metric_col1.metric("總投入本金", f"{summary_row['總投入本金']:,.0f} 元")
            metric_col2.metric("最後資產", f"{summary_row['資產終值']:,.0f} 元")
            metric_col3, metric_col4 = st.columns(2)
            metric_col3.metric("總損益", f"{summary_row['總損益']:,.0f} 元")
            metric_col4.metric("最大跌幅 MDD", mdd_value)
            st.caption(f"年化報酬率 XIRR：{summary_row['XIRR']}｜回測時間：{summary_row['回測時間']}｜最大跌幅期間：{summary_row['MDD']}")

        with st.expander("查看完整績效表", expanded=False):
            st.dataframe(pd.DataFrame(res['summary']).style.format({"總投入本金":"{:,.0f}", "資產終值":"{:,.0f}", "總提領金額":"{:,.0f}", "總損益":"{:,.0f}"}), use_container_width=True)
        st.markdown("### 📅 歷年報酬率明細")
        st.caption("使用排除投入與提領影響的單位淨值計算")
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
        if sel:
            detail_df = res['monthly_data'][sel].rename(columns={
                'Total Value': '帳戶總值',
                'Invested Capital': '累計投入本金',
                'Withdrawal': '當月提領',
            })
            st.dataframe(detail_df.style.format("{:,.0f}"), use_container_width=True)

st.markdown("---")
st.caption("作者：[豬力安](https://richedu168.blogspot.com/)｜聯絡信箱：ju888.lee@gmail.com")
