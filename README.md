# GEX-Indikator für TradingView (Pine Seeds)

Ablauf: GitHub Action berechnet täglich das GEX -> schreibt CSVs ins Repo -> TradingView liest sie per `request.seed()` -> Indikator zeigt Call Wall, Put Wall, Gamma Flip und Net GEX.

## Einmalige Einrichtung

1. **GitHub-Account** anlegen (falls noch keiner da ist): https://github.com
2. **Neues Repo erstellen**
   - Name: `seed_DEINUSERNAME_gex` (muss mit `seed_` beginnen, Username kleingeschrieben)
   - Sichtbarkeit: **Public**
3. **Dateien hochladen**: Alle Dateien aus diesem Ordner ins Repo (Add file -> Upload files). Wichtig ist die Struktur:
   ```
   .github/workflows/update-gex.yml
   scripts/gex_to_seed.py
   requirements.txt
   ```
   Der Ordner `.github` ist versteckt: am einfachsten das ganze Verzeichnis per Drag & Drop hochladen oder `git push` nutzen.
4. **Action-Rechte prüfen**: Repo -> Settings -> Actions -> General -> Workflow permissions -> **Read and write permissions** -> Save.
5. **Ersten Lauf starten**: Repo -> Actions -> "Update GEX data" -> Run workflow. Danach liegen im Repo die Ordner `data/` und `symbol_info/`.
6. **Repo bei TradingView als Pine-Seeds-Quelle anmelden**: Anleitung und aktuelles Verfahren stehen in der offiziellen Doku: https://github.com/tradingview-pine-seeds/docs
7. **Indikator einfügen**: TradingView -> Chart -> unten "Pine-Editor" -> Inhalt von `gex_seed.pine` einfügen -> in der Zeile `repo = input.string("seed_DEINUSER_gex", ...)` deinen Repo-Namen eintragen -> "Zum Chart hinzufügen".

## Täglicher Betrieb

Läuft automatisch Mo-Fr um 22:30 UTC. Nichts zu tun.

## Anpassen

- Ticker ändern: in `.github/workflows/update-gex.yml` bei `GEX_TICKERS`. Im Pine-Script die `options` beim Datenticker ergänzen.
- Auf SPX/ES/NQ chartest du? In den Indikator-Einstellungen "Skalierung" setzen (SPX ca. 10 bei SPY-Daten).

## Hinweise

- Datenquelle ist yfinance (Yahoo). Open Interest wird dort einmal täglich aktualisiert, die Werte sind eine Näherung und nicht identisch mit SpotGamma o. ä.
- Annahme der Berechnung: Calls = Dealer long Gamma, Puts = Dealer short Gamma (Standardmodell).
- Kein Anlagerat.
