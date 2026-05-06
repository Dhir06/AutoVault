import json
import os
import re
import time
import requests
from flask import Flask, render_template, request, redirect, url_for, jsonify
from dotenv import load_dotenv
from thefuzz import process

load_dotenv()

API_NINJAS_KEY      = os.getenv("API_NINJAS_KEY")
OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY")
MARKETCHECK_API_KEY = os.getenv("MARKETCHECK_API_KEY")

# In-memory cache for listings results: key=(make, model, zip) → (timestamp, results)
_listings_cache   = {}
LISTINGS_CACHE_TTL = 1800  # 30 minutes

# In-memory cache for Wikipedia page data: key=(make, model) → (timestamp, data)
# Prevents Wikipedia rate-limiting when multiple cars are loaded in quick succession.
_wiki_cache    = {}
WIKI_CACHE_TTL = 3600  # 1 hour

def load_brands():
    try:
        with open('brands.json', 'r') as file:
            data = json.load(file)
            return data.get("brands", [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading brands.json: {e}")
        return []

def load_variants():
    try:
        with open('variants.json', 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading variants.json: {e}")
        return {}

KNOWN_MAKES = load_brands()
VARIANTS = load_variants()
MAKES_LOWER = {make.lower(): make for make in KNOWN_MAKES}

CACHE_FILE = "model_lookup_cache.json"
CACHE_TTL  = 7 * 24 * 3600  # rebuild cache every 7 days

def build_model_lookup():
    # Load from disk cache if it exists and is fresh
    if os.path.exists(CACHE_FILE):
        try:
            age = time.time() - os.path.getmtime(CACHE_FILE)
            if age < CACHE_TTL:
                with open(CACHE_FILE, 'r') as f:
                    lookup = json.load(f)
                print(f"Model lookup loaded from cache ({len(lookup)} entries)")
                return lookup
        except Exception:
            pass

    print("Building model lookup from NHTSA (first run only, ~30 seconds)...")
    lookup = {}
    for make, models in VARIANTS.items():
        for model in models:
            lookup[model.lower()] = make
    for make in KNOWN_MAKES:
        try:
            url = f"https://vpic.nhtsa.dot.gov/api/vehicles/getmodelsformake/{make}?format=json"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                results = response.json().get("Results", [])
                for r in results:
                    if r["Make_Name"].lower() == make.lower():
                        model_name = r["Model_Name"].strip().lower()
                        if model_name and model_name not in lookup:
                            lookup[model_name] = make
        except:
            continue

    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(lookup, f)
        print(f"Model lookup cached to disk ({len(lookup)} entries)")
    except Exception as e:
        print(f"Warning: couldn't save cache: {e}")

    return lookup

CAR_KEYWORDS = ["car", "vehicle", "automobile", "motor", "truck", "suv", "sedan",
                "coupe", "engine", "automotive", "manufacturer", "horsepower", "drivetrain"]

EXCLUDED_IMAGE_PATTERNS = [
    # UI / metadata junk
    "star", "rating", "logo", "badge", "icon", "flag", "map",
    "diagram", "chart", "graph", "award", "trophy", "seal",
    "signature", "emblem", "commons-logo", "edit-icon",
    "question_book", "ambox", "padlock", "disambig", "portal",
    "arrow", "button", "symbol", "pictogram", "coat_of_arms",
    # Car detail / interior shots — we want exterior overview images
    "wheel", "tire", "tyre", "rim",
    "interior", "cockpit", "seat", "dashboard", "instrument",
    "steering", "exhaust", "engine_bay", "underhood",
]

# Flask debug mode spawns two processes. WERKZEUG_RUN_MAIN is only set in the
# actual server process, so we print only there to avoid duplicate console output.
if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    print("Loading model lookup...")
MODEL_TO_MAKE = build_model_lookup()
ALL_MODELS = list(MODEL_TO_MAKE.keys())

def is_valid_car_image(url_or_filename):
    if not url_or_filename:
        return False
    s = url_or_filename.lower()
    if not any(s.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
        return False
    for pattern in EXCLUDED_IMAGE_PATTERNS:
        if pattern in s:
            return False
    return True

def check_wikipedia_exists(titles):
    existing = set()
    wiki_headers = {"User-Agent": "AutoVault/1.0 (car research app)"}
    for i in range(0, len(titles), 50):
        batch = titles[i:i+50]
        titles_str = "|".join(batch)
        params = {"action": "query", "titles": titles_str, "format": "json"}
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params=params,
            headers=wiki_headers
        )
        if response.status_code == 200:
            pages = response.json().get("query", {}).get("pages", {})
            for page_id, page_data in pages.items():
                if int(page_id) > 0:
                    existing.add(page_data.get("title", "").lower())
    return existing

def parse_query(query):
    words = query.strip().split()
    for i in range(len(words), 0, -1):
        candidate = " ".join(words[:i]).lower()
        if candidate in MAKES_LOWER:
            make = MAKES_LOWER[candidate]
            model = " ".join(words[i:]).title()
            return make, model
    return None, query.strip().title()

def fuzzy_parse_query(query):
    words = query.strip().split()
    for i in range(len(words), 0, -1):
        candidate = " ".join(words[:i])
        match = process.extractOne(candidate, KNOWN_MAKES, score_cutoff=75)
        if match:
            make = match[0]
            model = " ".join(words[i:]).title()
            return make, model
    return None, None

def fuzzy_model_lookup(query):
    match = process.extractOne(query.lower(), ALL_MODELS, score_cutoff=70)
    if match:
        matched_model = match[0]
        make = MODEL_TO_MAKE[matched_model]
        return make, matched_model.title()
    words = query.strip().split()
    for i in range(1, len(words)):
        potential_model = " ".join(words[i:])
        match = process.extractOne(potential_model.lower(), ALL_MODELS, score_cutoff=75)
        if match:
            matched_model = match[0]
            make = MODEL_TO_MAKE[matched_model]
            return make, matched_model.title()
    return None, None

def get_specs(make, model):
    headers = {"X-Api-Key": API_NINJAS_KEY}
    variations = [
        model,
        model.lower(),
        model.replace("-", " "),
        model.replace("-", ""),
        model.replace(" ", "-"),
        model.split()[0] if " " in model else model,
    ]
    for variant in variations:
        url = f"https://api.api-ninjas.com/v1/cars?make={make}&model={variant}"
        try:
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data:
                    return data
        except:
            continue
    return []


def _wiki_get(url, params, headers, timeout):
    """
    GET a Wikipedia URL, retrying once with backoff on HTTP 429.
    Wikipedia rate-limits at ~10 req/s for anonymous clients; sequential page
    loads can briefly exceed that. A single 2-second backoff retry handles the
    common case without hanging the request.
    """
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    except Exception:
        raise
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        wait = 2.0
        if retry_after:
            try:
                wait = max(1.0, min(5.0, float(retry_after)))
            except ValueError:
                pass
        print(f"[wiki] 429 on {url.split('/')[-1] or url} — retrying after {wait}s")
        time.sleep(wait)
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    return resp


def get_section_images(page_title, wiki_headers):
    """
    Returns dict: section_title_lowercase -> image URL.

    Parses Wikipedia's *rendered HTML* (action=parse&prop=text) for the article.
    For each level-2 <h2> section, takes the first valid <img> appearing in
    that section's HTML body. This is the most reliable approach because:
      - Wikipedia handles all template expansion for us
      - Section boundaries are well-defined HTML elements
      - <h2> heading text matches the extract API exactly (no anchor/template noise)
      - Image URLs are pre-formatted — no separate imageinfo call needed
    Uses 1 API call total.
    """
    api_url    = "https://en.wikipedia.org/w/api.php"
    safe_title = page_title.replace(' ', '_')

    try:
        resp = _wiki_get(api_url, params={
            "action": "parse",
            "page":   safe_title,
            "prop":   "text",
            "format": "json",
        }, headers=wiki_headers, timeout=15)
        if resp.status_code != 200:
            print(f"[images] HTML fetch {resp.status_code} for '{page_title}'")
            return {}
        html = resp.json().get("parse", {}).get("text", {}).get("*", "")
    except Exception as e:
        print(f"[images] HTML fetch failed for '{page_title}': {e}")
        return {}

    if not html:
        return {}

    # Split on <h2> tags. Each h2 marks a top-level section boundary.
    h2_split = re.split(r'<h2(?:\s[^>]*)?>(.*?)</h2>', html, flags=re.DOTALL)
    # h2_split = [pre_first_h2_html, h2_inner1, body1, h2_inner2, body2, ...]
    if len(h2_split) < 3:
        print(f"[images] no <h2> sections found for '{page_title}'")
        return {}

    img_re = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)

    result    = {}
    used_urls = set()

    for i in range(1, len(h2_split) - 1, 2):
        # Strip all HTML tags and the [edit] link to get a clean title
        title = re.sub(r'<[^>]+>', '', h2_split[i])
        title = re.sub(r'\[\s*edit\s*\]', '', title, flags=re.IGNORECASE).strip().lower()
        if not title:
            continue

        body = h2_split[i + 1]

        for src in img_re.findall(body):
            if src.startswith('//'):
                src = 'https:' + src
            if not src.startswith('https://'):
                continue
            # Filter out tiny thumbs (icons, badges) by the size in the URL
            sm = re.search(r'/(\d+)px-', src)
            if sm and int(sm.group(1)) < 100:
                continue
            # Convert thumb URL → original full-size URL
            #   /wikipedia/commons/thumb/X/Y/FILE/Npx-FILE  →  /wikipedia/commons/X/Y/FILE
            full = re.sub(r'/thumb(/[^/]+/[^/]+/[^/]+)/[^/]+\.[a-zA-Z0-9]+$', r'\1', src)
            if not is_valid_car_image(full):
                continue
            if full in used_urls:
                continue
            result[title] = full
            used_urls.add(full)
            print(f"[images]   '{title}' ← {full.rsplit('/', 1)[-1]}")
            break

    print(f"[images] {len(result)} sections got images for '{page_title}'")
    return result


def _safe_url(url):
    """Return url only if it starts with http(s)://, else empty string."""
    if url and isinstance(url, str) and url.startswith(("https://", "http://")):
        return url
    return ""


app = Flask(__name__, template_folder='templates')

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/search")
def search():
    car = request.args.get("car", "").strip()
    if not car:
        return redirect(url_for('home'))

    make, model = parse_query(car)
    if make and model:
        return redirect(url_for('car_detail', make=make, model=model))
    if make and not model:
        return show_model_list(car, make)

    make, model = fuzzy_parse_query(car)
    if make and model:
        return redirect(url_for('car_detail', make=make, model=model))
    if make and not model:
        return show_model_list(car, make)

    car_lower = car.lower()
    if car_lower in MODEL_TO_MAKE:
        found_make = MODEL_TO_MAKE[car_lower]
        return redirect(url_for('car_detail', make=found_make, model=car.title()))

    make, model = fuzzy_model_lookup(car)
    if make and model:
        return redirect(url_for('car_detail', make=make, model=model))

    wiki_headers = {"User-Agent": "AutoVault/1.0 (car research app)"}
    params = {"action": "query", "list": "search", "srsearch": car, "format": "json"}
    wiki_response = requests.get("https://en.wikipedia.org/w/api.php", params=params, headers=wiki_headers)
    if wiki_response.status_code == 200:
        results = wiki_response.json().get("query", {}).get("search", [])
        for result in results[:5]:
            snippet = result.get("snippet", "").lower()
            title = result.get("title", "")
            if any(keyword in snippet for keyword in CAR_KEYWORDS):
                wiki_make, wiki_model = parse_query(title)
                if wiki_make and wiki_model:
                    return redirect(url_for('car_detail', make=wiki_make, model=wiki_model))

    return render_template("results.html", car=car, corrected_make=car, results=[])


def show_model_list(original_query, corrected_make):
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/getmodelsformake/{corrected_make}?format=json"
    response = requests.get(url)
    data = response.json()
    raw_results = data.get("Results", [])

    results = [r for r in raw_results if r["Make_Name"].lower() == corrected_make.lower()]

    seen = set()
    unique_results = []
    for r in results:
        model_name = r["Model_Name"].strip()
        model_lower = model_name.lower()
        if model_lower not in seen and model_name:
            seen.add(model_lower)
            unique_results.append(r)

    for variant in VARIANTS.get(corrected_make, []):
        variant_lower = variant.lower()
        if variant_lower not in seen:
            seen.add(variant_lower)
            unique_results.append({"Make_Name": corrected_make, "Model_Name": variant})

    wiki_titles = [f"{corrected_make} {r['Model_Name']}" for r in unique_results]
    existing_pages = check_wikipedia_exists(wiki_titles)

    filtered_results = [
        r for r in unique_results
        if f"{corrected_make} {r['Model_Name']}".lower() in existing_pages
    ]

    return render_template("results.html", car=original_query, corrected_make=corrected_make, results=filtered_results)


@app.route("/car/<make>/<model>")
def car_detail(make, model):

    specs = get_specs(make, model)

    wiki_headers = {"User-Agent": "AutoVault/1.0 (car research app)"}
    search_term = f"{make} {model}"

    # ── Serve from cache if fresh ─────────────────────────────────────────
    wiki_cache_key = (make.lower(), model.lower())
    if wiki_cache_key in _wiki_cache:
        ts, cached = _wiki_cache[wiki_cache_key]
        if time.time() - ts < WIKI_CACHE_TTL:
            wiki_summary, wiki_image, sections = cached
            return render_template("car_detail.html", make=make, model=model, specs=specs,
                                   wiki_summary=wiki_summary, wiki_image=wiki_image,
                                   sections=sections)

    # ── Find the Wikipedia article title ──────────────────────────────────
    wiki_page_title = None
    try:
        search_response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": search_term, "format": "json"},
            headers=wiki_headers,
            timeout=8,
        )
        if search_response.status_code == 200:
            search_results = search_response.json().get("query", {}).get("search", [])
            search_lower   = search_term.lower()

            # Pass 1: exact title match
            for result in search_results[:5]:
                if result.get("title", "").lower() == search_lower:
                    wiki_page_title = result.get("title")
                    break

            # Pass 2: keyword fallback — take first result mentioning a car keyword
            if not wiki_page_title:
                for result in search_results[:3]:
                    snippet = result.get("snippet", "").lower()
                    title   = result.get("title", "").lower()
                    if any(kw in snippet or kw in title for kw in CAR_KEYWORDS):
                        wiki_page_title = result.get("title", search_term)
                        break
    except Exception as e:
        print(f"[wiki] search failed for '{search_term}': {e}")

    # Pass 3: direct REST API fallback if search failed / rate-limited
    if not wiki_page_title:
        try:
            direct_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{search_term.replace(' ', '_')}"
            dr = requests.get(direct_url, headers=wiki_headers, timeout=8)
            if dr.status_code == 200:
                dd = dr.json()
                if dd.get("type") != "disambiguation" and any(
                    kw in dd.get("extract", "").lower() for kw in CAR_KEYWORDS
                ):
                    wiki_page_title = dd.get("title", search_term)
        except Exception as e:
            print(f"[wiki] direct REST fallback failed for '{search_term}': {e}")

    print(f"[wiki] '{search_term}' → title='{wiki_page_title}'")

    # ── Fetch summary + hero image ─────────────────────────────────────────
    wiki_summary = ""
    wiki_image   = ""
    sections     = []

    if wiki_page_title:
        try:
            summary_url   = f"https://en.wikipedia.org/api/rest_v1/page/summary/{wiki_page_title.replace(' ', '_')}"
            wiki_response = _wiki_get(summary_url, params=None, headers=wiki_headers, timeout=10)
            if wiki_response.status_code == 200:
                wiki_data    = wiki_response.json()
                wiki_summary = wiki_data.get("extract", "")
                wiki_image   = (wiki_data.get("originalimage", {}).get("source", "")
                                or wiki_data.get("thumbnail", {}).get("source", ""))
            else:
                print(f"[wiki] summary {wiki_response.status_code} for '{wiki_page_title}'")
        except Exception as e:
            print(f"[wiki] summary fetch failed for '{wiki_page_title}': {e}")

        # ── Fetch section text (extract) ──────────────────────────────────
        # This block builds section text. Isolated so image failures below
        # cannot cause this to be lost.
        try:
            extract_response = _wiki_get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action":      "query",
                    "titles":      wiki_page_title,
                    "prop":        "extracts",
                    "explaintext": "true",
                    "format":      "json",
                },
                headers=wiki_headers,
                timeout=15,
            )

            if extract_response.status_code == 200:
                pages     = extract_response.json().get("query", {}).get("pages", {})
                page      = next(iter(pages.values()))
                full_text = page.get("extract", "")

                skip_titles = {
                    "references", "external links", "see also", "notes",
                    "bibliography", "further reading", "citations", "cited sources",
                }

                raw_sections_text = re.split(r'\n==+\s*(.+?)\s*==+\n', full_text)
                for i in range(1, len(raw_sections_text) - 1, 2):
                    title = raw_sections_text[i].strip()
                    if title.lower() in skip_titles:
                        continue
                    text = raw_sections_text[i + 1].strip()
                    if text:
                        sections.append({"title": title, "text": text, "image": ""})
            else:
                print(f"[wiki] extract {extract_response.status_code} for '{wiki_page_title}'")

        except Exception as e:
            print(f"[wiki] extract failed for '{wiki_page_title}': {e}")

        # ── Add section images SEPARATELY ────────────────────────────────
        # Runs after sections text is already built. If this fails entirely,
        # sections still render with text — user loses images, not content.
        if sections:
            try:
                title_counts = {}
                for s in sections:
                    key = s["title"].lower()
                    title_counts[key] = title_counts.get(key, 0) + 1

                section_images = get_section_images(wiki_page_title, wiki_headers)

                for s in sections:
                    key = s["title"].lower()
                    if title_counts[key] == 1 and section_images.get(key):
                        s["image"] = section_images[key]

            except Exception as e:
                print(f"[wiki] section image assignment failed for '{wiki_page_title}': {e}")

    # ── Cache on success ───────────────────────────────────────────────────
    if sections:
        _wiki_cache[wiki_cache_key] = (time.time(), (wiki_summary, wiki_image, sections))
    elif wiki_summary:
        # Short TTL: sections may have failed due to rate limit — retry soon
        _wiki_cache[wiki_cache_key] = (time.time() - WIKI_CACHE_TTL + 300, (wiki_summary, wiki_image, []))

    return render_template("car_detail.html", make=make, model=model, specs=specs,
                           wiki_summary=wiki_summary, wiki_image=wiki_image,
                           sections=sections)


