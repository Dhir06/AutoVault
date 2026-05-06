# AutoVault — Project Guidelines

## What This App Does

AutoVault is a car research web app that lets users search for any vehicle and get comprehensive information including specs, history, images, and development timeline. Users can search by make (e.g. "Ford"), by make + model (e.g. "Ford Mustang"), or by just a model name (e.g. "Supra") and the app intelligently routes them to the right page. Built for my computer science resume to showcase full-stack development, API integration, and data aggregation skills.

## Tech Stack

- **Backend:** Python 3.12 + Flask
- **Frontend:** HTML + Jinja2 templates + vanilla CSS (no framework)
- **Fonts:** Orbitron (display) + DM Sans (body) via Google Fonts
- **IDE:** PyCharm Pro
- **Python libraries:** `flask`, `requests`, `python-dotenv`, `thefuzz`, `python-Levenshtein`
- **Port:** 5001 (port 5000 conflicts with macOS AirPlay Receiver)

## Project Structure
```
Car Project/
├── .venv/                  # virtual environment
├── static/
│   └── style.css          # all styling, dark motorsport theme
├── templates/
│   ├── index.html         # homepage with search
│   ├── results.html       # model list for a make
│   └── car_detail.html    # individual car page
├── app.py                 # main Flask app
├── brands.json            # curated list of real car makes
├── variants.json          # notable variants NHTSA misses (e.g. Ram 1500 TRX)
├── .env                   # API keys (never commit this)
└── CLAUDE.md             # this file
```

## APIs Used

| API | Purpose | Cost |
|---|---|---|
| NHTSA vPIC | Make/model lists | Free, unlimited |
| API Ninjas Cars | Spec data (engine, drivetrain, transmission) | Free tier — no horsepower, no MPG, no limit param |
| Wikipedia API | Summaries, history sections, images | Free |

Environment variables in `.env`:
- `API_NINJAS_KEY`
- Previously had `CARAPI_KEY` but ditched — 100 req/month free tier too restrictive

## Key Features Built

1. **Smart Search** — multi-tier search logic: exact make match → fuzzy make match → exact model lookup → fuzzy model match → Wikipedia search as final fallback
2. **Spell Correction** — fuzzy matching via `thefuzz` handles misspelled makes AND models (e.g. "frod mustng" resolves to Ford Mustang)
3. **Direct Routing** — "Ford Mustang" goes straight to the car page, "Ford" shows the model list, "Mustang" alone also goes direct
4. **Wikipedia Verification** — before showing a model in the list, we batch-check Wikipedia to confirm a page exists so users never click a dead link
5. **Rich Car Pages** — hero image, summary, history sections with inline images pulled from each Wikipedia section, and specs sidebar

## Architectural Decisions

- **brands.json + variants.json separation** — data lives in JSON files, logic in Python. Makes it easy to add makes/variants without code changes.
- **Model lookup table built at startup** — on app boot we scrape NHTSA for every model of every known make and build a `MODEL_TO_MAKE` dictionary. Takes ~30 seconds on first launch but then lookups are instant. This enables searching by model name alone.
- **No database** — all data fetched from APIs in real time. Keeps the app stateless and easy to deploy.
- **Curated brands list** — we don't accept every NHTSA make because the database contains thousands of commercial/obscure manufacturers. Our `brands.json` is a hand-picked list of real consumer car brands.
- **Wikipedia as primary content source** — more reliable and richer than any paid car API for historical/descriptive content.

## Design System

- **Aesthetic:** Dark luxury motorsport (think Ferrari's website)
- **Colors:**
  - Primary bg: `#080808`
  - Card bg: `#141414`
  - Accent: `#dc2626` (racing red)
  - Text primary: `#f5f5f5`
  - Text secondary: `#c4c4c4`
- **Typography:** Orbitron for headings/labels (geometric, motorsport), DM Sans for body
- **Textures:** Subtle diagonal carbon fiber overlay on background
- **Animations:** Staggered fade-up on page load

## How to Work With Me (User Preferences)

- **I'm vibe coding.** I describe what I want, Claude writes the code. I'm a sophomore CS major.
- **ALWAYS give me the full file when making changes.** Never tell me to "replace just this section" — I find partial edits confusing and I mess them up.
- **Explain what you're doing and why.** I want to learn as we build.
- **Don't go in circles on edge cases.** If something minor isn't working after a couple tries, we move on and come back later. Shipping features > perfection.
- **I have strong car knowledge.** I'll catch factual inaccuracies about cars, trims, specs.
- **Be direct and honest.** If an approach won't work, say so. Don't waste my time.

## Known Minor Issues (Accepted For Now)

- Ford F-100 and F-600 redirect to F-150 page (Wikipedia redirect quirk)
- Sienna sometimes pulls up a Toyota transmission page (Wikipedia search relevance)
- API Ninjas free tier returns limited data — can't show multiple generations of specs
- Ram TRX only shows under make search, not as standalone model

## Still To Build

1. **AI feature** — "Ask AI about this car" button using Gemini API
2. **PWA support** — make the app installable on mobile home screens
3. **Final polish and testing** — cross-browser checks, mobile responsiveness, edge cases