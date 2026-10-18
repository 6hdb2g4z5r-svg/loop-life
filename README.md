# Loop Life — iPhone web app

A thin installable shell (PWA) around a personal health dashboard. **This repo holds no data and no secrets**:
the dashboard page and its data are fetched at run time from the owner's own receiver, using a URL and key
entered once on the device (kept in the browser's local storage).

- `app/` — loader (`index.html`), runtime shim (`shim.js`: db / AI / sync), service worker, icons. Deployed by `pages.yml`.
- `pipeline/` — scheduled refresh (`refresh.yml`, every 20 min): reads new Health Auto Export files from the receiver,
  rebuilds the dashboard data and posts it back. Needs the Actions secrets `RECEIVER_URL`, `RECEIVER_KEY`, `TG_TOKEN`, `TG_CHAT`.

Install: open the Pages URL in Safari → Share → *Add to Home Screen*.
