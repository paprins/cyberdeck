# Homepage Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bento-box homepage with a survivalist card grid that is a 100% visual match to `mockup/code.html`, using Space Grotesk + Inter fonts, 7 category images, and the mockup's full Tailwind color palette.

**Architecture:** The home router is simplified to pass a flat `list[ModuleCard]` to the template instead of a `BentoLayout`. The template renders a fixed 4-column CSS grid of image cards, each linked to the module's URL, with a system-log footer strip. The bento service is deleted.

**Tech Stack:** FastAPI, Jinja2, Alpine.js, Tailwind CSS v4 (`@import "tailwindcss"` + `@theme`), Material Symbols Outlined (CDN icon font), Space Grotesk + Inter (self-hosted woff2), Python `urllib` for font download.

---

## File Map

| Action | Path |
|---|---|
| CREATE | `app/static/fonts/space-grotesk-{300,400,500,600,700}.woff2` |
| CREATE | `app/static/fonts/inter-{400,500,600,700}.woff2` |
| CREATE | `app/static/images/categories/{medical,food,energy,mechanic,gardening,shelter,animal_care}.jpg` |
| MODIFY | `app/static/css/input.css` — full replacement |
| MODIFY | `app/templates/base.html` — new header, keep Alpine.js JS |
| MODIFY | `app/templates/home.html` — card grid + system-log footer |
| MODIFY | `app/routers/home.py` — drop bento, pass `list[ModuleCard]` |
| DELETE | `app/services/bento.py` |
| DELETE | `app/templates/macros/tile.html` |
| MODIFY | `tests/test_home.py` — update assertions for new design |
| DELETE | `tests/test_bento.py` |

---

## Task 1: Download Space Grotesk + Inter fonts

**Files:**
- Create: `app/static/fonts/space-grotesk-{300,400,500,600,700}.woff2`
- Create: `app/static/fonts/inter-{400,500,600,700}.woff2`

- [ ] **Step 1: Run the font download script**

```bash
python3 - <<'PYEOF'
import re, urllib.request, os

os.makedirs("app/static/fonts", exist_ok=True)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Space+Grotesk:wght@300;400;500;600;700"
    "&family=Inter:wght@400;500;600;700"
    "&display=swap"
)
req = urllib.request.Request(URL, headers={"User-Agent": UA})
with urllib.request.urlopen(req) as r:
    css = r.read().decode()

blocks = re.findall(r'@font-face \{[^}]+\}', css, re.DOTALL)
for block in blocks:
    # Only grab Latin subset (last occurrence per family+weight = latin)
    family = re.search(r"font-family:\s*'([^']+)'", block)
    weight = re.search(r'font-weight:\s*(\d+)', block)
    url    = re.search(r'url\((https://fonts\.gstatic[^)]+\.woff2)\)', block)
    if not (family and weight and url):
        continue
    slug = family.group(1).lower().replace(" ", "-")
    fname = f"app/static/fonts/{slug}-{weight.group(1)}.woff2"
    print(f"  {fname}")
    urllib.request.urlretrieve(url.group(1), fname)

print("Done")
PYEOF
```

Expected output (order may vary — 9 files total):
```
  app/static/fonts/space-grotesk-300.woff2
  app/static/fonts/space-grotesk-400.woff2
  app/static/fonts/space-grotesk-500.woff2
  app/static/fonts/space-grotesk-600.woff2
  app/static/fonts/space-grotesk-700.woff2
  app/static/fonts/inter-400.woff2
  app/static/fonts/inter-500.woff2
  app/static/fonts/inter-600.woff2
  app/static/fonts/inter-700.woff2
Done
```

- [ ] **Step 2: Verify files exist and are non-zero**

```bash
ls -lh app/static/fonts/*.woff2
```

Expected: 9 `.woff2` files, each > 10 KB.

- [ ] **Step 3: Commit**

```bash
git add app/static/fonts/space-grotesk-*.woff2 app/static/fonts/inter-*.woff2
git commit -m "feat: add Space Grotesk and Inter fonts (self-hosted)"
```

---

## Task 2: Download category images

**Files:**
- Create: `app/static/images/categories/medical.jpg`
- Create: `app/static/images/categories/food.jpg`
- Create: `app/static/images/categories/energy.jpg`
- Create: `app/static/images/categories/mechanic.jpg`
- Create: `app/static/images/categories/gardening.jpg`
- Create: `app/static/images/categories/shelter.jpg`
- Create: `app/static/images/categories/animal_care.jpg`

