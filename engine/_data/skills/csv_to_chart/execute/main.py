"""CSV 데이터를 Chart.js HTML 차트로 변환한다."""

import csv
import io
import json
import sys


DEFAULT_COLORS = [
    "rgba(54, 162, 235, 0.8)",
    "rgba(255, 99, 132, 0.8)",
    "rgba(75, 192, 192, 0.8)",
    "rgba(255, 205, 86, 0.8)",
    "rgba(153, 102, 255, 0.8)",
    "rgba(255, 159, 64, 0.8)",
]


def parse_csv(csv_data: str) -> tuple[list[str], list[str], list[list[str]]]:
    """CSV 문자열을 헤더, 레이블, 데이터 행으로 파싱한다."""
    reader = csv.reader(io.StringIO(csv_data.strip()))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return [], [], []
    headers = [h.strip() for h in rows[0]]
    labels = [row[0].strip() for row in rows[1:] if row]
    data_rows = [row[1:] for row in rows[1:] if row]
    return headers, labels, data_rows


def build_datasets(
    headers: list[str],
    data_rows: list[list[str]],
    colors: list[str],
) -> list[dict]:
    """Chart.js datasets 배열을 만든다."""
    if not headers or not data_rows:
        return []
    dataset_count = len(headers) - 1
    datasets = []
    for i in range(dataset_count):
        color = colors[i % len(colors)] if colors else DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
        values = []
        for row in data_rows:
            if i < len(row):
                try:
                    values.append(float(row[i].strip()))
                except (ValueError, AttributeError):
                    values.append(0)
            else:
                values.append(0)
        datasets.append({
            "label": headers[i + 1] if i + 1 < len(headers) else f"Series {i + 1}",
            "data": values,
            "backgroundColor": color,
            "borderColor": color.replace("0.8", "1.0"),
            "borderWidth": 2,
        })
    return datasets


def build_html(
    title: str,
    chart_type: str,
    labels: list[str],
    datasets: list[dict],
) -> str:
    """Chart.js HTML 페이지를 생성한다."""
    datasets_json = json.dumps(datasets, ensure_ascii=False)
    labels_json = json.dumps(labels, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      margin: 0; padding: 20px;
      background: #f8f9fa;
    }}
    .container {{
      max-width: 900px;
      margin: 0 auto;
      background: white;
      border-radius: 12px;
      padding: 24px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.1);
    }}
    h1 {{
      margin: 0 0 20px;
      color: #1a1a2e;
      font-size: 1.5rem;
    }}
    .chart-wrapper {{
      position: relative;
      height: 400px;
    }}
  </style>
</head>
<body>
  <div class="container">
    <h1>{title}</h1>
    <div class="chart-wrapper">
      <canvas id="myChart"></canvas>
    </div>
  </div>
  <script>
    const ctx = document.getElementById('myChart').getContext('2d');
    new Chart(ctx, {{
      type: '{chart_type}',
      data: {{
        labels: {labels_json},
        datasets: {datasets_json}
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'top' }},
          title: {{ display: false }}
        }},
        scales: {{'y': {{'beginAtZero': true}}}}
      }}
    }});
  </script>
</body>
</html>"""


def run(input_data: dict) -> dict:
    """CSV 데이터를 Chart.js HTML 차트로 변환한다.

    Args:
        input_data: csv_data, chart_type, title, colors

    Returns:
        html, labels, row_count
    """
    csv_data = input_data.get("csv_data", "")
    chart_type = input_data.get("chart_type", "bar")
    title = input_data.get("title", "Chart")
    colors = input_data.get("colors", DEFAULT_COLORS)

    if chart_type not in ("bar", "line", "pie", "doughnut"):
        chart_type = "bar"

    headers, labels, data_rows = parse_csv(csv_data)
    datasets = build_datasets(headers, data_rows, colors)
    html = build_html(title, chart_type, labels, datasets)

    return {
        "html": html,
        "labels": labels,
        "row_count": len(data_rows),
    }


if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    result = run(input_data)
    print(json.dumps(result, ensure_ascii=False))
