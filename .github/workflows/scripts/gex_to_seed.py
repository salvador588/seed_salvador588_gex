"""Berechnet GEX-Levels (yfinance) und schreibt latest.txt."""
import os
import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

TICKERS = [t.strip() for t in os.environ.get("GEX_TICKERS", "SPY,QQQ").split(",") if t.strip()]
MAX_DAYS = int(os.environ.get("GEX_MAX_DAYS", "45"))
BAND = float(os.environ.get("GEX_BAND", "0.04"))
RATE = 0.045
OUT_FILE = "latest.txt"


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
    best = None
    for i in range(len(grid) - 1):
        if prof[i] == 0 or prof[i] * prof[i + 1] < 0:
            x = grid[i] - prof[i] * (grid[i + 1] - grid[i]) / (prof[i + 1] - prof[i]) if prof[i] != 0 else grid[i]
            if best is None or abs(x - spot) < abs(best - spot):
                best = x
    flip = float(best) if best is not None else 0.0

    per_strike = df.groupby("strike")["gex"].sum() / 1e6
    per_strike = per_strike[(per_strike.index >= spot * (1 - BAND)) & (per_strike.index <= spot * (1 + BAND))]
    per_strike = per_strike.sort_index()

    return {
        "spot": spot,
        "strikes": ",".join(f"{k:g}" for k in per_strike.index),
        "gex": ",".join(f"{v:.1f}" for v in per_strike.values),
        "call_wall": call_wall,
        "put_wall": put_wall,
        "flip": flip,
        "net": net,
    }


def main():
    today = dt.datetime.now(ZoneInfo("America/New_York")).date()
    blocks = [f"GEX-Werte berechnet am {today.isoformat()} (US-Börsenschluss)\n"]
    ok = 0
    for t in TICKERS:
        try:
            r = compute(t, today)
        except Exception as e:
            print(f"[{t}] Fehler: {e}")
            blocks.append(f"=== {t}: FEHLER ({e}) ===\n")
            continue
        flip = f"{r['flip']:.2f}" if r["flip"] > 0 else "0 (nicht gefunden, leer lassen)"
        blocks.append(
            f"=== {t}  (Kurs {r['spot']:.2f}) ===\n"
            f"Strikes (kommagetrennt):\n{r['strikes']}\n\n"
            f"GEX je Strike (Mio $ pro 1% Move):\n{r['gex']}\n\n"
            f"Call Wall:  {r['call_wall']:g}\n"
            f"Put Wall:   {r['put_wall']:g}\n"
            f"Gamma Flip: {flip}\n"
            f"Net GEX:    {r['net']:.2f} Mrd $\n"
        )
        print(f"[{t}] ok")
        ok += 1
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks))
    if ok == 0:
        raise SystemExit("Kein Ticker erfolgreich berechnet")


if __name__ == "__main__":
    main()