- [ ] **Step 1: Download all 7 images**

```bash
mkdir -p app/static/images/categories

curl -sL "https://lh3.googleusercontent.com/aida-public/AB6AXuAVbZK9O_TyHlERXKorYrui-ZFaW8W4snjBnaXBYU9Ws9Rz8E9OlZgUG6GSscs6o6WTfbdHNu2ssZeU0hjQWY9_UrrDEexrJHsBm4tJijLBpVlEdCnkty8_VQEOcPeSRe-ATh_0q6GeqPcK5sU3ib7l6wgNYCIopQAmmyvSFCDGfaxjpNdRy3PyfGAg6gikyEjzmU9sPMrSr1g98vecNDPad7DLBYv-1W2LEdhLNAU5Bk8C7VdmLXfCWO_nWmjPsVc0m6jIW9dohGTX" \
  -o app/static/images/categories/medical.jpg

curl -sL "https://lh3.googleusercontent.com/aida-public/AB6AXuCRinx9caypBkK8i-5ngVv06a6RZOofuzh3T-M_Q9jN4nK1iGZVzK8ibrNbCuuxgFax6wnyiJQKafDFydUXnAzNQkdWXm-2djDPCmIpVkOhfhty1bOnP1-alcevZCglL4SL2N5dJcvspNLDmpQ5z1JhvFZMySk8RDZ-jzXNY4A7308KLcwi8EuNDXywkR46lBNXoMk8I9srYbSdN7gt3BeVGH1fPuGW-rnXfEiEXQuPmSkbhXIthR1dJJZojt7gDfIoXqNdHoVWJH_r" \
  -o app/static/images/categories/food.jpg

curl -sL "https://lh3.googleusercontent.com/aida-public/AB6AXuDPmFPEsCeVuevnnypQfaAutLtL7SXK4Qlguv6fxs7tH1FJj7DV9ulKtTXOC2nHAwlCkRi_cKhq-aI__7Mex4boOcAa68ZogCI5I03bsZnBZ_wJN6zzRiGp5RzTGC44oTxKPhDiobSKKezuzQYS5LT5jqkk-zafSjeORjC_jCstylJuEgrD6aV9K3tjFGh24iIaPbT2eQWbxMSIhyxatoR75DjQsGsHIkdo5bnwFp2C38opIaropIOkqkWqohnjdmuHe9dDXjOxccZJ" \
  -o app/static/images/categories/energy.jpg

curl -sL "https://lh3.googleusercontent.com/aida-public/AB6AXuBF1lfqGJJA2rOQ1cHUdS_lvbyCAaw75sxb-sHXi4pQxhH-d0m7IR0F8sp2Kkg9tNuqKwjh4wSsOQ6kbLePG7lvrD9Uuc0j2EkZ8JI7p3yvCDwb6He0wiwzTdaJKYvTn7GzD6khn0MJKdiI3E5tDcuw-XElLo3PT4gJhzBSn5bIRRcpHLXZMhHjL64pfDNtnIOCr0ixu6OrlZpoi3ItKLcYN9vpHisFCUOPIhJSwvpxgp6bUcGzRTWAJ" \
  -o app/static/images/categories/mechanic.jpg

curl -sL "https://lh3.googleusercontent.com/aida-public/AB6AXuBHsw9rSbsEcvSylo7P-9qrYia6hMvfiIcNyPf6xz21qz3S3bdFrvagSdVMDkknLxaJq8wqnxKdgV1R_C5DJfr20hD_-nFsiIdqNDbs2xjTXM6SAA5LUaxIl_gqZSfBOuiAj-TrVrXWrVasL0JFUnDFvoK8AfvIVjGDOBxa3QjUL_MCrNdbpRflxxO919CFUcRRZI_WfZGZqpKNIw35ZrQG6_kzn5hvuF7ZeKgQ-qGjGx1thyQ7N4nNrPIIujkRaQRoRKdR41FuPlTj" \
  -o app/static/images/categories/gardening.jpg

curl -sL "https://lh3.googleusercontent.com/aida-public/AB6AXuAkpqvBqN498T9_4-lwki5juprFhZG73qStRFNr-PR2V2wMjYLSItiQoGGOnuau9WB5wa7F8RMFeHP7sKg1a4BlcxtMfnjVf77BeLxeilb32JNTyvTgKABBITtBOfTtw_28QzHbAc72fbEiEkZV1plTmHuYdOgoCF6dnvLLb4l6eI2kzIadLN84hKu2PCVG_JrmpZjRDYt1JsOZVa22iRlUYNOuN7WGFCF_R3i08sEaEjgsy1nhgdStxe6JNVdReh1_E_Cg5wgDit0O" \
  -o app/static/images/categories/shelter.jpg

curl -sL "https://lh3.googleusercontent.com/aida-public/AB6AXuAVV3rNXQgx5l0isWCiWRPxISMMVnkHNPbPSJd3Pt-VYJHCyVPJl_9Xubv_YUUTs5HRL_ApV_Glc5Bdh8vGIXQaFi95hSZbWKBIIz0rcDf6oJFzM2yfIxDkJLckT7tnn8VI73yqmI9US0tzT0-R9DRKzRav_U2tIL0H08kcQdw3mqaV5C_sxNulGXGU_gkyudiIxsiGFHqwvmrEdygJwg2zyXGmcqwAV1vrWOA_icInb-FpCcVc0_gbvGx9-D-imuIJX6Lyk7JVbUPV" \
  -o app/static/images/categories/animal_care.jpg
```

