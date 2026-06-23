#!/usr/bin/env python3
"""
Fetches MGO dashboard data from Google Sheets and injects it into index.html.

Reads:
  [INSTAGRAM] Feed     → IG_POSTS  (summary + top 4 per month)
  [INSTAGRAM] Stories  → IG_STORIES (monthly aggregates)
  LinkedIn métricas    → LI.monthly: imp, cli, rea, com
  LinkedIn page views  → LI.monthly: vis
  LinkedIn seguidores  → LI.monthly: seg
  LinkedIn concorrentes→ competitor-wrap HTML block
"""

import os, json, re, tempfile
from datetime import datetime
from calendar import monthrange

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    os.system("pip install gspread google-auth --quiet")
    import gspread
    from google.oauth2.service_account import Credentials

SHEET_ID = os.environ.get("SHEET_ID", "1ZnaZdi7RjCCogSV6eswra2MK8ZfAgWQD5hf0j-i5Npg")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

PT_MONTHS = {1:"Janeiro",2:"Fevereiro",3:"Março",4:"Abril",5:"Maio",6:"Junho",
             7:"Julho",8:"Agosto",9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"}
PT_SHORT  = {1:"Jan",2:"Fev",3:"Mar",4:"Abr",5:"Mai",6:"Jun",
             7:"Jul",8:"Ago",9:"Set",10:"Out",11:"Nov",12:"Dez"}


# ── helpers ──────────────────────────────────────────────────────────────────

def parse_date(val):
    if not val or str(val).strip() in ("", "Total"):
        return None
    val = str(val).strip()
    for fmt in ("%m/%d/%Y %H:%M", "%m/%d/%Y", "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def parse_num(val):
    if val is None:
        return 0
    s = re.sub(r"[^\d]", "", str(val).strip())
    return int(s) if s else 0


def normalize_tipo(raw):
    raw = str(raw).strip()
    if "Reel" in raw or "Vídeo" in raw or "Video" in raw:
        return "Reel"
    if "Carrossel" in raw or "Carousel" in raw:
        return "Carrossel"
    return "Imagem"


def rows_to_dicts(ws):
    rows = ws.get_all_values()
    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]
    result = []
    for row in rows[1:]:
        padded = row + [""] * (len(headers) - len(row))
        result.append(dict(zip(headers, padded)))
    return result


def find_ws(worksheets, *keywords):
    """Find first worksheet whose header row contains ALL keywords."""
    for ws in worksheets:
        try:
            header = " ".join(ws.row_values(1))
            if all(kw in header for kw in keywords):
                return ws
        except Exception:
            pass
    return None


def month_key(date_str):
    return date_str[:7] if date_str else None


def month_range_str(year, month):
    last = monthrange(year, month)[1]
    return f"01/{month:02d} — {last:02d}/{month:02d}"


def fmt_br(n):
    return f"{n:,}".replace(",", ".")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    # Auth
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(creds_json)
            creds_file = f.name
    else:
        creds_file = "credentials.json"

    creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    wss = sh.worksheets()
    print(f"Sheets: {[w.title for w in wss]}")

    # ── [INSTAGRAM] FEED ─────────────────────────────────────────────────────
    # Identify by: has "Tipo de post" + "Alcance" but NOT "Toques em figurinhas"
    ws_feed = None
    for ws in wss:
        try:
            h = " ".join(ws.row_values(1))
            if "Tipo de post" in h and "Alcance" in h and "Toques em figurinhas" not in h:
                ws_feed = ws
                break
        except Exception:
            pass

    if not ws_feed:
        raise RuntimeError("Instagram Feed sheet not found")
    print(f"  Feed: {ws_feed.title}")

    posts_by_month = {}
    for r in rows_to_dicts(ws_feed):
        # Only aggregate rows (Data == "Total"), skip stories
        if r.get("Data", "").strip() != "Total":
            continue
        tipo_raw = r.get("Tipo de post", "")
        if "Story" in tipo_raw:
            continue
        date_str = parse_date(r.get("Horário de publicação", ""))
        if not date_str:
            continue
        mk = month_key(date_str)
        post = {
            "tipo": normalize_tipo(tipo_raw),
            "date": datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y"),
            "views": parse_num(r.get("Visualizações", 0)),
            "curtidas": parse_num(r.get("Curtidas", 0)),
            "comentarios": parse_num(r.get("Comentários", 0)),
            "compartilhamentos": parse_num(r.get("Compartilhamentos", 0)),
            "salvamentos": parse_num(r.get("Salvamentos", 0)),
            "alcance": parse_num(r.get("Alcance", 0)),
            "desc": str(r.get("Descrição", "")).strip()[:120],
            "link": str(r.get("Link permanente", "")).strip(),
        }
        posts_by_month.setdefault(mk, []).append(post)

    for mk in posts_by_month:
        posts_by_month[mk].sort(key=lambda p: p["views"], reverse=True)

    ig_posts = {}
    for mk, posts in posts_by_month.items():
        ig_posts[mk] = {
            "summary": {
                "total": len(posts),
                "views": sum(p["views"] for p in posts),
                "curtidas": sum(p["curtidas"] for p in posts),
                "comentarios": sum(p["comentarios"] for p in posts),
                "salvamentos": sum(p["salvamentos"] for p in posts),
                "compartilhamentos": sum(p["compartilhamentos"] for p in posts),
                "alcance": sum(p["alcance"] for p in posts),
                "reels": sum(1 for p in posts if p["tipo"] == "Reel"),
                "carrosseis": sum(1 for p in posts if p["tipo"] == "Carrossel"),
                "imagens": sum(1 for p in posts if p["tipo"] == "Imagem"),
            },
            "top": posts[:4],
        }

    # ── [INSTAGRAM] STORIES ──────────────────────────────────────────────────
    ws_stories = find_ws(wss, "Toques em figurinhas")
    if not ws_stories:
        raise RuntimeError("Instagram Stories sheet not found")
    print(f"  Stories: {ws_stories.title}")

    ig_stories = {}
    for r in rows_to_dicts(ws_stories):
        if r.get("Data", "").strip() != "Total":
            continue
        date_str = parse_date(r.get("Horário de publicação", ""))
        if not date_str:
            continue
        mk = month_key(date_str)
        s = ig_stories.setdefault(mk, {
            "total": 0, "views": 0, "reach": 0,
            "curtidas": 0, "compartilhamentos": 0, "respostas": 0, "visitas": 0,
        })
        s["total"]            += 1
        s["views"]            += parse_num(r.get("Visualizações", 0))
        s["reach"]            += parse_num(r.get("Alcance", 0))
        s["curtidas"]         += parse_num(r.get("Curtidas", 0))
        s["compartilhamentos"]+= parse_num(r.get("Compartilhamentos", 0))
        s["respostas"]        += parse_num(r.get("Respostas", 0))
        s["visitas"]          += parse_num(r.get("Visitas ao perfil", 0))

    # ── LINKEDIN MÉTRICAS DIÁRIAS ─────────────────────────────────────────────
    ws_li_m = find_ws(wss, "Impressões (total)", "Reações (total)")
    if not ws_li_m:
        raise RuntimeError("LinkedIn metrics sheet not found")
    print(f"  LI métricas: {ws_li_m.title}")

    li_m = {}
    for r in rows_to_dicts(ws_li_m):
        date_str = parse_date(r.get("Data", ""))
        if not date_str:
            continue
        mk = month_key(date_str)
        d = li_m.setdefault(mk, {"imp": 0, "cli": 0, "rea": 0, "com": 0})
        d["imp"] += parse_num(r.get("Impressões (total)", 0))
        d["cli"] += parse_num(r.get("Cliques (total)", 0))
        d["rea"] += parse_num(r.get("Reações (total)", 0))
        d["com"] += parse_num(r.get("Comentários (total)", 0))

    # ── LINKEDIN PAGE VIEWS ───────────────────────────────────────────────────
    ws_li_v = find_ws(wss, "Total de visitantes únicos (total)")
    if not ws_li_v:
        raise RuntimeError("LinkedIn page views sheet not found")
    print(f"  LI page views: {ws_li_v.title}")

    li_vis = {}
    for r in rows_to_dicts(ws_li_v):
        date_str = parse_date(r.get("Data", ""))
        if not date_str:
            continue
        mk = month_key(date_str)
        li_vis[mk] = li_vis.get(mk, 0) + parse_num(r.get("Total de visitantes únicos (total)", 0))

    # ── LINKEDIN SEGUIDORES ───────────────────────────────────────────────────
    ws_li_f = find_ws(wss, "Seguidores orgânicos", "Seguidores patrocinados")
    if not ws_li_f:
        raise RuntimeError("LinkedIn followers sheet not found")
    print(f"  LI seguidores: {ws_li_f.title}")

    li_seg = {}
    for r in rows_to_dicts(ws_li_f):
        date_str = parse_date(r.get("Data", ""))
        if not date_str:
            continue
        mk = month_key(date_str)
        new_f = parse_num(r.get("Seguidores orgânicos", 0)) + parse_num(r.get("Seguidores patrocinados", 0))
        li_seg[mk] = li_seg.get(mk, 0) + new_f

    # ── LINKEDIN CONCORRENTES ─────────────────────────────────────────────────
    ws_comp = find_ws(wss, "Page", "Total de seguidores", "Novos seguidores")
    competitors = []
    if ws_comp:
        print(f"  LI concorrentes: {ws_comp.title}")
        for r in rows_to_dicts(ws_comp):
            page = str(r.get("Page", "")).strip()
            if not page:
                continue
            competitors.append({
                "name": page,
                "seg": parse_num(r.get("Total de seguidores", 0)),
                "novos": parse_num(r.get("Novos seguidores", 0)),
                "eng": parse_num(r.get("Total de engajamentos", 0) or r.get("Engajamentos", 0)),
                "pub": parse_num(r.get("Total de publicações", 0) or r.get("Publicações", 0)),
            })

    # ── ASSEMBLE LI.monthly ───────────────────────────────────────────────────
    all_li_months = sorted(set(list(li_m) + list(li_vis) + list(li_seg)))
    li_monthly = {}
    for mk in all_li_months:
        m = li_m.get(mk, {})
        li_monthly[mk] = {
            "imp": m.get("imp", 0),
            "cli": m.get("cli", 0),
            "rea": m.get("rea", 0),
            "com": m.get("com", 0),
            "seg": li_seg.get(mk, 0),
            "vis": li_vis.get(mk, 0),
        }

    # ── AUXILIARY MAPS ────────────────────────────────────────────────────────
    all_months = sorted(set(list(ig_posts) + list(ig_stories) + list(li_monthly)))
    labels, ranges, mnames, prev = {}, {}, {}, {}
    for i, mk in enumerate(all_months):
        y, m = int(mk[:4]), int(mk[5:7])
        labels[mk] = f"{PT_MONTHS[m]} {y}"
        ranges[mk] = month_range_str(y, m)
        mnames[mk] = PT_SHORT[m]
        prev[mk]   = all_months[i - 1] if i > 0 else None

    latest = all_months[-1] if all_months else ""

    # ── INJECT INTO index.html ────────────────────────────────────────────────
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    J = lambda obj: json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    # Preserve existing LI.posts (manually maintained)
    li_posts_match = re.search(r'posts:\{(.*?)\}\s*\};\s*\nconst IG_POSTS', html, re.DOTALL)
    li_posts_raw = "{" + li_posts_match.group(1) + "}" if li_posts_match else "{}"

    data_block = (
        "// ── DATA ──\n"
        f"const LI={{monthly:{J(li_monthly)},posts:{li_posts_raw}}};\n\n"
        f"const IG_POSTS={J(ig_posts)};\n"
        f"const IG_STORIES={J(ig_stories)};\n\n"
        f"const LABELS={J(labels)};\n"
        f"const RANGES={J(ranges)};\n"
        f"const PREV={J(prev)};\n"
        f"const MONTHS={J(all_months)};\n"
        f"const MNAMES={J(mnames)};"
    )

    html = re.sub(
        r"// ── DATA ──.*?(?=\nlet cur=)",
        data_block,
        html,
        flags=re.DOTALL,
    )

    if latest:
        html = re.sub(r'let cur="[^"]*"', f'let cur="{latest}"', html)

    # ── UPDATE COMPETITOR CARDS ───────────────────────────────────────────────
    if competitors:
        def build_card(c):
            is_mgo = "MGO" in c["name"].upper()
            cls = 'comp-card mgo' if is_mgo else 'comp-card'
            return (
                f'    <div class="{cls}">\n'
                f'      <div class="comp-name">{c["name"]}</div>\n'
                f'      <div class="comp-metric"><div class="comp-val">{fmt_br(c["seg"])}</div><div class="comp-lbl">Seguidores totais</div></div>\n'
                f'      <div class="comp-metric"><div class="comp-val">{fmt_br(c["novos"])}</div><div class="comp-lbl">Novos seguidores</div></div>\n'
                f'      <div class="comp-metric"><div class="comp-val">{fmt_br(c["eng"])}</div><div class="comp-lbl">Engajamentos</div></div>\n'
                f'      <div class="comp-metric"><div class="comp-val">{fmt_br(c["pub"])}</div><div class="comp-lbl">Publicações</div></div>\n'
                f'    </div>'
            )

        cards_html = "\n".join(build_card(c) for c in competitors)
        html = re.sub(
            r'(<div class="competitor-wrap">).*?(</div>\s*\n\s*<div style="background:rgba)',
            lambda m: m.group(1) + "\n" + cards_html + "\n  " + m.group(2),
            html,
            flags=re.DOTALL,
        )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    ig_total = sum(v["summary"]["total"] for v in ig_posts.values())
    st_total = sum(v["total"] for v in ig_stories.values())
    print(f"\n✓ index.html atualizado")
    print(f"  IG Feed:     {ig_total} posts em {len(ig_posts)} meses")
    print(f"  IG Stories:  {st_total} stories em {len(ig_stories)} meses")
    print(f"  LI Monthly:  {len(li_monthly)} meses")
    print(f"  Concorrentes:{len(competitors)} empresas")
    print(f"  Mês atual:   {latest}")
    print(f"  Atualizado:  {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}")


if __name__ == "__main__":
    main()
