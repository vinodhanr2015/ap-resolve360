# Deploy AP Resolve360 — handover note

**Goal:** a public Streamlit Community Cloud link for an IIM project submission due **13 Nov 2026, 9 PM IST**.
**Time needed:** about 15 minutes. No code changes needed.

## What this is
A small Streamlit (Python) app. It reads a sample CSV, applies simple rules, and makes one call to
Google Gemini (`gemini-2.5-flash`) through the `google-genai` package. No database, no login.

## Files
| File | Purpose |
|---|---|
| `app.py` | The app (entry point) |
| `requirements.txt` | streamlit, pandas, google-genai |
| `sample_erp_export.csv` | Demo data loaded by default |
| `sample_email_trail.txt` | Demo email history for invoice INV-1023 |
| `README.md` | Project description (keep it in the repo; it is a submission requirement) |
| `.gitignore` | Keeps `.streamlit/secrets.toml` out of Git |

## Steps
1. **Gemini key:** aistudio.google.com → Get API key → Create API key.
2. **GitHub:** create a **public** repo (suggested name `ap-resolve360`) and push all files above to `main`.
   Do **not** commit the API key.
3. **Streamlit:** share.streamlit.io → Create app → Deploy a public app from GitHub →
   repo `ap-resolve360`, branch `main`, main file `app.py`.
   Advanced settings → Python 3.11 or 3.12 → **Secrets**:
   ```
   GEMINI_API_KEY = "your-key-here"
   ```
   → Deploy.

## Test (2 minutes)
1. Open the app link. The stuck-invoice list should show 4 invoices.
2. Choose **INV-1023** → click **Build case summary**.
3. Expect: likely cause, "who to contact" (Stores), a ready reminder, and an **escalation alert** (3 reminders so far).
4. Click **I checked this – add to tracker** → the follow-up tracker and test results appear.

## If something fails
- **"Add GEMINI_API_KEY in Streamlit secrets"** → the secret name or quotes are wrong.
- **"AI step failed: … model not found"** → in `app.py`, change `MODEL = "gemini-2.5-flash"` to a model the key supports
  (for example `gemini-2.0-flash`) and redeploy.
- **"AI step failed: … quota / 429"** → wait a minute, or create the key on a different Google account.
- **Module not found** → check `requirements.txt` is in the repo root.

## Please send back
1. The live link (ends in `.streamlit.app`)
2. The GitHub repo link
3. Three screenshots: the stuck-invoice list, the case summary for INV-1023, and the ready reminder with the escalation alert
4. Optional: a 60-second screen recording of the test above (backup for the presentation)