- [ ] **Step 2: Verify all images downloaded**

```bash
ls -lh app/static/images/categories/
```

Expected: 7 `.jpg` files, each > 50 KB.

- [ ] **Step 3: Commit**

```bash
git add app/static/images/
git commit -m "feat: add category images from mockup"
```

---

## Task 3: Replace CSS tokens + rebuild

**Files:**
- Modify: `app/static/css/input.css`

- [ ] **Step 1: Replace `input.css` entirely**

```css
@import "tailwindcss";

@theme {
  /* ── Surfaces ── */
  --color-surface:                  #131313;
  --color-surface-dim:              #131313;
  --color-surface-container-lowest: #0e0e0e;
  --color-surface-container-low:    #1b1b1b;
  --color-surface-container:        #1f1f1f;
  --color-surface-container-high:   #2a2a2a;
  --color-surface-container-highest:#353535;
  --color-surface-variant:          #353535;
  --color-surface-bright:           #393939;
  --color-background:               #131313;

  /* ── Primary (orange) ── */
  --color-primary:                  #ffb693;
  --color-primary-container:        #ff6b00;
  --color-on-primary:               #561f00;
  --color-on-primary-container:     #572000;
  --color-on-primary-fixed:         #351000;
  --color-primary-fixed:            #ffdbcc;
  --color-primary-fixed-dim:        #ffb693;

  /* ── Secondary (purple) ── */
  --color-secondary:                #d3beeb;
  --color-secondary-container:      #524267;
  --color-on-secondary:             #38294d;
  --color-on-secondary-container:   #c4b0dd;
  --color-secondary-fixed:          #eddcff;
  --color-secondary-fixed-dim:      #d3beeb;
  --color-on-secondary-fixed:       #231437;
  --color-on-secondary-fixed-variant:#4f4065;

  /* ── Tertiary (blue) ── */
  --color-tertiary:                 #9ccaff;
  --color-tertiary-container:       #059eff;
  --color-on-tertiary:              #003257;
  --color-on-tertiary-container:    #003357;
  --color-tertiary-fixed:           #d0e4ff;
  --color-tertiary-fixed-dim:       #9ccaff;
  --color-on-tertiary-fixed:        #001d35;
  --color-on-tertiary-fixed-variant:#00497b;

  /* ── Outline ── */
  --color-outline:                  #a98a7d;
  --color-outline-variant:          #5a4136;

  /* ── Text ── */
  --color-on-surface:               #e2e2e2;
  --color-on-surface-variant:       #e2bfb0;
  --color-on-background:            #e2e2e2;

  /* ── Inverse ── */
  --color-inverse-surface:          #e2e2e2;
  --color-inverse-on-surface:       #303030;
  --color-inverse-primary:          #a04100;
  --color-surface-tint:             #ffb693;

  /* ── Error ── */
  --color-error:                    #ffb4ab;
  --color-error-container:          #93000a;
  --color-on-error:                 #690005;
  --color-on-error-container:       #ffdad6;

  /* ── Typography ── */
  --font-headline: 'Space Grotesk', sans-serif;
  --font-body:     'Inter', sans-serif;
  --font-label:    'Space Grotesk', sans-serif;

  /* ── Shape: 0px everywhere, full stays round ── */
  --radius:        0px;
  --radius-sm:     0px;
  --radius-md:     0px;
  --radius-lg:     0px;
  --radius-xl:     0px;
  --radius-2xl:    0px;
  --radius-3xl:    0px;
  --radius-full:   9999px;
}

@layer base {
  @font-face {
    font-family: 'Space Grotesk';
    src: url('/static/fonts/space-grotesk-300.woff2') format('woff2');
    font-weight: 300; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Space Grotesk';
    src: url('/static/fonts/space-grotesk-400.woff2') format('woff2');
    font-weight: 400; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Space Grotesk';
    src: url('/static/fonts/space-grotesk-500.woff2') format('woff2');
    font-weight: 500; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Space Grotesk';
    src: url('/static/fonts/space-grotesk-600.woff2') format('woff2');
    font-weight: 600; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Space Grotesk';
    src: url('/static/fonts/space-grotesk-700.woff2') format('woff2');
    font-weight: 700; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Inter';
    src: url('/static/fonts/inter-400.woff2') format('woff2');
    font-weight: 400; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Inter';
    src: url('/static/fonts/inter-500.woff2') format('woff2');
    font-weight: 500; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Inter';
    src: url('/static/fonts/inter-600.woff2') format('woff2');
    font-weight: 600; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Inter';
    src: url('/static/fonts/inter-700.woff2') format('woff2');
    font-weight: 700; font-style: normal; font-display: swap;
  }

  [x-cloak] { display: none !important; }

  /* Scrollbar */
  ::-webkit-scrollbar       { width: 4px; }
  ::-webkit-scrollbar-track { background: #0e0e0e; }
  ::-webkit-scrollbar-thumb { background: #ff6b00; }
}
```

