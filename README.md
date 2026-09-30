# Valux Games

Public studio site for **Valux Games LLC**, a game studio in Raleigh, North Carolina. Plain HTML, CSS, and JavaScript. No build step.

The site introduces the studio and links out to the games:

- [Civic Watch](https://civicwatchgame.com/) — in development, with a browser demo and an iPhone and iPad beta
- [Mecca Gecko](https://www.meccagecko.com/) — out now on the App Store

`valuxgames.com` is the canonical host. `valuxgaming.com` redirects there.

Public addresses on the site:

- `support@valuxgames.com` — players and the studio
- `legal@valuxgames.com` — privacy, terms, and other legal notes

## Preview

From this folder:

```sh
python3 -m http.server 4173 --bind 127.0.0.1
python3 scripts/validate.py
```

Open http://127.0.0.1:4173.

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

## Assets

Showcase images are copies of art already published on the Civic Watch and Mecca Gecko sites. Loading-screen illustrations are captioned separately from in-game images. Fonts are Instrument Serif and Instrument Sans, both SIL Open Font License; the license texts are in `assets/fonts/`.
