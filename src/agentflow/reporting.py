"""Local, self-contained HTML index for a completed analysis directory."""

import base64
from html import escape

from .theme import ASSETS, BERRY, BG, INK, SOFT


def write_report(folder, recipe, table, inputs):
    title = recipe.get("experiment", {}).get("label", "Flow analysis — review gates")
    pending = "".join(
        f"<li>{escape(p['label'])}: {escape(p['reason'])}</li>" for p in recipe.get("pending_gates", [])
    )
    sections = []
    for i, item in enumerate(inputs, 1):
        quality = item["quality"]
        messages = []
        if quality["identity_compensation"]:
            messages.append("Embedded/supplied matrix is identity: no spillover correction was applied.")
        if quality["uncompensated"]:
            messages.append("Uncompensated: no spillover correction.")
        if quality["time_nonmonotonic"]:
            messages.append("Acquisition time is nonmonotonic; inspect time QC.")
        for q in quality["upper_range_events"]:
            if q["percent"] >= 0.1:
                messages.append(
                    f"{q['detector']}: {q['at_upper_range']} events ({q['percent']:.2f}%) at/above detector upper range."
                )
        sections.append(
            f"<section><h2>{escape(item['sample_id'])}</h2><p>{escape(' '.join(messages))}</p>"
            f"<img src='gates-{i:04d}.png' alt='Gate review for {escape(item['sample_id'], quote=True)}'>"
            + (
                f"<img src='time-{i:04d}.png' alt='Acquisition time QC'>"
                if (folder / f"time-{i:04d}.png").exists()
                else ""
            )
            + "</section>"
        )
    fonts = "".join(
        f"@font-face{{font-family:'{family}';src:url(data:font/ttf;base64,"
        + base64.b64encode((ASSETS / file).read_bytes()).decode()
        + ") format('truetype');}"
        for family, file in [("Manrope", "Manrope.ttf"), ("Playfair Display", "PlayfairDisplay.ttf")]
    )
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>{escape(title)}</title>
<style>{fonts}body{{font:15px Manrope,sans-serif;background:{BG};margin:32px auto;max-width:1200px;color:{INK};padding:0 24px}}h1,h2{{font-family:"Playfair Display",serif;font-weight:500}}h1{{font-size:32px;color:{BERRY}}}.notice{{background:{SOFT};padding:18px;border-left:5px solid {BERRY}}}img{{max-width:100%}}.table{{overflow:auto}}table{{border-collapse:collapse;font-size:13px}}td,th{{padding:8px;border-bottom:1px solid #ddd}}a{{color:{BERRY}}}section{{margin-top:32px}}</style></head>
<body><h1>{escape(title)}</h1><p class='notice'>Draft gates are drawing aids, not biologically validated populations. Counts use all events. Fluorescence medians precede display transformations. Missing gates below were not evaluated.</p>
<h2>Unavailable / unmapped gates</h2><ul>{pending or "<li>None</li>"}</ul>
<p>Compensation mode: <strong>{escape(recipe["compensation"]["mode"])}</strong>. <a href='recipe.json'>Recipe</a> · <a href='summary.csv'>Results CSV</a> · <a href='run.json'>Run provenance</a></p>
<div class='table'>{table.to_html(index=False, escape=True, float_format=lambda x: f"{x:.4g}")}</div>{"".join(sections)}</body></html>"""
    (folder / "report.html").write_text(html)
