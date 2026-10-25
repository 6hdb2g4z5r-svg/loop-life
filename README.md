# Loop Life — iPhone web app

A thin installable shell (PWA) around a personal health dashboard. **This repo holds no data and no secrets**:
the dashboard page and its data are fetched at run time from the owner's own receiver, using a URL and key
entered once on the device (kept in the browser's local storage).

- `app/` — loader (`index.html`), runtime shim (`shim.js`: db / AI / sync), service worker, icons. Deployed by `pages.yml`.
- `pipeline/` — scheduled refresh (`refresh.yml`, every 20 min): reads new Health Auto Export files from the receiver,
  rebuilds the dashboard data and posts it back. Needs the Actions secrets `RECEIVER_URL`, `RECEIVER_KEY`, `TG_TOKEN`, `TG_CHAT`.
  `coach.py` sends the iPhone push notifications (rule-based), `notify.py` holds the push plumbing.
  `gband_nightly.py` reads the G Band cloud (read-only, the G Band app's own session stored on the receiver as
  `gband_auth`, never in this repo) and keeps nightly HRV (RMSSD) / respiratory rate in `gband_nightly`; Recovery uses
  G Band HRV against its own baseline when present, Watch HRV otherwise. Heart rate (per minute, Watch preferred where worn, i.e. workouts), sleep
  (the band's own stages; its score leaves out efficiency because the band misses awakenings), resting heart rate,
  respiratory rate, calories and distance also come from the band (`gband_series`). Daily steps also come from the G Band
  (its own count, updated whenever the G Band app syncs), Watch steps otherwise. If the session expires the run logs it and
  falls back to the Watch: capture a new token from the G Band app and store it as `gband_auth`.

AI coach: Claude by default; DeepSeek can be selected in the app settings (own API key, same request format).

Operating notes:
- Bump `SHELL` in `app/sw.js` on every app change, otherwise phones keep the old shell.
- The push key pair (`vapid` / `vapid_pub` on the receiver) must never be regenerated: every phone subscription is bound
  to it. `ensure_vapid()` only creates it when the receiver explicitly reports it missing; the app re-subscribes itself
  if the key it holds differs from the receiver's.
- Inbox files are consumed only after the receiver confirms the merged state is stored; the dashboard is re-published
  whenever the receiver's copy lags behind the data held.

Install: open the Pages URL in Safari → Share → *Add to Home Screen*.

Home-screen widget: `tools/widget-scriptable.js` for the Scriptable app (4 dials: Recovery, Sleep, Strain, Nutrition).
The refresh publishes a small `widget` summary; the app saves today's nutrition score to `db_widget` when Home renders.
