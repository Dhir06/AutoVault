# AutoVault 
 
A full-stack car research web app built with Python and Flask.
Search any make or model to get Wikipedia-sourced history, specs,
inline section images, and used car listings near you — all in one place.
 
## Features
 
- **Smart search** — search by make, model, or "Make Model" (e.g. "Ford Mustang" or just "Supra")
- **Fuzzy correction** — typos and misspellings are automatically corrected
- **Car detail pages** — hero image, Wikipedia summary, history sections with inline images
- **Specs sidebar** — engine, cylinders, drivetrain, transmission, and fuel type
- **Listings Near You** — find used listings by zip code or GPS location via Marketcheck
- **AI Assistant** — floating chat panel powered by OpenRouter to ask anything about the car
- **100+ brands, 1000s of models** — powered by the NHTSA vehicle database
## Tech Stack
 
- **Backend:** Python, Flask
- **Frontend:** HTML, CSS, Jinja2 templates
- **APIs:** NHTSA (makes/models), API Ninjas (specs), Wikipedia (content + images), Marketcheck (listings), OpenRouter (AI chat), OpenStreetMap Nominatim (geocoding)
## Setup
 
1. Clone the repo
```
git clone https://github.com/YOUR_USERNAME/autovault.git
cd autovault
```
 
2. Create and activate a virtual environment
```
python -m venv .venv
source .venv/bin/activate  # Mac/Linux
.venv\Scripts\activate     # Windows
```
 
3. Install dependencies
```
pip install flask python-dotenv requests thefuzz
```
 
4. Create a `.env` file in the project root with your API keys
```
API_NINJAS_KEY=your_key_here
OPENROUTER_API_KEY=your_key_here
MARKETCHECK_API_KEY=your_key_here
```
 
5. Run the app
```
python app.py
```
Then open `http://localhost:5002` in your browser.
 
## Notes
 
- On first run, AutoVault builds a model lookup table from the NHTSA API (~30 seconds). This is cached locally and only rebuilds weekly.
- The `.env` file is intentionally excluded from this repo. Never commit API keys.
## Status
 
Active development — more features in progress.