- [ ] **Step 2: Rebuild CSS**

```bash
tailwindcss -i app/static/css/input.css -o app/static/css/app.css
```

Expected: output like `Done in Xms.` with no errors.

- [ ] **Step 3: Commit**

```bash
git add app/static/css/input.css app/static/css/app.css
git commit -m "feat: replace CSS tokens with mockup palette, Space Grotesk + Inter"
```

---

## Task 4: Update home router — TDD

**Files:**
- Modify: `app/routers/home.py`
- Modify: `tests/test_home.py`
- Delete: `app/services/bento.py`
- Delete: `app/templates/macros/tile.html`
- Delete: `tests/test_bento.py`

- [ ] **Step 1: Write the updated `tests/test_home.py`**

Replace the file completely:

```python
from __future__ import annotations
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.models.registry import Module, Registry
from app.services.registry import save_registry


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_home_returns_200(client):
    r = await client.get("/")
    assert r.status_code == 200


async def test_home_returns_html(client):
    r = await client.get("/")
    assert "text/html" in r.headers["content-type"]


async def test_home_renders_wordmark(client):
    r = await client.get("/")
    assert "SURVIVAL_DASHBOARD" in r.text


async def test_home_import_module_card_always_present(client):
    r = await client.get("/")
    assert "IMPORT_MODULE" in r.text
    assert 'href="/packages"' in r.text


async def test_home_shows_active_module_name(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="medical-wikimed", display_name="Medical Wiki", category="medical",
                description="Emergency medicine reference", latest_version="2024-01",
                size_gb=0.8, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert "Medical Wiki" in r.text or "MEDICAL_WIKI" in r.text


async def test_home_shows_module_size(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="medical-wikimed", display_name="Medical Wiki", category="medical",
                description="Emergency medicine reference", latest_version="2024-01",
                size_gb=3.2, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert "3.2" in r.text


async def test_home_maps_module_has_mbtiles_url(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="maps-world", display_name="Maps", category="maps",
                description="OSM", latest_version="2024-01",
                size_gb=10, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert 'href="http://localhost:8081/' in r.text


async def test_home_medical_module_has_kiwix_url(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="medical-wikimed", display_name="Medical", category="medical",
                description="WikiMed", latest_version="2024-01",
                size_gb=0.8, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert 'href="http://localhost:8080/medical-wikimed/' in r.text


async def test_home_inactive_modules_not_shown(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="medical-wikimed", display_name="Secret Module", category="medical",
                description="Should not appear", latest_version="2024-01",
                size_gb=0.8, checksum="sha256:abc", active=False,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert "Secret Module" not in r.text
```

