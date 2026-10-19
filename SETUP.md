# Padel Sniper – Setup Railway

## 1. Instalare locală (opțional, pentru test)

```bash
pip install -r requirements.txt
playwright install chromium --with-deps
cp .env.example .env
# editează .env cu credențialele tale Gmail
python app.py
# deschide http://localhost:5000
```

## 2. Deploy pe Railway.app

1. Creează cont gratuit pe https://railway.app
2. New Project → Deploy from GitHub repo (sau "Empty Project" + Railway CLI)
3. Variables → adaugă:
   - `GMAIL_USER` = adresa ta Gmail
   - `GMAIL_PASS` = App Password Gmail (nu parola normală!)
   - `SECRET_KEY` = un string random lung (ex: openssl rand -hex 32)
   - `APP_PIN` = PIN-ul cerut la deschiderea aplicației (obligatoriu; aplicația nu pornește fără el, la fel ca fără `SECRET_KEY`)
4. Railway detectează automat `railway.json` și rulează build-ul
5. Settings → Generate Domain → copiezi URL-ul pe telefon

## 3. Gmail App Password

1. Contul Google → Securitate → Verificare în 2 pași (activat)
2. Caută "Parole pentru aplicații"
3. Selectează "Altă aplicație" → "Padel Sniper" → Generează
4. Copiezi cele 16 caractere → `GMAIL_PASS`

## 4. Utilizare

- Deschide URL-ul Railway pe telefon
- Completează email + parolă cont Calendis
- Apasă "Verifică cont" să confirmi că funcționează
- Selectează data și ora dorită
- Apasă "Programează Sniping"
- Botul pornește automat cu 2 minute înainte de ora deschiderii
- Primești email cu rezultatul

## Logica timing

Slot pe 29 iulie la 15:00:
- Se deschide pe 15 iulie la 15:00:00
- Botul pornește pe 15 iulie la 14:58 (login + navigate)
- La 15:00:00 exact → click instant pe slot
