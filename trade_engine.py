import sys, asyncio, random, json, logging
import tzlocal
from datetime import timezone
tzlocal.get_localzone = lambda: timezone.utc

import types
webview_mod = types.ModuleType('webview')
webview_mod.create_window = lambda *a, **k: None
webview_mod.start = lambda *a, **k: None
webview_mod.token = lambda *a, **k: None
sys.modules['webview'] = webview_mod
webview_window = types.ModuleType('webview.window')
class _FakeWindow:
    def __init__(self, *a, **k): pass
    def load_url(self, *a, **k): pass
    def load_html(self, *a, **k): pass
    def evaluate_js(self, *a, **k): return None
    @property
    def events(self): return types.SimpleNamespace(loaded=None)
webview_window.Window = _FakeWindow
sys.modules['webview.window'] = webview_window
sys.modules['webview.http'] = types.ModuleType('webview.http')
webview_util = types.ModuleType('webview.util')
webview_util.base_uri = lambda *a, **k: None
sys.modules['webview.util'] = webview_util

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Tuple, List
from curl_cffi.requests import AsyncSession

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PocketOptionCurl:
    def __init__(self, ssid, is_demo=True):
        self.ssid = ssid
        self.is_demo = is_demo
        self.session = None
        self.ws = None
        self.connected = False
        self.current_balance = None
        self.pairs = []
        self.ws_url = "wss://api-in.pocketoption.com/socket.io/?EIO=4&transport=websocket"

    async def connect(self):
        logger.info("Connecting with curl_cffi + DoH...")
        try:
            self.session = AsyncSession(
                impersonate="chrome120",
                proxies={"https": "socks5h://127.0.0.1:10808", "http": "socks5h://127.0.0.1:10808"}
            )
            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                "Origin": "https://m.p.finance",
                "Referer": "https://m.p.finance/",
                "Accept-Language": "en-US,en;q=0.9",
            }
            logger.info("Connecting WebSocket...")
            self.ws = await self.session.ws_connect(self.ws_url, headers=headers, timeout=30)
            logger.info("WebSocket connected.")
            initial = await asyncio.wait_for(self.ws.recv(), timeout=15)
            logger.info("Initial: " + str(initial)[:80])
            logger.info("Sending auth...")
            await self.ws.send(self.ssid)
            response = await asyncio.wait_for(self.ws.recv(), timeout=15)
            r = str(response)
            logger.info("Response: " + r[:200])
            if '"auth"' in r or '"success"' in r or '42["auth"' in r:
                logger.info("Auth OK!")
                self.connected = True
                return True
            logger.error("Auth failed.")
            return False
        except Exception as e:
            logger.error("Connection error: " + str(e))
            return False

    async def GetBalance(self):
        if not self.connected: return None
        try:
            await self.ws.send('42["getBalance"]')
            response = await asyncio.wait_for(self.ws.recv(), timeout=10)
            data = json.loads(str(response)[2:])
            self.current_balance = float(data.get("balance", 0))
            logger.info("Balance: " + str(self.current_balance))
            return self.current_balance
        except Exception as e:
            logger.error("Balance error: " + str(e))
            return None

    async def GetPairs(self):
        if not self.connected: return []
        try:
            await self.ws.send('42["getAssets"]')
            response = await asyncio.wait_for(self.ws.recv(), timeout=10)
            data = json.loads(str(response)[2:])
            self.pairs = data.get("assets", [])
            logger.info(str(len(self.pairs)) + " assets received.")
            return self.pairs
        except Exception:
            return []

    async def GetHistory(self, asset):
        if not self.connected: return None
        try:
            await self.ws.send('42["getHistory",{"asset":"' + asset + '","count":100}]')
            response = await asyncio.wait_for(self.ws.recv(), timeout=10)
            data = json.loads(str(response)[2:])
            return data.get("history", [])
        except Exception:
            return None

    async def close(self):
        if self.ws:
            try: await self.ws.close()
            except: pass
        if self.session:
            try: await self.session.close()
            except: pass


class Indicators:
    @staticmethod
    def rsi(prices, period=14):
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def ema(prices, period):
        return prices.ewm(span=period, adjust=False).mean()

    @staticmethod
    def macd(prices, fast=12, slow=26, signal=9):
        ef = prices.ewm(span=fast, adjust=False).mean()
        es = prices.ewm(span=slow, adjust=False).mean()
        m = ef - es
        s = m.ewm(span=signal, adjust=False).mean()
        return m, s, m - s

    @staticmethod
    def bb(prices, period=20, sd=2.0):
        sma = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        return sma + (std * sd), sma, sma - (std * sd)


