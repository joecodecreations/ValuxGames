# Valux Games

Public studio site for **Valux Games LLC**, a game studio in Raleigh, North Carolina. Plain HTML, CSS, and JavaScript. No build step.

The site introduces the studio and links out to the games:

- [Civic Watch](https://civicwatchgame.com/) — out now on the App Store and Google Play; larger releases coming
- [Mecca Gecko](https://www.meccagecko.com/) — out now on the App Store
- [Echo Brawlers: Roll & Fight](https://www.roblox.com/games/83952850539551/ECHO-BRAWLERS-Roll-Fight) — live on Roblox

`valuxgames.com` is the canonical host. `valuxgaming.com` redirects there.

Public addresses on the site:

- `support@valuxgames.com` — players and the studio
- `support@valuxgames.com` — privacy, terms, and other legal notes
- [Facebook](https://www.facebook.com/valuxgames) — Valux Games page
- [YouTube](https://www.youtube.com/@ValuxGames) — @ValuxGames channel
- [TikTok](https://www.tiktok.com/@valuxgamesofficial) — @valuxgamesofficial

The homepage contact card and every page footer link to Facebook, YouTube, and TikTok. The homepage Organization schema lists the same profiles in `sameAs`.

## Secretary

`tools/secretary/gather_valuxgames.py` pushes valuxgames.com Analytics (GA4 property `557364225`) into the Secretary app, node `valuxgames` in section `valux-games`. It does not write the game nodes. The page shows people yesterday and today so far, 28-day people and new people, clicks on store links (App Store, Play, TestFlight, Roblox, from GA4's outbound `click` event), a daily chart, and tables of sources, landing pages, countries, devices, and outbound links. The reader is `~/projects/ios_secretary_notification_app/automation/valux_google.py` (`fetch_site`, `site_blocks`), shared with the Site tabs of Civic Watch and Mecca Gecko. The key is `~/.config/valux-games/secretary-google.json`. The Secretary scheduler runs it every 30 minutes at :27 and :57 (`automation/jobs.json` in the Secretary repo, job id `valuxgames-site`); there is no launchd plist for it any more, and `tools/secretary/install_launchd.sh` only installs or refreshes the scheduler. Log `~/.config/valux-games/secretary/gather.log`. To run it outside the schedule use `python3 ~/projects/ios_secretary_notification_app/automation/scheduler.py --run valuxgames-site --wait`. The page starts with a `product` block for the Secretary Home screen, and each run uploads `assets/icon-512.png` as the node icon and the `valux-games` section icon. The phone is notified when a day has people. The first read stays quiet. The feed index is `~/projects/ios_secretary_notification_app/docs/FEEDS.md`.

`tools/secretary/gather_gameanalytics.py` reads GameAnalytics for Civic Watch and Mecca Gecko (iOS and Android are four GameAnalytics games) every 5 minutes, launchd label `com.codecreations.secretary.gameanalytics`, log `~/.config/valux-games/secretary/gameanalytics.log`. It posts live numbers to Secretary's realtime channel, writes the `players` tab on both game nodes every 30 minutes, and alerts on in-game purchases, a busiest hour, error bursts, first players on a platform, and a stopped feed. The free GameAnalytics plan has no API key, so it reads the dashboard in Chrome through Grok Browser Control (session `secretary-ga`). Chrome must stay open and signed in. Details: `~/projects/ios_secretary_notification_app/docs/FEEDS.md`.

`tools/secretary/gather_search.py` reads Google Search Console for valuxgames.com, civicwatchgame.com, and www.meccagecko.com hourly at minute 47 and at login, launchd label `com.codecreations.secretary.valux-search` (installer `tools/secretary/install_search_launchd.sh`), log `~/.config/valux-games/secretary/search.log`, state `~/.config/valux-games/secretary/search.json`. The properties belong to weboaster@gmail.com, and it reads them as `secretary-reader@valux-secretary.iam.gserviceaccount.com`, a Restricted user on each, with the same key as Analytics. It writes the `search` node in `valux-games` (Overview plus a tab per site: clicks, impressions, position, top searches and pages, which sitemap pages Google has indexed, sitemaps) and alerts on a finished day with clicks, pages Google newly indexed or dropped, new sitemap errors, and a site not read for 3 hours. The Search Console API must be enabled in Google Cloud project `valux-secretary`. `--check` prints what the reader can see. Each homepage carries a `google-site-verification` meta tag for weboaster's ownership: do not remove it. Details: `~/projects/ios_secretary_notification_app/docs/FEEDS.md`, section *Google Search Console*.

`tools/secretary/gather_social.py` reads the Valux social accounts (TikTok and Instagram `@valuxgamesofficial`, the Facebook page, YouTube `@ValuxGames`) every 15 minutes, launchd label `com.codecreations.secretary.social`, log `~/.config/valux-games/secretary/social.log`. It writes the `social` node in `valux-games` (Overview plus a tab per platform: activity, recent posts, followers) and alerts on each comment, reply, mention, or warning, and once per run for new likes, follows, and milestones. There are no API keys, so it reads each account in Chrome through Grok Browser Control in its own read-only window (session `secretary-social`), never the posting windows. It reads Chrome's **Default** profile only. Custody Commander's accounts live in the Firmbinder profile, because Instagram accounts, Facebook pages and YouTube channels switch for a whole profile. Chrome must stay open with all four Valux accounts signed in to the Default profile and Facebook acting as the page. `--check` prints who each platform is signed in as. The merge, alert and page code is shared with Custody Commander's feed (`automation/social_feed.py` in the Secretary repo). Details: `~/projects/ios_secretary_notification_app/docs/FEEDS.md`, section *Valux Games social*.

```sh
python3 tools/secretary/gather_social.py --self-test
python3 tools/secretary/gather_social.py --check
python3 tools/secretary/gather_social.py --dry-run
python3 tools/secretary/gather_gameanalytics.py --self-test
python3 tools/secretary/gather_gameanalytics.py --dry-run
tools/secretary/install_gameanalytics_launchd.sh
```

```sh
python3 tools/secretary/gather_valuxgames.py --self-test
python3 tools/secretary/gather_valuxgames.py --dry-run
python3 ~/projects/ios_secretary_notification_app/automation/scheduler.py --run valuxgames-site --wait
```

## Preview

From this folder:

```sh
python3 -m http.server 4181 --bind 127.0.0.1
python3 scripts/validate.py
```

Open http://127.0.0.1:4181.

## GitHub Pages

Repository: https://github.com/joecodecreations/ValuxGames

Pages deploys from the `main` branch at `/`. `.nojekyll` keeps this a plain static site. `CNAME` is `valuxgames.com`.

## Namecheap

After GitHub Pages has saved `valuxgames.com` as the custom domain, set both domains on Namecheap BasicDNS.

**valuxgames.com**

iCloud Mail is already on this domain. When you change DNS, keep every existing mail record and only replace the website address records:

- TXT records, including the Apple domain-verification TXT and the SPF TXT (`include:icloud.com`)
- MX records for `mx01.mail.icloud.com` and `mx02.mail.icloud.com`
- The DKIM CNAME at `sig1._domainkey`

Namecheap’s API replaces the whole host list, so those records have to be sent back with the new website records.

1. Remove the parking **A** record on `@` and any URL-redirect on `@` or `www`. Leave the mail TXT, MX, and DKIM CNAME in place.
2. Add four **A** records, host `@`, TTL Automatic:
   - `185.199.108.153`
   - `185.199.109.153`
   - `185.199.110.153`
   - `185.199.111.153`
3. Add four **AAAA** records, host `@`, TTL Automatic:
   - `2606:50c0:8000::153`
   - `2606:50c0:8001::153`
   - `2606:50c0:8002::153`
   - `2606:50c0:8003::153`
4. Add a **CNAME**, host `www`, value `joecodecreations.github.io`.
5. When GitHub’s certificate is ready, turn on **Enforce HTTPS**.

**valuxgaming.com**

Keep the existing email-forwarding MX records and the SPF TXT. Replace the parking address records with **URL Redirect** records (`URL301`):

- Host `@`, value `https://valuxgames.com`
- Host `www`, value `https://valuxgames.com`

Reference: [GitHub’s custom-domain instructions](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site).

## Design

Dark studio shell with a violet-to-pink accent, then each game takes over its own section in its own palette: Mecca Gecko in candy purple, pink, cyan and lime; Civic Watch in navy and gold. Type is Archivo (variable width and weight; headings use the 125% width at 900) with JetBrains Mono for small HUD-style labels. Both are self-hosted and SIL Open Font License; the license texts are in `assets/fonts/`.

`js/site.js` handles the mobile menu, the header background on scroll, scroll reveals, the character marquee pause button, the arena Deathmatch/Zombies toggle, and the two muted video loops. Videos play only while on screen and never start on their own when the visitor prefers reduced motion. The site works without JavaScript.

Every page loads Google Analytics 4 (`G-DVZCZV1Z40`) near the top of `<head>`. `privacy.html` describes what it collects and how to opt out; change both together. `scripts/validate.py` fails if a page is missing the tag.

## Assets

All images are WebP delivery copies. Originals stay in the game repos.

| Path | Source |
|---|---|
| `assets/mecca/key.webp`, `art-*.webp` | Mecca Gecko loading-screen art, `mecca-gecko/assets/ui/loading/load_*.jpg` (labeled as loading-screen art on the page) |
| `assets/mecca/logo.webp`, `icon.webp` | `mecca-gecko/website/store/out/headers/wordmark_logo.png`, `store/out/icon/app_icon_1024.png` |
| `assets/mecca/chars/` | Character cards from the Mecca Gecko site (promotional art, captioned as such) |
| `assets/mecca/mode-*.webp`, `map-*.webp` | Mode art and in-game map renders from the Mecca Gecko site |
| `assets/mecca/gecko-dance.mp4` | `mecca-gecko/assets/video/gecko_dancing.ogv`, re-encoded H.264, muted |
| `assets/civic/key.webp` | Civic Watch loading art, `golden-eye/assets/ui/loading/18_comedy_diner.jpg` |
| `assets/civic/icon.webp` | `golden-eye/assets/ui/brand/app_icon_1024_store.png` |
| `assets/civic/cast/`, `arenas/` | Portraits and in-game arena plates (day and Zombies) from the Civic Watch site |
| `assets/civic/reel.mp4` | Operative intro clips from `golden-eye/assets/ui/character_videos/` (Pearl, Pepe, Rico, Libby, Pierre, Floyd), cut into one muted loop |
| `assets/og.jpg`, `icon.png`, `apple-touch-icon.png`, `favicon.svg`, `assets/icon-512.png` | Studio mark and share card, generated for this site |

Game facts on the homepage (character, map, arena and weapon counts, modes, ratings, store status) follow each game's own website. Update both when a game changes. Civic Watch links to Google Play (`com.valuxgames.civicwatch`). Mecca Gecko stays "coming soon" on Android until that game is live on Google Play.

Cache-version `css/site.css` and `js/site.js` (`?v=YYYYMMDD`) when either changes.