- [ ] **Step 2: Run tests — expect failures**

```bash
uv run pytest tests/test_home.py -v 2>&1 | head -50
```

Expected: `test_home_renders_wordmark` FAILS (still says "CYBERDECK"), `test_home_import_module_card_always_present` FAILS, `test_home_shows_module_size` FAILS. Others may pass.

- [ ] **Step 3: Replace `app/routers/home.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import Settings
from app.models.registry import Module
from app.services.registry import load_registry
from app.services.system import read_system_status

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


@dataclass
class ModuleCard:
    module: Module
    url: str


def _tile_url(module: Module, cfg: Settings) -> str:
    if module.category == "maps":
        return f"http://localhost:{cfg.mbtiles_port}/"
    if module.category == "packages":
        return "/packages"
    if module.category == "internet":
        return "https://duckduckgo.com"
    return f"http://localhost:{cfg.kiwix_port}/{module.id}/"


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=_TEMPLATE_DIR)

    @router.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        registry = load_registry(cfg)
        status = read_system_status(cfg)
        active = [m for m in registry.modules if m.active]
        cards = [ModuleCard(module=m, url=_tile_url(m, cfg)) for m in active]
        return templates.TemplateResponse(request, "home.html", {
            "cards": cards,
            "battery_pct": status.battery_pct,
            "wifi_connected": status.wifi_connected,
        })

    return router
```

- [ ] **Step 4: Delete bento service and tile macro**

```bash
rm app/services/bento.py
rm app/templates/macros/tile.html
rm tests/test_bento.py
```

- [ ] **Step 5: Run home tests — should pass**

```bash
uv run pytest tests/test_home.py tests/test_tile_url.py -v
```

Expected: all tests PASS. (`test_tile_url.py` imports `_tile_url` from `home.py` — still present.)

- [ ] **Step 6: Run full suite — check nothing else broke**

```bash
uv run pytest --ignore=tests/test_bento.py -v 2>&1 | tail -20
```

Expected: all non-bento tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/routers/home.py tests/test_home.py
git rm app/services/bento.py app/templates/macros/tile.html tests/test_bento.py
git commit -m "refactor: replace bento layout with flat ModuleCard list; delete bento service"
```

---

## Task 5: Redesign base.html

**Files:**
- Modify: `app/templates/base.html`

- [ ] **Step 1: Replace `app/templates/base.html`**

```html
<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=1280, initial-scale=1">
  <title>Cyberdeck</title>
  <link rel="stylesheet" href="/static/css/app.css">
  <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet">
  <script defer src="/static/js/alpine.min.js"></script>
</head>
<body
  class="bg-[#131313] text-on-surface font-body h-full overflow-hidden flex flex-col"
  x-data="{
    battery_pct: {{ battery_pct | tojson }},
    wifi_connected: {{ wifi_connected | tojson }},
    lastActivity: Date.now(),
    dimmed: false,
    restorePct: null,
    async poll() {
      try {
        const r = await fetch('/api/system');
        const d = await r.json();
        this.battery_pct = d.battery_pct;
        this.wifi_connected = d.wifi_connected;
      } catch(e) {}
    },
    async initBrightness() {
      try {
        const r = await fetch('/api/system/brightness');
        const d = await r.json();
        this.restorePct = d.brightness_pct;
      } catch(e) {}
    },
    async _setBrightness(pct) {
      try {
        await fetch('/api/system/brightness', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({level: pct})
        });
      } catch(e) {}
    },
    _onActivity() {
      this.lastActivity = Date.now();
      if (this.dimmed) {
        this.dimmed = false;
        this._setBrightness(this.restorePct ?? 100);
      }
    }
  }"
  x-init="
    initBrightness();
    setInterval(() => poll(), 10000);
    setInterval(() => {
      if (!dimmed && Date.now() - lastActivity > 120000) {
        dimmed = true;
        _setBrightness(10);
      }
    }, 30000);
    ['mousemove', 'keydown', 'click', 'touchstart'].forEach(e =>
      window.addEventListener(e, () => _onActivity(), {passive: true})
    );
  "
  @keydown.ctrl.k.window.prevent="document.getElementById('search') && document.getElementById('search').focus()"