def analyze(df):
    if len(df) < 50:
        return {"signal": "NO_DATA", "score": 0}
    df['rsi'] = Indicators.rsi(df['close'], 14)
    df['ef'] = Indicators.ema(df['close'], 9)
    df['es'] = Indicators.ema(df['close'], 21)
    m, s, h = Indicators.macd(df['close'])
    df['macd'] = m
    df['msig'] = s
    df['bbu'], _, df['bbl'] = Indicators.bb(df['close'])
    last = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    reasons = []
    if last['rsi'] < 30: score += 3; reasons.append("RSI oversold")
    elif last['rsi'] > 70: score += 3; reasons.append("RSI overbought")
    if last['ef'] > last['es'] and prev['ef'] <= prev['es']:
        score += 2; reasons.append("EMA bull cross")
    elif last['ef'] < last['es'] and prev['ef'] >= prev['es']:
        score += 2; reasons.append("EMA bear cross")
    if last['macd'] > last['msig'] and prev['macd'] <= prev['msig']:
        score += 2; reasons.append("MACD bull")
    elif last['macd'] < last['msig'] and prev['macd'] >= prev['msig']:
        score += 2; reasons.append("MACD bear")
    if last['close'] <= last['bbl']: score += 2; reasons.append("BB lower")
    elif last['close'] >= last['bbu']: score += 2; reasons.append("BB upper")
    sig = "NO_TRADE"
    if score >= 5:
        if last['rsi'] < 40 and last['ef'] > last['es']: sig = "CALL"
        elif last['rsi'] > 60 and last['ef'] < last['es']: sig = "PUT"
        elif last['rsi'] < 30: sig = "CALL"
        elif last['rsi'] > 70: sig = "PUT"
    return {"signal": sig, "score": score, "reasons": reasons, "rsi": round(last['rsi'], 2)}


ASSETS = ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "AUDCAD_otc", "EURGBP_otc", "NZDUSD_otc", "USDCAD_otc", "AUDUSD_otc"]


async def main():
    if len(sys.argv) < 4:
        print("Usage: trade_engine.py <ssid> <uid> <account>")
        return
    raw_token = sys.argv[1]
    uid = sys.argv[2]
    account = sys.argv[3]
    is_demo = 1 if account == 'demo' else 0
    full_ssid = '42["auth",{"session":"' + raw_token + '","isDemo":' + str(is_demo) + ',"uid":' + uid + ',"platform":2,"isFastHistory":true,"isOptimized":true}]'
    print("=" * 60)
    print("[Trade Engine] UID: " + uid + " | Account: " + account)
    print("[Trade Engine] SSID length: " + str(len(full_ssid)))
    print("=" * 60)

    api = PocketOptionCurl(full_ssid, is_demo)
    if not await api.connect():
        print("[Trade Engine] Connection FAILED. Check token/VPN.")
        return
    balance = await api.GetBalance()
    if balance is None:
        print("[Trade Engine] Balance is None. Cannot continue.")
        return
    await api.GetPairs()
    print("[Trade Engine] Starting analysis loop...")
    while True:
        try:
            data = {}
            for asset in ASSETS:
                hist = await api.GetHistory(asset)
                if hist and len(hist) >= 50:
                    df = pd.DataFrame(hist)
                    if 'close' not in df.columns and len(df.columns) >= 5:
                        df.columns = ['time', 'open', 'high', 'low', 'close'] + list(df.columns[5:])
                    data[asset] = df.tail(100).copy()
            if not data:
                await asyncio.sleep(30); continue
            results = []
            for a, df in data.items():
                results.append((a, analyze(df)))
            results.sort(key=lambda x: x[1]['score'], reverse=True)
            print("\n" + "=" * 60)
            print("Time: " + datetime.now().strftime('%H:%M:%S') + " | Balance: " + str(balance))
            for i, (a, r) in enumerate(results[:5]):
                print(str(i+1) + ". " + a + " -> " + r['signal'] + " (score " + str(r['score']) + "/10)")
            best = results[0]
            if best[1]['signal'] != "NO_TRADE":
                print(">>> BEST: " + best[1]['signal'] + " on " + best[0])
            await asyncio.sleep(60)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print("Error: " + str(e))
            await asyncio.sleep(10)
    await api.close()


if __name__ == "__main__":
    asyncio.run(main())
