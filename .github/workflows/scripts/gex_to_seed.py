"""Berechnet GEX-Levels aus der Options-Chain (yfinance) und schreibt Pine-Seeds-CSVs."""
import json
import os
import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

TICKERS = [t.strip() for t in os.environ.get("GEX_TICKERS", "SPY,QQQ").split(",") if t.strip()]
MAX_DAYS = int(os.environ.get("GEX_MAX_DAYS", "45"))
RATE = 0.045
DATA_DIR = "data"
SYMBOL_INFO_DIR = "symbol_info"
SUFFIXES = ["CALLWALL", "PUTWALL", "FLIP", "NETGEX", "SPOT"]


def bs_gamma(S, K, T, sigma):
    d1 = (np.log(S / K) + (RATE + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi) / (S * sigma * np.sqrt(T))


def load_chain(ticker, spot, today):
    tk = yf.Ticker(ticker)
    rows = []
    for exp in tk.options:
        exp_date = dt.date.fromisoformat(exp)
        days = (exp_date - today).days
        if days < 0 or days > MAX_DAYS:
            continue
        T = max(days, 0.5) / 365.0
        chain = tk.option_chain(exp)
        for df, sign in ((chain.calls, 1), (chain.puts, -1)):
            d = df[["strike", "openInterest", "impliedVolatility"]].copy()
            d["T"] = T
            d["sign"] = sign
            rows.append(d)
    if not rows:
        raise RuntimeError(f"Keine Optionsdaten für {ticker}")
    df = pd.concat(rows, ignore_index=True).dropna()
    df = df[(df["openInterest"] > 0) & (df["impliedVolatility"] > 0.01)]
    df = df[(df["strike"] > spot * 0.8) & (df["strike"] < spot * 1.2)]
    return df


def gex_profile(df, spots):
    S = spots[:, None]
    K = df["strike"].to_numpy()[None, :]
    T = df["T"].to_numpy()[None, :]
    iv = df["impliedVolatility"].to_numpy()[None, :]
    oi = df["openInterest"].to_numpy()[None, :]
    sign = df["sign"].to_numpy()[None, :]
    gamma = bs_gamma(S, K, T, iv)
    return (gamma * oi * 100 * S ** 2 * 0.01 * sign).sum(axis=1)


def compute(ticker, today):
    spot = float(yf.Ticker(ticker).history(period="5d")["Close"].dropna().iloc[-1])
    df = load_chain(ticker, spot, today)

    gamma = bs_gamma(spot, df["strike"].to_numpy(), df["T"].to_numpy(), df["impliedVolatility"].to_numpy())
    df = df.assign(gex=gamma * df["openInterest"] * 100 * spot ** 2 * 0.01 * df["sign"])
    calls = df[df["sign"] > 0].groupby("strike")["gex"].sum()
    puts = df[df["sign"] < 0].groupby("strike")["gex"].sum()
    call_wall = float(calls.idxmax())
    put_wall = float(puts.idxmin())
    net = float(df["gex"].sum()) / 1e9

    grid = np.linspace(spot * 0.9, spot * 1.1, 201)
    prof = gex_profile(df, grid)
    flip = 0.0
    best = None
    for i in range(len(grid) - 1):
        if prof[i] == 0 or prof[i] * prof[i + 1] < 0:
            x = grid[i] - prof[i] * (grid[i + 1] - grid[i]) / (prof[i + 1] - prof[i]) if prof[i] != 0 else grid[i]
            if best is None or abs(x - spot) < abs(best - spot):
                best = x
    if best is not None:
        flip = float(best)

    return {"CALLWALL": call_wall, "PUTWALL": put_wall, "FLIP": flip, "NETGEX": net, "SPOT": spot}


def upsert(symbol, date, value):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"{symbol}.csv")
    key = date.strftime("%Y%m%dT")
    lines = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    lines[line.split(",")[0]] = line
    v = round(value, 3)
    lines[key] = f"{key},{v},{v},{v},{v},0"
    with open(path, "w") as f:
        f.write("\n".join(lines[k] for k in sorted(lines)) + "\n")


def write_symbol_info():
    repo = os.environ.get("GITHUB_REPOSITORY", "DEINUSER/seed_DEINUSER_gex").split("/")[1]
    symbols = [f"{t}_{s}" for t in TICKERS for s in SUFFIXES]
    n = len(symbols)
    info = {
        "symbol": symbols,
        "description": [f"{t} GEX {s}" for t in TICKERS for s in SUFFIXES],
        "currency": ["USD"] * n,
        "session-regular": ["24x7"] * n,
        "timezone": ["America/New_York"] * n,
    }
    os.makedirs(SYMBOL_INFO_DIR, exist_ok=True)
    with open(os.path.join(SYMBOL_INFO_DIR, f"{repo}.json"), "w") as f:
        json.dump(info, f, indent=2)


def main():
    today = dt.datetime.now(ZoneInfo("America/New_York")).date()
    ok = 0
    for t in TICKERS:
        try:
            res = compute(t, today)
        except Exception as e:
            print(f"[{t}] Fehler: {e}")
            continue
        valid_from = pd.Timestamp(np.busday_offset(today, 1, roll="forward")).date()
        for suffix, value in res.items():
            upsert(f"{t}_{suffix}", valid_from, value)
        print(f"[{t}] {res}")
        ok += 1
    write_symbol_info()
    if ok == 0:
        raise SystemExit("Kein Ticker erfolgreich berechnet")


if __name__ == "__main__":
    main()
