import os
import time
import threading
import requests
import yfinance as yf
import telebot
from flask import Flask
from datetime import datetime

# ==========================================
# 1. 환경변수 (Render Environment Variables 또는 직접 입력)
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "여기에_텔레그램_봇_토큰_입력")
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "여기에_알파카_API_KEY_입력")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "여기에_알파카_SECRET_KEY_입력")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

CHAT_FILE = "registered_chats.txt"
alerted_tickers = {}

# ==========================================
# 2. 채팅방 ID 저장 및 불러오기 (/start 명령어 연동)
# ==========================================
def load_chats():
    if not os.path.exists(CHAT_FILE):
        return set()
    with open(CHAT_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())

def save_chat(chat_id):
    chats = load_chats()
    chat_str = str(chat_id)
    if chat_str not in chats:
        with open(CHAT_FILE, "a") as f:
            f.write(f"{chat_str}\n")

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    save_chat(chat_id)
    bot.reply_to(
        message,
        "🎯 [대장주 스나이퍼 봇 가동 완료]\n"
        "실시간 나스닥 소형주 수급 포착 및 설거지 방지 필터링이 시작되었습니다.\n"
        "93점 이상 초강세 종목 포착 시 즉시 알림을 발송합니다!"
    )

@bot.message_handler(commands=['status'])
def send_status(message):
    bot.reply_to(message, "✅ 스나이퍼 봇이 24시간 정상 감시 중입니다.")

def broadcast_message(text):
    chats = load_chats()
    for chat_id in chats:
        try:
            bot.send_message(chat_id, text)
        except Exception as e:
            print(f"메시지 발송 오류 ({chat_id}): {e}")

# ==========================================
# 3. 기술적 분석 & 설거지 방지 스나이퍼 점수 계산
# ==========================================
def analyze_ticker(ticker):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="5d", interval="5m")
        if df.empty or len(df) < 20:
            return None

        current_price = float(df['Close'].iloc[-1])
        open_price = float(df['Open'].iloc[0])
        high_price = float(df['High'].max())
        low_price = float(df['Low'].min())

        # 소형주 가격 필터 ($0.5 ~ $20)
        if not (0.5 <= current_price <= 20.0):
            return None

        # 당일 변동률 및 고점 대비 낙폭(설거지 방지) 체크
        change_pct = ((current_price - open_price) / open_price) * 100
        drop_from_high = ((high_price - current_price) / high_price) * 100

        # 고점 대비 15% 이상 밀린 종목은 설거지 패턴으로 간주하여 제외
        if drop_from_high > 15.0:
            return None

        # 거래량 폭발 계산 (최근 거래량 vs 평균 거래량)
        avg_vol = float(df['Volume'].iloc[:-3].mean()) if len(df) > 3 else 1.0
        recent_vol = float(df['Volume'].iloc[-1])
        vol_ratio = (recent_vol / avg_vol) if avg_vol > 0 else 1.0

        # VWAP (거래량 가중 평균 가격) 계산 및 돌파 여부
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
        vwap = float((typical_price * df['Volume']).sum() / df['Volume'].sum())
        above_vwap = current_price > vwap

        # 스나이퍼 점수 산출 (100점 만점 기준)
        score = 70
        if vol_ratio >= 5.0:
            score += 12
        elif vol_ratio >= 3.0:
            score += 7

        if above_vwap:
            score += 8

        if 10.0 <= change_pct <= 60.0:
            score += 7

        if drop_from_high <= 5.0:
            score += 5

        return {
            "ticker": ticker,
            "price": round(current_price, 3),
            "change_pct": round(change_pct, 2),
            "vol_ratio": round(vol_ratio, 1),
            "vwap": round(vwap, 3),
            "score": min(score, 99)
        }
    except Exception as e:
        return None

# ==========================================
# 4. 실시간 시장 스캐너 (Alpaca & 급등주 감시)
# ==========================================
def get_active_candidates():
    # Alpaca Most Actives / Movers API 연동 (키가 있을 경우 작동)
    if ALPACA_API_KEY and "여기에" not in ALPACA_API_KEY:
        try:
            url = "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives?top=30"
            headers = {
                "APCA-API-KEY-ID": ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
            }
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                return [item["symbol"] for item in data.get("most_actives", [])]
        except Exception as e:
            print(f"Alpaca API 스캔 오류: {e}")

    # 기본 감시 워치리스트 (API 미설정 시 백업용)
    return ["SQNS", "ONFO", "BRNX", "EFOI", "ATXG", "WSHP", "MULN", "FFIE", "GME", "AMC"]

def sniper_scanner_loop():
    while True:
        try:
            candidates = get_active_candidates()
            now = time.time()

            for ticker in candidates:
                # 동일 종목 중복 알림 쿨타임 (1시간)
                if ticker in alerted_tickers and (now - alerted_tickers[ticker]) < 3600:
                    continue

                result = analyze_ticker(ticker)
                if result and result["score"] >= 93:
                    alerted_tickers[ticker] = now
                    msg = (
                        f"🚨 [대장주 스나이퍼 포착 - {result['score']}점]\n\n"
                        f"▪️ 종목코드: #{result['ticker']}\n"
                        f"▪️ 현재가: ${result['price']} ({result['change_pct']:+}%)\n"
                        f"▪️ 수급강도: 평균 대비 거래량 {result['vol_ratio']}배 폭발\n"
                        f"▪️ 지지선(VWAP): ${result['vwap']} 상단 지지 완료\n"
                        f"▪️ 상태: 설거지 위험 낮음 / 초강세 돌파 구간\n"
                        f"⏰ 포착시간: {datetime.now().strftime('%H:%M:%S')}"
                    )
                    broadcast_message(msg)
                time.sleep(1)
        except Exception as e:
            print(f"스캐너 루프 오류: {e}")
        time.sleep(30)

# ==========================================
# 5. Flask 웹서버 및 24시간 멀티스레드 구동
# ==========================================
@app.route('/')
def index():
    return "Ung_bot Sniper Service is Running 24/7!"

def run_bot():
    while True:
        try:
            bot.polling(non_stop=True, interval=2, timeout=20)
        except Exception as e:
            print(f"텔레그램 폴링 재시작: {e}")
            time.sleep(5)

if __name__ == "__main__":
    # 스캐너 스레드 시작
    scanner_thread = threading.Thread(target=sniper_scanner_loop, daemon=True)
    scanner_thread.start()

    # 텔레그램 봇 폴링 스레드 시작
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    # Render 포트 바인딩 및 웹서버 실행
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
