"""Berechnet GEX-Levels (yfinance) inkl. 0DTE und schreibt latest.txt."""
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
T_0DTE = 0.5 / 365.0
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
            d["exp"] = exp_date
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


def find_flip(df, spot):
    grid = np.linspace(spot * 0.9, spot * 1.1, 201)
    prof = gex_profile(df, grid)
    best = None
    for i in range(len(grid) - 1):
        if prof[i] == 0 or prof[i] * prof[i + 1] < 0:
            x = grid[i] - prof[i] * (grid[i + 1] - grid[i]) / (prof[i + 1] - prof[i]) if prof[i] != 0 else grid[i]
            if best is None or abs(x - spot) < abs(best - spot):
                best = x
    return float(best) if best is not None else 0.0


def walls(df, spot):
    gamma = bs_gamma(spot, df["strike"].to_numpy(), df["T"].to_numpy(), df["impliedVolatility"].to_numpy())
    df = df.assign(gex=gamma * df["openInterest"] * 100 * spot ** 2 * 0.01 * df["sign"])
    calls = df[(df["sign"] > 0) & (df["strike"] >= spot)].groupby("strike")["gex"].sum()
    puts = df[(df["sign"] < 0) & (df["strike"] <= spot)].groupby("strike")["gex"].sum()
    call_wall = float(calls.idxmax()) if not calls.empty else 0.0
    put_wall = float(puts.idxmin()) if not puts.empty else 0.0
    return df, call_wall, put_wall, float(df["gex"].sum()) / 1e9


def compute(ticker, today, next_session):
    spot = float(yf.Ticker(ticker).history(period="5d")["Close"].dropna().iloc[-1])
    df = load_chain(ticker, spot, today)

    df, call_wall, put_wall, net = walls(df, spot)
    flip = find_flip(df, spot)

    df0 = df[df["exp"] == next_session]
    if df0.empty:
        df0 = df[df["exp"] == df["exp"].min()]
    exp0 = df0["exp"].min()
    df0 = df0.drop(columns=["gex"]).assign(T=T_0DTE)
    df0, call_wall0, put_wall0, _ = walls(df0, spot)
    flip0 = find_flip(df0, spot)

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
        "call_wall0": call_wall0,
        "put_wall0": put_wall0,
        "flip0": flip0,
        "exp0": exp0,
    }


def fmt_flip(v):
    return f"{v:.2f}" if v > 0 else "0"


def main():
    today = dt.datetime.now(ZoneInfo("America/New_York")).date()
    next_session = pd.Timestamp(np.busday_offset(today, 1, roll="forward")).date()
    blocks = [f"GEX-Werte berechnet am {today.isoformat()} (US-Börsenschluss), gültig für {next_session.isoformat()}\n"]
    ok = 0
    for t in TICKERS:
        try:
            r = compute(t, today, next_session)
        except Exception as e:
            print(f"[{t}] Fehler: {e}")
            blocks.append(f"=== {t}: FEHLER ({e}) ===\n")
            continue
        blocks.append(
            f"=== {t}  (Kurs {r['spot']:.2f}) ===\n"
            f"Strikes (kommagetrennt):\n{r['strikes']}\n\n"
            f"GEX je Strike (Mio $ pro 1% Move):\n{r['gex']}\n\n"
            f"Call Wall:       {r['call_wall']:g}\n"
            f"Put Wall:        {r['put_wall']:g}\n"
            f"Gamma Flip:      {fmt_flip(r['flip'])}\n"
            f"Call Wall 0DTE:  {r['call_wall0']:g}\n"
            f"Put Wall 0DTE:   {r['put_wall0']:g}\n"
            f"Gamma Flip 0DTE: {fmt_flip(r['flip0'])}\n"
            f"(0DTE = Verfall am {r['exp0']})\n"
            f"Net GEX:         {r['net']:.2f} Mrd $\n"
        )
        print(f"[{t}] ok")
        ok += 1
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks))
    if ok == 0:
        raise SystemExit("Kein Ticker erfolgreich berechnet")


if __name__ == "__main__":
    main()