>

  <!-- ── Header ── -->
  <header class="bg-[#131313] w-full z-50 flex justify-between items-center px-6 flex-shrink-0"
          style="height:64px; border-bottom: 1px solid rgba(90,65,54,0.15);">

    <!-- Left: brand + search -->
    <div class="flex items-center gap-6">
      <!-- Logo -->
      <div class="w-10 h-10 bg-primary-container flex items-center justify-center flex-shrink-0">
        <span class="material-symbols-outlined text-on-primary-container text-2xl" style="font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24">radar</span>
      </div>

      <!-- Wordmark -->
      <div class="flex flex-col">
        <div class="text-xl font-bold text-primary-container tracking-tighter font-headline uppercase leading-none">
          SURVIVAL_DASHBOARD
        </div>
        <div class="text-[8px] font-label tracking-[0.3em] uppercase mt-1 leading-none"
             style="color: rgba(255,182,147,0.6);">
          SECURE_ACCESS // SECTOR_G14
        </div>
      </div>

      <!-- Search -->
      <div class="hidden xl:flex items-center bg-surface-container-lowest px-4 py-1.5 gap-3 ml-4"
           style="border: 1px solid rgba(90,65,54,0.2);"
           x-data="{
             searchQuery: '',
             searchResults: [],
             searchOpen: false,
             async search() {
               if (this.searchQuery.length < 2) { this.searchResults = []; this.searchOpen = false; return; }
               try {
                 const r = await fetch('/api/search?q=' + encodeURIComponent(this.searchQuery));
                 this.searchResults = await r.json();
                 this.searchOpen = this.searchResults.length > 0;
               } catch(e) { this.searchResults = []; }
             }
           }"
      >
        <span class="material-symbols-outlined text-primary text-sm" style="font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24">search</span>
        <input
          id="search"
          type="text"
          x-model="searchQuery"
          @input.debounce.300ms="search()"
          @keydown.escape="searchResults = []; searchOpen = false"
          placeholder="QUERY_DATABASE..."
          class="bg-transparent border-none focus:ring-0 text-[10px] font-label uppercase tracking-wider w-48 text-on-surface placeholder:opacity-30 outline-none"
          autocomplete="off"
        >
        <!-- Search results dropdown -->
        <div x-show="searchOpen && searchResults.length > 0" x-cloak
             class="absolute top-14 bg-surface-container border border-outline-variant/30 overflow-hidden z-50 w-80">
          <template x-for="result in searchResults" :key="result.title + result.module">
            <a :href="result.url"
               class="flex items-center gap-3 px-4 py-3 border-b border-outline-variant/20 last:border-b-0 hover:bg-surface-container-high"
               @click="searchOpen = false; searchQuery = ''">
              <span class="text-on-surface-variant text-[10px] tracking-[0.08em] uppercase font-label min-w-[80px]" x-text="result.module"></span>
              <span class="text-on-surface text-[13px] font-body truncate" x-text="result.title"></span>
            </a>
          </template>
        </div>
      </div>
    </div>

    <!-- Right: status + shutdown -->
    <div class="flex items-center gap-6">

      <!-- Language dropdown -->
      <div class="flex items-center gap-2 bg-surface-container-highest px-3 py-1.5 cursor-pointer"
           style="border: 1px solid rgba(90,65,54,0.3);">
        <span class="material-symbols-outlined text-primary text-sm" style="font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24">language</span>
        <span class="text-xs font-label uppercase font-bold">ENG_US</span>
        <span class="material-symbols-outlined text-xs" style="font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24">expand_more</span>
      </div>

      <!-- System icons -->
      <div class="flex items-center gap-4 text-on-surface/70">
        <span class="material-symbols-outlined cursor-pointer hover:text-primary"
              style="font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24"
              title="Settings">settings</span>
        <span class="material-symbols-outlined cursor-pointer hover:text-primary"
              style="font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24"
              :title="'Battery: ' + (battery_pct ?? '?') + '%'"
              x-text="'battery_charging_full'">battery_charging_full</span>
        <span class="material-symbols-outlined cursor-pointer"
              style="font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24"
              :class="wifi_connected ? 'text-tertiary' : 'text-error'"
              :title="wifi_connected ? 'Online' : 'Offline'">signal_cellular_connected_no_internet_4_bar</span>

        <div class="h-6 w-px bg-outline-variant/20 mx-2"></div>

        <!-- Shutdown -->
        <button class="flex items-center gap-2 text-error px-3 py-1.5 font-label text-xs tracking-widest uppercase"
                style="border: 1px solid rgba(255,180,171,0.2);">
          <span class="material-symbols-outlined text-sm" style="font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24">power_settings_new</span>
          SHUTDOWN
        </button>
      </div>
    </div>
  </header>

  <!-- ── Main content ── -->
  <div class="flex-1 flex flex-col overflow-hidden">
    {% block content %}{% endblock %}
  </div>

