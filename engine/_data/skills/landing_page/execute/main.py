"""제품 정보를 Tailwind CSS 기반 랜딩 페이지 HTML로 변환한다."""

import json
import sys


COLOR_PALETTES = {
    "blue": {
        "primary": "#3b82f6",
        "primary_dark": "#1d4ed8",
        "primary_light": "#eff6ff",
        "gradient_from": "#1e40af",
        "gradient_to": "#3b82f6",
    },
    "green": {
        "primary": "#10b981",
        "primary_dark": "#065f46",
        "primary_light": "#ecfdf5",
        "gradient_from": "#065f46",
        "gradient_to": "#10b981",
    },
    "purple": {
        "primary": "#8b5cf6",
        "primary_dark": "#4c1d95",
        "primary_light": "#f5f3ff",
        "gradient_from": "#4c1d95",
        "gradient_to": "#8b5cf6",
    },
    "orange": {
        "primary": "#f97316",
        "primary_dark": "#c2410c",
        "primary_light": "#fff7ed",
        "gradient_from": "#c2410c",
        "gradient_to": "#f97316",
    },
    "red": {
        "primary": "#ef4444",
        "primary_dark": "#991b1b",
        "primary_light": "#fef2f2",
        "gradient_from": "#991b1b",
        "gradient_to": "#ef4444",
    },
}

FEATURE_ICONS = ["&#9654;", "&#9733;", "&#9632;", "&#9650;", "&#9679;", "&#9658;"]


def build_features_section(features: list, palette: dict) -> str:
    """기능 카드 섹션 HTML을 생성한다."""
    if not features:
        return ""

    cards = []
    for i, feat in enumerate(features):
        icon = FEATURE_ICONS[i % len(FEATURE_ICONS)]
        title = feat.get("title", "")
        desc = feat.get("description", "")
        cards.append(f"""
      <div style="background:white;border-radius:12px;padding:24px;
                  box-shadow:0 2px 12px rgba(0,0,0,0.08);border-top:3px solid {palette['primary']};">
        <div style="font-size:1.5rem;margin-bottom:12px;color:{palette['primary']};">{icon}</div>
        <h3 style="font-size:1.1rem;font-weight:700;margin-bottom:8px;color:#1e293b;">{title}</h3>
        <p style="color:#64748b;line-height:1.6;">{desc}</p>
      </div>""")

    cols = min(len(features), 3)
    return f"""
  <section style="padding:64px 32px;background:#f8fafc;">
    <div style="max-width:1100px;margin:0 auto;">
      <h2 style="text-align:center;font-size:1.8rem;font-weight:800;
                 color:#1e293b;margin-bottom:40px;">주요 기능</h2>
      <div style="display:grid;grid-template-columns:repeat({cols},1fr);gap:24px;">
        {"".join(cards)}
      </div>
    </div>
  </section>"""


def run(input_data: dict) -> dict:
    """제품 정보를 랜딩 페이지 HTML로 변환한다.

    Args:
        input_data: product_name, tagline, description, features, cta_text, color

    Returns:
        html
    """
    product_name = input_data.get("product_name", "Product")
    tagline = input_data.get("tagline", "Your tagline here")
    description = input_data.get("description", "")
    features = input_data.get("features", [])
    cta_text = input_data.get("cta_text", "시작하기")
    color = input_data.get("color", "blue")

    palette = COLOR_PALETTES.get(color, COLOR_PALETTES["blue"])
    features_section = build_features_section(features, palette)

    desc_html = (
        f'<p style="font-size:1.15rem;color:rgba(255,255,255,0.85);'
        f'max-width:600px;margin:0 auto 32px;line-height:1.7;">{description}</p>'
        if description else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{product_name}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #1e293b;
    }}
    a {{ text-decoration: none; }}
    nav {{
      position: fixed; top: 0; left: 0; right: 0;
      background: rgba(255,255,255,0.95);
      backdrop-filter: blur(8px);
      padding: 16px 32px;
      display: flex; justify-content: space-between; align-items: center;
      box-shadow: 0 1px 8px rgba(0,0,0,0.08);
      z-index: 100;
    }}
    .nav-brand {{
      font-size: 1.2rem; font-weight: 800;
      color: {palette['primary']};
    }}
    .btn-primary {{
      background: {palette['primary']};
      color: white;
      padding: 10px 24px;
      border-radius: 8px;
      font-weight: 600;
      font-size: 0.95rem;
      border: none;
      cursor: pointer;
      transition: background 0.2s;
    }}
    .btn-primary:hover {{ background: {palette['primary_dark']}; }}
    .hero {{
      background: linear-gradient(135deg, {palette['gradient_from']}, {palette['gradient_to']});
      min-height: 100vh;
      display: flex; align-items: center; justify-content: center;
      text-align: center;
      padding: 120px 32px 80px;
    }}
    footer {{
      background: #0f172a;
      color: #94a3b8;
      text-align: center;
      padding: 32px;
      font-size: 0.9rem;
    }}
    @media (max-width: 768px) {{
      .hero h1 {{ font-size: 2rem !important; }}
    }}
  </style>
</head>
<body>
  <nav>
    <div class="nav-brand">{product_name}</div>
    <button class="btn-primary">{cta_text}</button>
  </nav>

  <section class="hero">
    <div>
      <h1 style="font-size:3rem;font-weight:900;color:white;
                 margin-bottom:20px;line-height:1.2;">{tagline}</h1>
      {desc_html}
      <button class="btn-primary" style="font-size:1.1rem;padding:14px 36px;">
        {cta_text} &rarr;
      </button>
    </div>
  </section>

  {features_section}

  <footer>
    <p style="margin-bottom:8px;font-weight:600;color:#e2e8f0;">{product_name}</p>
    <p>&copy; 2026 {product_name}. All rights reserved.</p>
  </footer>
</body>
</html>"""

    return {"html": html}


if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    result = run(input_data)
    print(json.dumps(result, ensure_ascii=False))
