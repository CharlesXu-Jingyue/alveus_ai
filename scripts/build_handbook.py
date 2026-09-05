#!/usr/bin/env python
"""Render docs/*.md into a single self-contained docs/handbook.html.

Works offline from file:// (no CDN scripts; fonts fall back to system faces when offline).
Usage: python scripts/build_handbook.py [--out PATH]
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

try:
    import markdown
except ImportError:  # pragma: no cover
    sys.exit("pip install markdown   (or: pip install -e '.[dev]')")

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
ORDER = [
    ("README", "Start here", "readme", "Orientation"),
    ("overview", "Overview", "overview", "Orientation"),
    ("architecture", "Architecture", "architecture", "Orientation"),
    ("installation", "Installation", "installation", "Set up"),
    ("configuration", "Configuration", "configuration", "Set up"),
    ("usage", "Usage", "usage", "Use"),
    ("tools", "Tools (MCP)", "tools", "Use"),
    ("backends", "Backends", "backends", "Use"),
    ("api", "GUI & HTTP API", "api", "Use"),
    ("wake-words", "Wake words", "wake-words", "Use"),
    ("troubleshooting", "Troubleshooting", "troubleshooting", "Maintain"),
    ("development", "Development", "development", "Maintain"),
]
SLUGS = {f.lower(): s for f, _, s, _ in ORDER}
LINK_RE = re.compile(r'href="([a-zA-Z0-9-]+)\.md(#[^"]*)?"')


def render(md_text: str) -> tuple[str, list[dict]]:
    mk = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"],
                           extension_configs={"toc": {"toc_depth": "2-3", "permalink": False}})
    body = mk.convert(md_text)
    heads = [{"id": t["id"], "text": t["name"], "level": t["level"]} for t in _flatten(mk.toc_tokens)]
    body = LINK_RE.sub(lambda m: f'href="#{SLUGS.get(m.group(1).lower(), m.group(1).lower())}'
                                 f'{("/" + m.group(2)[1:]) if m.group(2) else ""}"', body)
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    body = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', body)
    return body, heads


def _flatten(tokens):
    for t in tokens:
        yield t
        yield from _flatten(t.get("children", []))


def build(out: Path) -> None:
    docs = []
    for fname, title, slug, group in ORDER:
        text = (DOCS / f"{fname}.md").read_text()
        if fname == "README":
            text = text.replace("# Alveus documentation", "# Start here")
        body, heads = render(text)
        docs.append({"slug": slug, "title": title, "group": group, "html": body, "headings": heads,
                     "source": f"docs/{fname}.md"})
    payload = json.dumps(docs, ensure_ascii=False).replace("</", "<\\/")
    stamp = dt.date.today().strftime("%B %-d, %Y")
    page = TEMPLATE.replace("__PAYLOAD__", payload).replace("__STAMP__", html.escape(stamp))
    out.write_text(page)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB, {len(docs)} documents)")


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Alveus Handbook</title>
<meta name="description" content="Documentation for Alveus / Aurea, a fully local voice AI assistant.">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,600;12..96,700&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --bg:#F4F6F3; --surface:#FFFFFF; --surface-2:#EAEEEA; --ink:#17232A; --ink-2:#4E5F66; --muted:#7C8B90;
  --rule:#D5DCD8; --rule-2:#C2CBC6; --accent:#0E7C86; --accent-ink:#0A5E66; --accent-soft:#DDF0F1;
  --warm:#B8641F; --code-bg:#EDF1EE; --sel:#CFEAEC; --shadow:0 1px 0 rgba(23,35,42,.06);
  --nav-w:236px; --toc-w:200px;
}
@media (prefers-color-scheme: dark){ :root{
  --bg:#0F1518; --surface:#141C20; --surface-2:#1B252A; --ink:#E4EBE9; --ink-2:#AEBDC1; --muted:#7F9197;
  --rule:#243136; --rule-2:#2F3E44; --accent:#4FC3CF; --accent-ink:#8ADCE4; --accent-soft:#12333A;
  --warm:#E39A4E; --code-bg:#182226; --sel:#1F4A50; --shadow:0 1px 0 rgba(0,0,0,.4);
}}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
@media (prefers-reduced-motion: reduce){ html{scroll-behavior:auto} *{transition:none!important} }
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
::selection{background:var(--sel)}
a{color:var(--accent-ink);text-decoration:none;border-bottom:1px solid transparent}
a:hover{border-bottom-color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:2px}
.top{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--rule);height:56px;display:flex;align-items:center;gap:18px;padding:0 22px}
.brand{display:flex;align-items:center;gap:12px;font-family:"Bricolage Grotesque","IBM Plex Sans",sans-serif;font-weight:700;font-size:19px;letter-spacing:-.01em;color:var(--ink)}
.brand a{color:inherit;border:0}
.brand .slash{color:var(--muted);font-weight:400;margin:0 2px}
.brand .aurea{color:var(--accent)}
.wave{display:flex;align-items:center;gap:2px;height:22px}
.wave i{display:block;width:3px;border-radius:2px;background:var(--accent);height:var(--h)}
.top .meta{margin-left:auto;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;color:var(--muted);letter-spacing:.02em;display:flex;gap:16px}
.top .meta span b{color:var(--ink-2);font-weight:500}
.menu-btn{display:none;background:none;border:1px solid var(--rule-2);color:var(--ink);border-radius:6px;padding:4px 10px;font:inherit;font-size:13px}
.shell{display:grid;grid-template-columns:var(--nav-w) minmax(0,1fr) var(--toc-w);max-width:1320px;margin:0 auto}
nav.docs{position:sticky;top:56px;height:calc(100vh - 56px);overflow:auto;padding:22px 14px 22px 22px;border-right:1px solid var(--rule)}
nav.docs .search{width:100%;background:var(--surface);border:1px solid var(--rule-2);color:var(--ink);border-radius:6px;padding:7px 10px;font:inherit;font-size:13.5px;margin-bottom:14px}
nav.docs .search::placeholder{color:var(--muted)}
nav.docs .group{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:16px 0 6px 10px}
nav.docs a{display:block;padding:6px 10px;border-radius:6px;color:var(--ink-2);font-size:14px;border:0;line-height:1.35}
nav.docs a:hover{background:var(--surface-2);color:var(--ink)}
nav.docs a.active{background:var(--accent-soft);color:var(--accent-ink);font-weight:600}
nav.docs a .hit{display:block;font-size:12px;color:var(--muted);font-weight:400;margin-top:2px;padding-left:10px;border-left:2px solid var(--rule-2)}
nav.docs .empty{color:var(--muted);font-size:13px;padding:6px 10px}
main{padding:34px 48px 80px;min-width:0}
article{max-width:74ch}
aside.toc{position:sticky;top:56px;height:calc(100vh - 56px);overflow:auto;padding:30px 22px 22px 8px;font-size:13px}
aside.toc .label{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
aside.toc a{display:block;color:var(--ink-2);padding:3px 0 3px 10px;border-left:2px solid var(--rule);line-height:1.4;border-bottom:0}
aside.toc a.h3{padding-left:22px;font-size:12.5px;color:var(--muted)}
aside.toc a:hover{color:var(--ink)}
aside.toc a.current{color:var(--accent-ink);border-left-color:var(--accent)}
.crumb{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;color:var(--muted);letter-spacing:.02em;margin-bottom:14px;display:flex;gap:8px;align-items:center}
.crumb .n{color:var(--accent);font-weight:500}
article h1,article h2,article h3,article h4{font-family:"Bricolage Grotesque","IBM Plex Sans",sans-serif;text-wrap:balance;letter-spacing:-.015em;line-height:1.15;color:var(--ink);scroll-margin-top:76px}
article h1{font-size:38px;font-weight:700;margin:0 0 18px}
article h2{font-size:24px;font-weight:600;margin:44px 0 12px;padding-top:18px;border-top:1px solid var(--rule)}
article h3{font-size:18px;font-weight:600;margin:28px 0 8px}
article h4{font-size:15.5px;font-weight:600;margin:20px 0 6px}
article p{margin:0 0 14px}
article ul,article ol{padding-left:24px;margin:0 0 14px}
article li{margin:4px 0}
article li>p{margin:0}
article strong{font-weight:600}
article hr{border:0;border-top:1px solid var(--rule);margin:28px 0}
article blockquote{margin:0 0 14px;padding:8px 16px;border-left:3px solid var(--accent);background:var(--surface-2);color:var(--ink-2);border-radius:0 6px 6px 0}
article code{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em;background:var(--code-bg);padding:1px 5px;border-radius:4px;color:var(--ink)}
article pre{background:var(--code-bg);border:1px solid var(--rule);border-radius:8px;padding:14px 16px;overflow-x:auto;margin:0 0 18px;line-height:1.5}
article pre code{background:none;padding:0;font-size:13px;color:var(--ink)}
.table-wrap{overflow-x:auto;margin:0 0 20px;border:1px solid var(--rule);border-radius:8px;background:var(--surface);box-shadow:var(--shadow)}
article table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
article th{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;letter-spacing:.08em;text-transform:uppercase;font-weight:500;color:var(--ink-2);text-align:left;padding:10px 12px;background:var(--surface-2);border-bottom:1px solid var(--rule-2);white-space:nowrap}
article td{padding:9px 12px;border-bottom:1px solid var(--rule);vertical-align:top}
article tr:last-child td{border-bottom:0}
article td code{white-space:nowrap}
article td:first-child code{color:var(--accent-ink)}
article table strong{color:var(--warm)}
.pager{display:flex;justify-content:space-between;gap:16px;margin-top:56px;padding-top:18px;border-top:1px solid var(--rule);font-size:14px}
.pager a{border:0;color:var(--ink-2)}
.pager a small{display:block;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:2px}
.pager a b{font-weight:600;color:var(--accent-ink)}
.pager .next{text-align:right;margin-left:auto}
.source{margin-top:26px;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11.5px;color:var(--muted)}
.source code{background:none;padding:0;font-size:inherit;color:var(--ink-2)}
@media (max-width:1180px){ .shell{grid-template-columns:var(--nav-w) minmax(0,1fr)} aside.toc{display:none} }
@media (max-width:820px){
  .shell{grid-template-columns:minmax(0,1fr)}
  nav.docs{position:fixed;left:0;top:56px;width:min(84vw,320px);background:var(--bg);transform:translateX(-102%);transition:transform .2s ease;z-index:15;box-shadow:4px 0 24px rgba(0,0,0,.18)}
  nav.docs.open{transform:none}
  .menu-btn{display:inline-block}
  .top .meta{display:none}
  main{padding:24px 18px 60px}
  article h1{font-size:30px}
}
</style>
</head>
<body>
<header class="top">
  <button class="menu-btn" id="menuBtn" aria-controls="docnav" aria-expanded="false">Docs</button>
  <div class="brand">
    <span class="wave" aria-hidden="true"><i style="--h:6px"></i><i style="--h:14px"></i><i style="--h:22px"></i><i style="--h:11px"></i><i style="--h:17px"></i><i style="--h:7px"></i></span>
    <a href="#readme">Alveus<span class="slash">/</span><span class="aurea">Aurea</span></a>
  </div>
  <div class="meta"><span>LLM <b>Bonsai-27B</b></span><span>STT <b>whisper turbo</b></span><span>TTS <b>Kokoro</b></span><span>built <b>__STAMP__</b></span></div>
</header>
<div class="shell">
  <nav class="docs" id="docnav" aria-label="Documents">
    <input class="search" id="search" type="search" placeholder="Search headings…" aria-label="Search headings">
    <div id="navlist"></div>
  </nav>
  <main>
    <div class="crumb" id="crumb"></div>
    <article id="article"></article>
    <div class="pager" id="pager"></div>
    <div class="source" id="source"></div>
  </main>
  <aside class="toc" aria-label="On this page"><div class="label">On this page</div><div id="toc"></div></aside>
</div>
<script type="application/json" id="docs-data">__PAYLOAD__</script>
<script>
(function(){
  const DOCS = JSON.parse(document.getElementById('docs-data').textContent);
  const GROUPS = [...new Set(DOCS.map(d=>d.group))].map(g => [g, DOCS.filter(d=>d.group===g).map(d=>d.slug)]);
  const bySlug = Object.fromEntries(DOCS.map(d=>[d.slug,d]));
  const $ = id => document.getElementById(id);
  const article=$('article'), toc=$('toc'), navlist=$('navlist'), crumb=$('crumb'), pager=$('pager'), source=$('source');
  const search=$('search'), nav=$('docnav'), menuBtn=$('menuBtn');
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

  function buildNav(filter){
    const q=(filter||'').trim().toLowerCase(); let html='', any=false;
    for (const [g, slugs] of GROUPS){
      let items='';
      for (const s of slugs){
        const d=bySlug[s];
        const hits = q ? d.headings.filter(h=>h.text.toLowerCase().includes(q)) : [];
        if (q && !hits.length && !d.title.toLowerCase().includes(q)) continue;
        any=true;
        items += `<a href="#${s}" data-slug="${s}">${esc(d.title)}${hits.slice(0,6).map(h=>`<span class="hit"><a href="#${s}/${h.id}">${esc(h.text)}</a></span>`).join('')}</a>`;
      }
      if (items) html += `<div class="group">${esc(g)}</div>${items}`;
    }
    navlist.innerHTML = any ? html : '<div class="empty">No headings match.</div>';
    markActive();
  }
  function current(){ const slug=location.hash.replace(/^#/,'').split('/')[0]; return bySlug[slug] ? slug : 'readme'; }
  function markActive(){ const s=current(); navlist.querySelectorAll('a[data-slug]').forEach(a=>a.classList.toggle('active', a.dataset.slug===s)); }
  function show(){
    const slug=current(), idx=DOCS.findIndex(d=>d.slug===slug), d=DOCS[idx], sub=location.hash.split('/')[1];
    article.innerHTML = d.html;
    crumb.innerHTML = `<span class="n">${String(idx+1).padStart(2,'0')}</span> · ${esc(d.group)} · ${esc(d.title)}`;
    toc.innerHTML = d.headings.map(h=>`<a href="#${slug}/${h.id}" class="${h.level===3?'h3':''}" data-id="${h.id}">${esc(h.text)}</a>`).join('') || '<span style="color:var(--muted)">—</span>';
    const prev=DOCS[idx-1], next=DOCS[idx+1];
    pager.innerHTML = (prev?`<a class="prev" href="#${prev.slug}"><small>Previous</small><b>${esc(prev.title)}</b></a>`:'<span></span>') + (next?`<a class="next" href="#${next.slug}"><small>Next</small><b>${esc(next.title)}</b></a>`:'');
    source.innerHTML = `Source: <code>${esc(d.source)}</code> — regenerate with <code>python scripts/build_handbook.py</code>`;
    document.title = slug==='readme' ? 'Alveus Handbook' : d.title + ' · Alveus Handbook';
    markActive(); nav.classList.remove('open'); menuBtn.setAttribute('aria-expanded','false');
    if (sub){ const el=document.getElementById(sub); if (el) el.scrollIntoView({block:'start'}); } else window.scrollTo(0,0);
    observe();
  }
  let io;
  function observe(){
    if (io) io.disconnect();
    const links=[...toc.querySelectorAll('a')]; if(!links.length) return;
    io = new IntersectionObserver(entries => {
      const vis = entries.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top)[0];
      if (vis) links.forEach(a=>a.classList.toggle('current', a.dataset.id===vis.target.id));
    }, {rootMargin:'-70px 0px -70% 0px'});
    article.querySelectorAll('h2,h3').forEach(h=>io.observe(h));
  }
  search.addEventListener('input', e=>buildNav(e.target.value));
  menuBtn.addEventListener('click', ()=>{ const open=nav.classList.toggle('open'); menuBtn.setAttribute('aria-expanded', String(open)); });
  window.addEventListener('hashchange', show);
  buildNav(''); show();
})();
</script>
</body>
</html>
'''

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DOCS / "handbook.html"))
    build(Path(ap.parse_args().out))