@app.route("/geocode")
def geocode():
    """Reverse geocode lat/lng → US zip code via Nominatim (OpenStreetMap)."""
    try:
        lat = float(request.args.get("lat", ""))
        lng = float(request.args.get("lng", ""))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid coordinates"}), 400

    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return jsonify({"error": "Coordinates out of range"}), 400

    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"format": "json", "lat": lat, "lon": lng},
            headers={"User-Agent": "AutoVault/1.0 (car research app)"},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            addr = data.get("address", {})
            postcode = addr.get("postcode", "")
            zip_code = postcode.split("-")[0] if postcode else ""
            city  = addr.get("city") or addr.get("town") or addr.get("village") or ""
            state = addr.get("state", "")
            return jsonify({"zip": zip_code, "city": city, "state": state})
    except Exception:
        pass

    return jsonify({"error": "Could not determine zip code"}), 500


@app.route("/listings")
def listings():
    """Return used car listings from Marketcheck for a given make/model/zip."""
    make     = request.args.get("make", "").strip()
    model    = request.args.get("model", "").strip()
    zip_code = request.args.get("zip", "").strip()

    if not make or not model or not zip_code:
        return jsonify({"error": "Missing required parameters", "listings": []}), 400
    if len(make) > 50 or len(model) > 60:
        return jsonify({"error": "Invalid parameters", "listings": []}), 400
    if not re.match(r"^\d{5}$", zip_code):
        return jsonify({"error": "Invalid zip code — must be 5 digits", "listings": []}), 400
    if not MARKETCHECK_API_KEY:
        return jsonify({"error": "Listings feature is not configured on this server.", "listings": []}), 500

    # Serve from cache if still fresh
    cache_key = (make.lower(), model.lower(), zip_code)
    if cache_key in _listings_cache:
        ts, cached = _listings_cache[cache_key]
        if time.time() - ts < LISTINGS_CACHE_TTL:
            return jsonify({"listings": cached})

    try:
        resp = requests.get(
            "https://mc-api.marketcheck.com/v2/search/car/active",
            params={
                "api_key":    MARKETCHECK_API_KEY,
                "make":       make,
                "model":      model,
                "zip":        zip_code,
                "radius":     100,
                "rows":       9,
                "sort_by":    "price",
                "sort_order": "asc",
            },
            timeout=10,
        )
    except requests.exceptions.Timeout:
        return jsonify({"error": "Listings service timed out. Please try again.", "listings": []}), 504
    except Exception:
        return jsonify({"error": "Could not reach listings service.", "listings": []}), 500

    if resp.status_code == 401:
        return jsonify({"error": "Listings API key is invalid.", "listings": []}), 500
    if resp.status_code == 429:
        return jsonify({"error": "Daily listing quota reached — check back tomorrow.", "listings": []}), 429
    if resp.status_code != 200:
        print(f"[listings] Marketcheck error {resp.status_code}: {resp.text[:300]}")
        return jsonify({"error": f"Listings service error (HTTP {resp.status_code})", "listings": []}), 500

    resp_data = resp.json()
    raw = resp_data.get("listings", [])
    print(f"[listings] make={make!r} model={model!r} zip={zip_code} → num_found={resp_data.get('num_found', '?')} returned={len(raw)}")
    if raw:
        first = raw[0]
        print(f"[listings] First item keys: {sorted(first.keys())}")
        print(f"[listings] price={first.get('price')!r}  year={first.get('year')!r}  build={str(first.get('build'))[:80]!r}")

    results = []
    for item in raw:
        # Marketcheck sometimes nests year inside a 'build' sub-object
        build = item.get("build") if isinstance(item.get("build"), dict) else {}
        price = item.get("price") or item.get("asking_price") or 0
        year  = item.get("year") or build.get("year")

        dealer = item.get("dealer") or {}
        media  = item.get("media")  or {}
        photos = media.get("photo_links") or media.get("photo_link_list") or []

        image = ""
        if isinstance(photos, list):
            for photo in photos:
                safe = _safe_url(photo)
                if safe.startswith("https://"):
                    image = safe
                    break

        results.append({
            "heading":     item.get("heading") or f"{year or ''} {make} {model}".strip(),
            "price":       price if price and price > 0 else None,
            "miles":       item.get("miles"),
            "year":        year,
            "dealer_name": dealer.get("name")  or "Private Seller",
            "city":        dealer.get("city")  or "",
            "state":       dealer.get("state") or "",
            "url":         _safe_url(item.get("vdp_url") or item.get("listing_url") or ""),
            "image":       image,
        })

    print(f"[listings] Built {len(results)} cards")
    _listings_cache[cache_key] = (time.time(), results)
    return jsonify({"listings": results})


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    make = data.get("make", "").strip()
    model_name = data.get("model", "").strip()
    messages = data.get("messages", [])

    if not OPENROUTER_API_KEY:
        return jsonify({"error": "AI feature is not configured on this server."}), 500

    if not messages:
        return jsonify({"error": "No messages provided"}), 400

    system_prompt = (
        f"You are AutoVault's AI assistant — a car expert answering questions about the {make} {model_name}. "
        f"RULES: "
        f"1. Keep every response between 150-250 words. No exceptions. "
        f"2. Never use markdown tables, headers, or long bullet lists. "
        f"3. Never use emojis. "
        f"4. Write like you're talking to a friend — direct, confident, conversational. "
        f"5. Give the most useful facts with specific years and numbers where relevant. Skip excessive caveats. "
        f"6. If someone asks a broad question, pick the most useful angle and answer it clearly. "
        f"7. If asked about something completely unrelated to cars or the {make} {model_name}, "
        f"politely say you can only help with questions about this vehicle."
    )

    or_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "").strip()
        if content:
            or_messages.append({"role": role, "content": content})

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai/gpt-oss-20b:free",
                "messages": or_messages,
                "temperature": 0.75,
                "max_tokens": 1024,
            },
            timeout=30,
        )
        if response.status_code == 200:
            text = response.json()["choices"][0]["message"]["content"]
            return jsonify({"reply": text})
        else:
            error_detail = response.json().get("error", {}).get("message", f"HTTP {response.status_code}")
            return jsonify({"error": f"AI service error: {error_detail}"}), 500
    except requests.exceptions.Timeout:
        return jsonify({"error": "The AI took too long to respond. Please try again."}), 504
    except Exception:
        return jsonify({"error": "Something went wrong. Please try again."}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5002)
