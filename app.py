import streamlit as st
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
from collections import deque

# ---------------------------------------------------------
# 1. 설정값 (여기서 코인 종류나 레인지바 크기를 조절하세요)
# ---------------------------------------------------------
SYMBOL = 'SOL/USDT:USDT'
RANGE_SIZE_TICKS = 15    # 레인지바 크기 (틱 수)
TICK_VALUE = 0.01        # 최소 호가 단위
UPDATE_INTERVAL = 1.0    # 화면 갱신 주기 (초)

# ---------------------------------------------------------
# 2. Streamlit 페이지 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="MEXC Live CVD Chart",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title(f"🚀 {SYMBOL} Real-Time Range Bar & CVD")

# 사이드바 컨트롤
with st.sidebar:
    st.header("설정 패널")
    range_input = st.number_input("Range Size (Ticks)", min_value=1, value=RANGE_SIZE_TICKS)
    if st.button("차트 초기화"):
        st.session_state.bars = deque(maxlen=100)  # <-- 스페이스 4칸 들여쓰기
        st.session_state.current_bar = None
        st.rerun()

# ---------------------------------------------------------
# 3. 데이터 상태 관리 (Session State)
# ---------------------------------------------------------
# Streamlit은 새로고침될 때 변수가 초기화되므로 session_state에 저장해야 함
if 'bars' not in st.session_state:
    st.session_state.bars = deque(maxlen=200)
if 'current_bar' not in st.session_state:
    st.session_state.current_bar = None
if 'last_trade_id' not in st.session_state:
    st.session_state.last_trade_id = None

# ---------------------------------------------------------
# 4. 레인지바 로직 함수
# ---------------------------------------------------------
def process_tick(trade, range_height_val):
    price = float(trade['price'])
    amount = float(trade['amount'])
    side = trade['side']
    timestamp = trade['timestamp']
    
    # 1) 첫 데이터 초기화
    if st.session_state.current_bar is None:
        init_new_bar(price, timestamp)
        
    bar = st.session_state.current_bar
    
    # 2) OHLC 업데이트
    bar['high'] = max(bar['high'], price)
    bar['low'] = min(bar['low'], price)
    bar['close'] = price
    bar['volume'] += amount
    
    # 3) CVD 델타 계산
    delta = amount if side == 'buy' else -amount
    bar['cvd_delta'] += delta
    
    # 4) 바 완성 체크
    if (bar['high'] - bar['low']) >= range_height_val:
        # 누적 CVD 확정 (이전 누적값 + 현재 델타)
        bar['cvd_cum'] += bar['cvd_delta']
        
        # 완성된 바 저장
        st.session_state.bars.append(bar.copy())
        
        # 새 바 시작
        init_new_bar(price, timestamp)

def init_new_bar(price, timestamp):
    # 이전 바의 누적 CVD를 가져옴 (없으면 0)
    if len(st.session_state.bars) > 0:
        prev_cum = st.session_state.bars[-1]['cvd_cum']
    else:
        prev_cum = 0
        
    st.session_state.current_bar = {
        'time': datetime.fromtimestamp(timestamp/1000),
        'open': price, 'high': price, 'low': price, 'close': price,
        'volume': 0,
        'cvd_delta': 0,
        'cvd_cum': prev_cum # 시작값 = 이전 종료값
    }

# ---------------------------------------------------------
# 5. 비동기 데이터 수집 함수
# ---------------------------------------------------------
async def fetch_data():
    exchange = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    
    try:
        # 최근 체결 내역 가져오기
        trades = await exchange.fetch_trades(SYMBOL, limit=50)
        
        # 중복 제거 (last_id 기준)
        if st.session_state.last_trade_id:
            new_trades = [t for t in trades if t['id'] > st.session_state.last_trade_id]
        else:
            new_trades = trades
            
        if new_trades:
            st.session_state.last_trade_id = new_trades[-1]['id']
            range_h = range_input * TICK_VALUE
            
            for trade in new_trades:
                process_tick(trade, range_h)
                
    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        await exchange.close()

# ---------------------------------------------------------
# 6. 메인 실행 루프
# ---------------------------------------------------------
# 실시간 차트를 위한 빈 공간 확보
chart_placeholder = st.empty()
status_placeholder = st.empty()

# 비동기 루프 실행
async def main_loop():
    while True:
        # 1) 데이터 가져오기
        await fetch_data()
        
        # 2) 데이터가 있으면 차트 그리기
        if len(st.session_state.bars) > 0:
            df = pd.DataFrame(st.session_state.bars)
            
            # Plotly 차트 구성
            fig = go.Figure()
            
            # (1) 캔들스틱
            fig.add_trace(go.Candlestick(
                x=df['time'], open=df['open'], high=df['high'],
                low=df['low'], close=df['close'], name='Price',
                increasing_line_color='#26A69A', decreasing_line_color='#EF5350'
            ))
            
            # (2) CVD (보조축)
            fig.add_trace(go.Scatter(
                x=df['time'], y=df['cvd_cum'], name='CVD',
                yaxis='y2', mode='lines+markers',
                marker=dict(size=4), line=dict(color='#FFD700', width=2)
            ))
            
            # 레이아웃
            fig.update_layout(
                height=600, template='plotly_dark',
                xaxis_rangeslider_visible=False,
                yaxis=dict(title='Price', domain=[0.3, 1.0]),
                yaxis2=dict(title='CVD', domain=[0.0, 0.25], overlaying=None),
                margin=dict(l=10, r=10, t=30, b=10),
                legend=dict(x=0, y=1, orientation='h')
            )
            
            # key를 추가하여 중복 ID 에러 방지
            chart_placeholder.plotly_chart(fig, use_container_width=True, key="live_chart")
            
            # 현재 상태 표시
            last_price = df.iloc[-1]['close']
            last_cvd = df.iloc[-1]['cvd_cum']
            status_placeholder.markdown(f"**현재가:** `{last_price}` | **누적 CVD:** `{last_cvd:.2f}` | **바 개수:** `{len(df)}`")
            
        else:
            status_placeholder.info("데이터 수신 중... 잠시만 기다려주세요.")

        # 대기
        await asyncio.sleep(UPDATE_INTERVAL)

# Streamlit에서 비동기 루프 실행
if __name__ == "__main__":
    asyncio.run(main_loop())
