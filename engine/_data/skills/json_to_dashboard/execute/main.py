"""JSON 메트릭 데이터를 HTML 대시보드로 변환한다."""

import json
import sys


THEMES = {
    "blue": {
        "bg": "#f0f4ff",
        "card_bg": "white",
        "accent": "#3b82f6",
        "header_bg": "#1e40af",
        "header_text": "white",
        "text": "#1e293b",
        "subtext": "#64748b",
        "change_positive": "#10b981",
        "change_negative": "#ef4444",
    },
    "green": {
        "bg": "#f0fdf4",
        "card_bg": "white",
        "accent": "#10b981",
        "header_bg": "#065f46",
        "header_text": "white",
        "text": "#1e293b",
        "subtext": "#64748b",
        "change_positive": "#10b981",
        "change_negative": "#ef4444",
    },
    "purple": {
        "bg": "#faf5ff",
        "card_bg": "white",
        "accent": "#8b5cf6",
        "header_bg": "#4c1d95",
        "header_text": "white",
        "text": "#1e293b",
        "subtext": "#64748b",
        "change_positive": "#10b981",
        "change_negative": "#ef4444",
    },
    "dark": {
        "bg": "#0f172a",
        "card_bg": "#1e293b",
        "accent": "#38bdf8",
        "header_bg": "#020617",
        "header_text": "#f1f5f9",
        "text": "#f1f5f9",
        "subtext": "#94a3b8",
        "change_positive": "#34d399",
        "change_negative": "#f87171",
    },
}


def build_metric_cards(metrics: list, theme: dict) -> str:
    """메트릭 카드 HTML을 생성한다."""
    cards = []
    for metric in metrics:
        label = metric.get("label", "")
        value = metric.get("value", "")
        change = metric.get("change", "")

        change_html = ""
        if change:
            is_positive = not change.startswith("-")
            color = theme["change_positive"] if is_positive else theme["change_negative"]
            arrow = "&#8593;" if is_positive else "&#8595;"
            change_html = (
                f'<span style="color:{color};font-size:0.85rem;font-weight:600;">'
                f'{arrow} {change}</span>'
            )

        cards.append(f"""
    <div style="background:{theme['card_bg']};border-radius:12px;padding:20px;
                box-shadow:0 1px 8px rgba(0,0,0,0.08);">
      <div style="color:{theme['subtext']};font-size:0.85rem;margin-bottom:8px;">{label}</div>
      <div style="color:{theme['text']};font-size:1.8rem;font-weight:700;margin-bottom:4px;">{value}</div>
      {change_html}
    </div>""")
    return "\n".join(cards)


def build_chart_section(chart_data: dict | None, theme: dict) -> str:
    """차트 섹션 HTML을 생성한다."""
    if not chart_data:
        return ""

    chart_type = chart_data.get("type", "bar")
    labels = chart_data.get("labels", [])
    datasets = chart_data.get("datasets", [])

    if not labels or not datasets:
        return ""

    datasets_json = json.dumps(datasets, ensure_ascii=False)
    labels_json = json.dumps(labels, ensure_ascii=False)

    return f"""
  <div style="background:{theme['card_bg']};border-radius:12px;padding:24px;margin-top:20px;
              box-shadow:0 1px 8px rgba(0,0,0,0.08);">
    <div style="position:relative;height:300px;">
      <canvas id="dashChart"></canvas>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script>
    const ctx = document.getElementById('dashChart').getContext('2d');
    new Chart(ctx, {{
      type: '{chart_type}',
      data: {{
        labels: {labels_json},
        datasets: {datasets_json}
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ position: 'top' }} }},
        scales: {{'y': {{'beginAtZero': true}}}}
      }}
    }});
  </script>"""


def run(input_data: dict) -> dict:
    """JSON 데이터를 HTML 대시보드로 변환한다.

    Args:
        input_data: title, metrics, chart, theme

    Returns:
        html, metric_count
    """
    title = input_data.get("title", "Dashboard")
    metrics = input_data.get("metrics", [])
    chart_data = input_data.get("chart")
    theme_name = input_data.get("theme", "blue")

    theme = THEMES.get(theme_name, THEMES["blue"])

    metric_cards = build_metric_cards(metrics, theme)
    chart_section = build_chart_section(chart_data, theme)

    grid_cols = min(len(metrics), 4) if metrics else 1

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: {theme['bg']};
      min-height: 100vh;
    }}
    .header {{
      background: {theme['header_bg']};
      color: {theme['header_text']};
      padding: 20px 32px;
      font-size: 1.3rem;
      font-weight: 700;
    }}
    .content {{ padding: 24px 32px; }}
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat({grid_cols}, 1fr);
      gap: 16px;
    }}
    @media (max-width: 768px) {{
      .metrics-grid {{ grid-template-columns: repeat(2, 1fr); }}
    }}
    @media (max-width: 480px) {{
      .metrics-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="header">{title}</div>
  <div class="content">
    <div class="metrics-grid">
      {metric_cards}
    </div>
    {chart_section}
  </div>
</body>
</html>"""

    return {
        "html": html,
        "metric_count": len(metrics),
    }


if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    result = run(input_data)
    print(json.dumps(result, ensure_ascii=False))
