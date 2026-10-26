"""
Interactive API documentation and playground endpoint.
"""

from flask import Blueprint, render_template_string

bp = Blueprint("docs", __name__)

DOCS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Saudi Places of Worship — REST API Documentation</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🕌</text></svg>">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: rgba(22, 30, 46, 0.85);
      --border: rgba(255, 255, 255, 0.08);
      --accent: #00ff87;
      --accent-glow: rgba(0, 255, 135, 0.15);
      --blue: #38bdf8;
      --amber: #fbbf24;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --code-bg: #060911;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 32px 20px;
    }
    .container { max-width: 1100px; margin: 0 auto; }
    header {
      border-bottom: 1px solid var(--border);
      padding-bottom: 24px;
      margin-bottom: 32px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
    }
    .brand { display: flex; align-items: center; gap: 14px; }
    .brand-icon { font-size: 38px; }
    h1 { font-size: 26px; font-weight: 700; color: #fff; }
    .subtitle { color: var(--text-muted); font-size: 14px; margin-top: 4px; }
    .header-links a {
      color: var(--accent);
      text-decoration: none;
      font-size: 14px;
      font-weight: 500;
      padding: 8px 16px;
      border: 1px solid rgba(0, 255, 135, 0.3);
      border-radius: 8px;
      transition: all 0.2s;
    }
    .header-links a:hover {
      background: var(--accent-glow);
    }
    .badge {
      display: inline-block;
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 700;
      border-radius: 6px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .badge-get { background: rgba(56, 189, 248, 0.15); color: var(--blue); border: 1px solid rgba(56, 189, 248, 0.3); }
    .badge-post { background: rgba(0, 255, 135, 0.15); color: var(--accent); border: 1px solid rgba(0, 255, 135, 0.3); }
    .badge-delete { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
    
    .grid { display: flex; flex-direction: column; gap: 20px; }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 22px;
      backdrop-filter: blur(12px);
      transition: border-color 0.2s;
    }
    .card:hover { border-color: rgba(255, 255, 255, 0.18); }
    .endpoint-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }
    .endpoint-path {
      font-family: 'JetBrains Mono', monospace;
      font-size: 16px;
      font-weight: 600;
      color: #fff;
    }
    .endpoint-desc { color: var(--text-muted); font-size: 14px; margin-bottom: 14px; }
    .param-table {
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0;
      font-size: 13px;
    }
    .param-table th, .param-table td {
      text-align: left;
      padding: 8px 12px;
      border-bottom: 1px solid var(--border);
    }
    .param-table th { color: var(--text-muted); font-weight: 600; }
    .param-name { font-family: 'JetBrains Mono', monospace; color: var(--blue); }
    .code-block {
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 13px;
      color: #e2e8f0;
      overflow-x: auto;
      margin-top: 10px;
    }
    .btn-try {
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 14px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.2s;
      text-decoration: none;
      display: inline-block;
    }
    .btn-try:hover { background: rgba(255, 255, 255, 0.12); }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="brand">
        <span class="brand-icon">🕌</span>
        <div>
          <h1>Saudi Places of Worship — REST API</h1>
          <p class="subtitle">High-performance spatial search, coverage analysis, and community review API for Saudi OSM places of worship.</p>
        </div>
      </div>
      <div class="header-links">
        <a href="/" target="_blank">← Open Interactive Map</a>
      </div>
    </header>

    <div class="grid">
      <!-- Health -->
      <div class="card">
        <div class="endpoint-header">
          <span class="badge badge-get">GET</span>
          <span class="endpoint-path">/api/health</span>
          <a class="btn-try" href="/api/health" target="_blank">Execute ↗</a>
        </div>
        <p class="endpoint-desc">System health check, server uptime, database status, and record counts.</p>
        <div class="code-block">curl -X GET "https://localhost:8000/api/health"</div>
      </div>

      <!-- Stats -->
      <div class="card">
        <div class="endpoint-header">
          <span class="badge badge-get">GET</span>
          <span class="endpoint-path">/api/stats</span>
          <a class="btn-try" href="/api/stats" target="_blank">Execute ↗</a>
        </div>
        <p class="endpoint-desc">Comprehensive analytics across places of worship, gap cells, quality issues distribution, and review progress.</p>
        <div class="code-block">curl -X GET "https://localhost:8000/api/stats"</div>
      </div>

      <!-- Places List & Search -->
      <div class="card">
        <div class="endpoint-header">
          <span class="badge badge-get">GET</span>
          <span class="endpoint-path">/api/places</span>
          <a class="btn-try" href="/api/places?limit=5" target="_blank">Execute ↗</a>
        </div>
        <p class="endpoint-desc">Query places with spatial bounding box, full-text Arabic search, and quality issue filtering.</p>
        <table class="param-table">
          <thead><tr><th>Parameter</th><th>Type</th><th>Description</th></tr></thead>
          <tbody>
            <tr><td class="param-name">bbox</td><td>string</td><td>Bounding box as <code>minLon,minLat,maxLon,maxLat</code></td></tr>
            <tr><td class="param-name">q</td><td>string</td><td>Full-text search query (Arabic normalized, e.g. الراجحي)</td></tr>
            <tr><td class="param-name">religion</td><td>string</td><td>Filter by religion: <code>muslim</code>, <code>christian</code>, etc.</td></tr>
            <tr><td class="param-name">issue</td><td>string</td><td>Filter by issue ID: <code>qibla_deviation</code>, <code>missing_amenity</code>, <code>stale_data</code>, etc.</td></tr>
            <tr><td class="param-name">limit</td><td>integer</td><td>Max records to return (default: 100, max: 5000)</td></tr>
            <tr><td class="param-name">offset</td><td>integer</td><td>Pagination offset (default: 0)</td></tr>
          </tbody>
        </table>
        <div class="code-block">curl -X GET "https://localhost:8000/api/places?q=الراجحي&limit=10"</div>
      </div>

      <!-- Place Detail -->
      <div class="card">
        <div class="endpoint-header">
          <span class="badge badge-get">GET</span>
          <span class="endpoint-path">/api/places/{osm_type}/{osm_id}</span>
          <a class="btn-try" href="/api/places/way/40589083" target="_blank">Sample ↗</a>
        </div>
        <p class="endpoint-desc">Retrieve single place of worship with footprint geometry, tags, size, ML anomaly score, Qibla deviation, and quality diagnosis.</p>
        <div class="code-block">curl -X GET "https://localhost:8000/api/places/way/40589083"</div>
      </div>

      <!-- Proximity / Nearby -->
      <div class="card">
        <div class="endpoint-header">
          <span class="badge badge-get">GET</span>
          <span class="endpoint-path">/api/places/nearby</span>
          <a class="btn-try" href="/api/places/nearby?lat=24.7136&lon=46.6753&radius_km=3" target="_blank">Execute ↗</a>
        </div>
        <p class="endpoint-desc">Find places of worship within a given radius (km) of coordinates (lat, lon), sorted by proximity.</p>
        <div class="code-block">curl -X GET "https://localhost:8000/api/places/nearby?lat=24.7136&lon=46.6753&radius_km=3"</div>
      </div>

      <!-- Gaps -->
      <div class="card">
        <div class="endpoint-header">
          <span class="badge badge-get">GET</span>
          <span class="endpoint-path">/api/gaps</span>
          <a class="btn-try" href="/api/gaps?limit=10" target="_blank">Execute ↗</a>
        </div>
        <p class="endpoint-desc">Query coverage gap cells (underserved inhabited areas with 0 places of worship) with optional bbox and score thresholds.</p>
        <div class="code-block">curl -X GET "https://localhost:8000/api/gaps?min_score=5.0&limit=50"</div>
      </div>

      <!-- Reviews -->
      <div class="card">
        <div class="endpoint-header">
          <span class="badge badge-get">GET</span>
          <span class="badge badge-post">POST</span>
          <span class="badge badge-delete">DELETE</span>
          <span class="endpoint-path">/api/reviews</span>
          <a class="btn-try" href="/api/reviews" target="_blank">List Reviews ↗</a>
        </div>
        <p class="endpoint-desc">Persistent review marks management (fixed, skipped, needs_work), syncing, and community statistics.</p>
        <div class="code-block"># Mark place as fixed
curl -X POST "https://localhost:8000/api/reviews" \\
  -H "Content-Type: application/json" \\
  -d '{"osm_type":"way","osm_id":40589083,"status":"fixed","user_name":"Abdullah"}'</div>
      </div>

      <!-- Notes -->
      <div class="card">
        <div class="endpoint-header">
          <span class="badge badge-get">GET</span>
          <span class="badge badge-post">POST</span>
          <span class="endpoint-path">/api/notes/{osm_type}/{osm_id}</span>
        </div>
        <p class="endpoint-desc">Community mapper field notes and discussions for a specific place of worship.</p>
        <div class="code-block">curl -X POST "https://localhost:8000/api/notes" \\
  -H "Content-Type: application/json" \\
  -d '{"osm_type":"way","osm_id":40589083,"user_name":"Mapper1","content":"Checked satellite; building outline matches well."}'</div>
      </div>

      <!-- Export -->
      <div class="card">
        <div class="endpoint-header">
          <span class="badge badge-get">GET</span>
          <span class="endpoint-path">/api/export/{format}</span>
          <a class="btn-try" href="/api/export/csv?limit=20" target="_blank">Export CSV ↗</a>
        </div>
        <p class="endpoint-desc">Dynamic server-side export. Supported formats: <code>csv</code> (with UTF-8 BOM), <code>geojson</code>, <code>maproulette</code>.</p>
        <div class="code-block">curl -X GET "https://localhost:8000/api/export/csv?issue=qibla_deviation" -o qibla_issues.csv</div>
      </div>

      <!-- Pipeline Status -->
      <div class="card">
        <div class="endpoint-header">
          <span class="badge badge-get">GET</span>
          <span class="badge badge-post">POST</span>
          <span class="endpoint-path">/api/pipeline/status</span>
          <a class="btn-try" href="/api/pipeline/status" target="_blank">Check Pipeline ↗</a>
        </div>
        <p class="endpoint-desc">Pipeline health, dataset file sizes, git commit info, and trigger data validation.</p>
        <div class="code-block">curl -X POST "https://localhost:8000/api/pipeline/validate"</div>
      </div>
    </div>
  </div>
</body>
</html>
"""


@bp.route("/api/docs", methods=["GET"])
def api_docs():
    return render_template_string(DOCS_HTML)