</body>
</html>
```

- [ ] **Step 2: Rebuild CSS (new classes need scanning)**

```bash
tailwindcss -i app/static/css/input.css -o app/static/css/app.css
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/test_home.py -v
```

Expected: all pass (wordmark test now finds "SURVIVAL_DASHBOARD").

- [ ] **Step 4: Commit**

```bash
git add app/templates/base.html app/static/css/app.css
git commit -m "feat: replace header with mockup survivalist design"
```

---

## Task 6: Redesign home.html — card grid + system log

**Files:**
- Modify: `app/templates/home.html`

- [ ] **Step 1: Replace `app/templates/home.html`**

```html
{% extends "base.html" %}

{% block content %}
<main class="flex-1 overflow-hidden flex flex-col p-8">

  {#-- Category metadata: icon, badge, image --#}
  {%- set META = {
    'medical':    {'icon': 'medication',   'badge': 'CRITICAL', 'badge_bg': 'bg-error-container',        'badge_text': 'text-on-error-container'},
    'food':       {'icon': 'inventory',    'badge': 'RESOURCE', 'badge_bg': 'bg-secondary-container',    'badge_text': 'text-on-secondary-container'},
    'energy':     {'icon': 'bolt',         'badge': 'GRID_OFF', 'badge_bg': 'bg-tertiary-container',     'badge_text': 'text-on-tertiary'},
    'mechanic':   {'icon': 'build',        'badge': None,       'badge_bg': '',                          'badge_text': ''},
    'gardening':  {'icon': 'potted_plant', 'badge': None,       'badge_bg': '',                          'badge_text': ''},
    'shelter':    {'icon': 'foundation',   'badge': None,       'badge_bg': '',                          'badge_text': ''},
    'animal_care':{'icon': 'pets',         'badge': None,       'badge_bg': '',                          'badge_text': ''},
  } -%}

  {#-- Card grid --#}
  <div class="flex-1 grid grid-cols-4 grid-rows-2 gap-4">

    {% for card in cards %}
    {%- set cat = card.module.category -%}
    {%- set meta = META.get(cat, {'icon': 'folder', 'badge': None, 'badge_bg': '', 'badge_text': ''}) -%}
    <a href="{{ card.url }}"
       class="bg-surface-container flex flex-col cursor-pointer group border-b-2 border-transparent hover:bg-surface-container-high hover:border-primary">
      {#-- Image --#}
      <div class="flex-1 relative overflow-hidden" style="max-height: 50%;">
        <img src="/static/images/categories/{{ cat }}.jpg"
             alt="{{ card.module.display_name }}"
             class="w-full h-full object-cover brightness-75 grayscale group-hover:grayscale-0"
             style="transition: none;">
        {% if meta.badge %}
        <div class="absolute top-2 right-2 {{ meta.badge_bg }} {{ meta.badge_text }} px-2 py-1 text-[10px] font-bold font-label uppercase">
          {{ meta.badge }}
        </div>
        {% endif %}
      </div>
      {#-- Info --#}
      <div class="p-4 flex flex-col" style="min-height: 50%;">
        <div class="flex justify-between items-start mb-2">
          <h4 class="font-headline font-bold text-lg uppercase tracking-tight text-on-surface group-hover:text-primary leading-tight">
            {{ card.module.display_name | replace(' ', '_') }}
          </h4>
          <span class="material-symbols-outlined text-on-secondary-container text-xl"
                style="font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24">{{ meta.icon }}</span>
        </div>
        <p class="text-[11px] text-on-surface/60 font-body mb-4 leading-snug flex-1">
          {{ card.module.description }}
        </p>
        <div class="flex justify-between items-center mt-auto">
          <span class="text-[9px] font-label text-on-surface/40 uppercase">{{ card.module.size_gb }}_GB</span>
          <span class="text-[9px] font-label text-primary font-bold">VIEW →</span>
        </div>
      </div>
    </a>
    {% endfor %}

    {#-- IMPORT_MODULE card (always last) --#}
    <a href="/packages"
       class="bg-surface-container-lowest flex flex-col items-center justify-center p-4 group hover:border-primary cursor-pointer"
       style="border: 1px dashed rgba(90,65,54,0.3);">
      <span class="material-symbols-outlined text-4xl text-on-surface/20 group-hover:text-primary mb-2"
            style="font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24">add_box</span>
      <span class="font-label text-xs uppercase tracking-[0.2em] text-on-surface/40 group-hover:text-primary font-bold">
        IMPORT_MODULE
      </span>
    </a>

  </div>

  {#-- System log footer --#}
  <div class="mt-6 bg-surface-container-lowest p-4 font-label text-[10px] flex-shrink-0"
       style="border: 1px solid rgba(90,65,54,0.1);">
    <div class="flex justify-between text-primary/40 mb-3 font-bold uppercase tracking-[0.2em]">
      <span>CORE_PROCESS_LOG</span>
      <span>TIME_UTC: <span x-text="new Date().toUTCString().split(' ')[4]">00:00:00</span></span>
    </div>
    <div class="space-y-1 opacity-70">
      <div class="flex gap-4">
        <span class="text-primary">[OK]</span>
        <span class="text-on-surface/40" x-text="new Date(Date.now()-4000).toUTCString().split(' ')[4]">--:--:--</span>
        <span>MD5_CHECKSUM_VERIFIED: CYBERDECK_V1.DB</span>
      </div>
      <div class="flex gap-4">
        <span class="text-primary">[OK]</span>
        <span class="text-on-surface/40" x-text="new Date(Date.now()-6000).toUTCString().split(' ')[4]">--:--:--</span>
        <span>ENCRYPTION_LAYER_RE-LOCKED: SECTOR_G14</span>
      </div>
      <div class="flex gap-4">
        <span class="text-tertiary-container">[INFO]</span>
        <span class="text-on-surface/40" x-text="new Date(Date.now()-9000).toUTCString().split(' ')[4]">--:--:--</span>
        <span>BACKGROUND_SYNC_PENDING: {% if wifi_connected %}QUEUED{% else %}LOW_SIGNAL_DENSITY{% endif %}</span>
      </div>
      <div class="flex gap-4 animate-pulse">
        <span class="text-primary-container">[WARN]</span>
        <span class="text-on-surface/40" x-text="new Date(Date.now()-13000).toUTCString().split(' ')[4]">--:--:--</span>
        <span>LOW_VOLTAGE_DETECTED: AUX_BANK_03</span>
      </div>
    </div>
  </div>

</main>
{% endblock %}
```

- [ ] **Step 2: Rebuild CSS**

```bash
tailwindcss -i app/static/css/input.css -o app/static/css/app.css
```

- [ ] **Step 3: Run all tests**

```bash
uv run pytest -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 4: Start the dev server and open in browser**

```bash
CYBERDECK_DATA_DIR=data uv run uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000` and verify:
- Header matches mockup: orange radar icon, SURVIVAL_DASHBOARD wordmark, search, language dropdown, shutdown
- Card grid renders (empty = just IMPORT_MODULE card)
- System log footer visible at bottom with live UTC time
- 0px corners everywhere
- Orange accent color on hover

- [ ] **Step 5: Commit**

```bash
git add app/templates/home.html app/static/css/app.css
git commit -m "feat: replace bento grid with survivalist card grid + system log footer"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests pass, 0 failures.

- [ ] **Step 2: Verify no references to deleted bento service**

```bash
grep -r "bento" app/ tests/ --include="*.py" --include="*.html"
```

Expected: no output (no references remain).

- [ ] **Step 3: Final commit**

```bash
git add -A
git status
```

If clean (no uncommitted changes), you're done. If there are stray changes, review and commit them:

```bash
git commit -m "chore: remove stray bento references"
```
