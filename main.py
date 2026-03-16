# main.py
# ═══════════════════════════════════════════════════════════════════
#  WebNav — Navigateur Web Multi-Moteur (fichier unique)
#  7 moteurs : Requests, HTTPX, MechanicalSoup, Selenium Chrome,
#              Selenium Firefox, Playwright, Pyppeteer
#
#  Usage :  pip install flask requests httpx mechanicalsoup \
#                       selenium playwright pyppeteer beautifulsoup4
#           playwright install chromium
#           python main.py
# ═══════════════════════════════════════════════════════════════════

import os
import re
import sys
import json
import asyncio
import base64
import traceback
from abc import ABC, abstractmethod
from flask import Flask, request, jsonify, Response


# ─────────────────────────────────────────────────────────────────
# 1. MOTEURS DE NAVIGATION
# ─────────────────────────────────────────────────────────────────

class BaseEngine(ABC):
    """
    Classe abstraite. Chaque moteur retourne :
    {
        "url":        str,       # URL finale
        "status":     int,       # Code HTTP
        "title":      str,       # <title>
        "html":       str,       # HTML complet
        "screenshot": str|None,  # base64 PNG
        "engine":     str,       # nom du moteur
        "headers":    dict,      # en-têtes de réponse
    }
    """
    name: str = "base"

    @abstractmethod
    def fetch(self, url: str) -> dict:
        ...

    @staticmethod
    def _extract_title(html: str) -> str:
        m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
        return m.group(1).strip() if m else '(sans titre)'

    @staticmethod
    def _ua():
        return (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )


# ── 1) Requests ──────────────────────────────────────────────
class RequestsEngine(BaseEngine):
    name = "requests"

    def fetch(self, url):
        import requests as req
        r = req.get(url, headers={'User-Agent': self._ua()},
                    timeout=30, allow_redirects=True)
        r.encoding = r.apparent_encoding or 'utf-8'
        html = r.text
        return {
            'url': r.url, 'status': r.status_code,
            'title': self._extract_title(html), 'html': html,
            'screenshot': None, 'engine': self.name,
            'headers': dict(r.headers),
        }


# ── 2) HTTPX (async) ────────────────────────────────────────
class HttpxEngine(BaseEngine):
    name = "httpx"

    async def fetch(self, url):
        import httpx
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=30.0, verify=False
        ) as client:
            r = await client.get(url, headers={'User-Agent': self._ua()})
            html = r.text
            return {
                'url': str(r.url), 'status': r.status_code,
                'title': self._extract_title(html), 'html': html,
                'screenshot': None, 'engine': self.name,
                'headers': dict(r.headers),
            }


# ── 3) MechanicalSoup ───────────────────────────────────────
class MechanicalSoupEngine(BaseEngine):
    name = "mechanicalsoup"

    def fetch(self, url):
        import mechanicalsoup
        br = mechanicalsoup.StatefulBrowser(user_agent=self._ua())
        br.open(url, timeout=30)
        page = br.page
        html = str(page)
        title = page.title.string if page.title and page.title.string else '(sans titre)'
        return {
            'url': br.url, 'status': 200,
            'title': title, 'html': html,
            'screenshot': None, 'engine': self.name,
            'headers': {},
        }


# ── 4) Selenium Chrome ──────────────────────────────────────
class SeleniumChromeEngine(BaseEngine):
    name = "selenium-chrome"

    def fetch(self, url):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        opts = Options()
        for flag in ['--headless=new', '--no-sandbox',
                     '--disable-dev-shm-usage', '--disable-gpu',
                     '--window-size=1920,1080']:
            opts.add_argument(flag)
        opts.add_argument(f'--user-agent={self._ua()}')
        driver = webdriver.Chrome(options=opts)
        try:
            driver.set_page_load_timeout(30)
            driver.get(url)
            html = driver.page_source
            shot = base64.b64encode(driver.get_screenshot_as_png()).decode()
            return {
                'url': driver.current_url, 'status': 200,
                'title': driver.title or self._extract_title(html),
                'html': html, 'screenshot': shot,
                'engine': self.name, 'headers': {},
            }
        finally:
            driver.quit()


# ── 5) Selenium Firefox ─────────────────────────────────────
class SeleniumFirefoxEngine(BaseEngine):
    name = "selenium-firefox"

    def fetch(self, url):
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        opts = Options()
        opts.add_argument('--headless')
        opts.set_preference('general.useragent.override', self._ua())
        driver = webdriver.Firefox(options=opts)
        try:
            driver.set_page_load_timeout(30)
            driver.set_window_size(1920, 1080)
            driver.get(url)
            html = driver.page_source
            shot = base64.b64encode(driver.get_screenshot_as_png()).decode()
            return {
                'url': driver.current_url, 'status': 200,
                'title': driver.title or self._extract_title(html),
                'html': html, 'screenshot': shot,
                'engine': self.name, 'headers': {},
            }
        finally:
            driver.quit()


# ── 6) Playwright ────────────────────────────────────────────
class PlaywrightEngine(BaseEngine):
    name = "playwright"

    async def fetch(self, url):
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            ctx = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=self._ua(),
            )
            page = await ctx.new_page()
            resp = await page.goto(url, wait_until='networkidle', timeout=30000)
            html = await page.content()
            shot = base64.b64encode(await page.screenshot()).decode()
            result = {
                'url': page.url, 'status': resp.status if resp else 0,
                'title': await page.title() or self._extract_title(html),
                'html': html, 'screenshot': shot,
                'engine': self.name,
                'headers': dict(resp.headers) if resp else {},
            }
            await browser.close()
            return result


# ── 7) Pyppeteer ─────────────────────────────────────────────
class PyppeteerEngine(BaseEngine):
    name = "pyppeteer"

    async def fetch(self, url):
        from pyppeteer import launch
        browser = await launch(
            headless=True,
            handleSIGINT=False, handleSIGTERM=False, handleSIGHUP=False,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--single-process']
        )
        try:
            page = await browser.newPage()
            await page.setViewport({'width': 1920, 'height': 1080})
            await page.setUserAgent(self._ua())
            resp = await page.goto(url, {'waitUntil': 'networkidle0', 'timeout': 30000})
            html = await page.content()
            shot = base64.b64encode(await page.screenshot()).decode()
            return {
                'url': page.url,
                'status': resp.status if resp else 0,
                'title': await page.title() or self._extract_title(html),
                'html': html, 'screenshot': shot,
                'engine': self.name,
                'headers': resp.headers if resp else {},
            }
        finally:
            await browser.close()


# ─────────────────────────────────────────────────────────────────
# 2. FACTORY — REGISTRE DES MOTEURS
# ─────────────────────────────────────────────────────────────────

ENGINE_REGISTRY = {
    'requests':         RequestsEngine,
    'httpx':            HttpxEngine,
    'mechanicalsoup':   MechanicalSoupEngine,
    'selenium-chrome':  SeleniumChromeEngine,
    'selenium-firefox': SeleniumFirefoxEngine,
    'playwright':       PlaywrightEngine,
    'pyppeteer':        PyppeteerEngine,
}

ENGINE_META = {
    'requests':         {'label': 'Requests',         'icon': '📡', 'desc': 'HTTP simple, pas de JS',           'cat': 'light'},
    'httpx':            {'label': 'HTTPX',             'icon': '⚡', 'desc': 'HTTP async moderne',              'cat': 'light'},
    'mechanicalsoup':   {'label': 'MechanicalSoup',    'icon': '🍜', 'desc': 'Navigation formulaire',           'cat': 'light'},
    'selenium-chrome':  {'label': 'Selenium Chrome',   'icon': '🌐', 'desc': 'Chromium headless + JS',          'cat': 'head'},
    'selenium-firefox': {'label': 'Selenium Firefox',  'icon': '🦊', 'desc': 'Firefox headless + JS',           'cat': 'head'},
    'playwright':       {'label': 'Playwright',        'icon': '🎭', 'desc': 'Chromium + screenshot',           'cat': 'head'},
    'pyppeteer':        {'label': 'Pyppeteer',         'icon': '🤖', 'desc': 'Puppeteer Python',                'cat': 'head'},
}


def run_engine(engine, url):
    """Exécute un moteur sync ou async et retourne le dict résultat."""
    if asyncio.iscoroutinefunction(engine.fetch):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(engine.fetch(url))
        finally:
            loop.close()
    return engine.fetch(url)


# ─────────────────────────────────────────────────────────────────
# 3. APPLICATION FLASK
# ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')


# ── Page HTML intégrée (tout-en-un) ─────────────────────────
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🌐 WebNav</title>
<style>
/* ── Reset ───────────────────────────────── */
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg1:#1a1b2e;--bg2:#232440;--bg3:#2a2b4a;--bg4:#2e2f52;
  --hov:#363760;--t1:#e8e9f3;--t2:#a0a2c0;--tm:#6b6d8a;
  --ac:#6c63ff;--ac2:#7b73ff;--acg:rgba(108,99,255,.3);
  --ok:#4ade80;--wn:#fbbf24;--er:#f87171;
  --bd:rgba(255,255,255,.06);--r:12px;--rs:8px;--rx:6px;
  --sh:0 4px 24px rgba(0,0,0,.3);--tr:.2s ease;
  --f:'Inter',system-ui,sans-serif;--fm:'Courier New',monospace;
}
html,body{height:100%;font-family:var(--f);background:var(--bg1);color:var(--t1);overflow:hidden}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:0 0}
::-webkit-scrollbar-thumb{background:var(--hov);border-radius:3px}

/* ── Layout ──────────────────────────────── */
.app{display:flex;flex-direction:column;height:100vh}
.main{display:flex;flex:1;overflow:hidden}

/* ── Navbar ──────────────────────────────── */
.nav{display:flex;align-items:center;gap:10px;padding:8px 14px;background:var(--bg2);border-bottom:1px solid var(--bd);height:54px;z-index:100}
.brand{display:flex;align-items:center;gap:6px;flex-shrink:0}
.brand b{font-size:15px;background:linear-gradient(135deg,var(--ac),#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.urlc{flex:1;max-width:860px}
.urlbar{display:flex;align-items:center;gap:4px;background:var(--bg3);border:1px solid var(--bd);border-radius:var(--r);padding:3px}
.urlbar:focus-within{border-color:var(--ac);box-shadow:0 0 0 3px var(--acg)}
.nb{display:flex;gap:2px}
.nb button,.abtn{width:32px;height:32px;border:0;background:0 0;color:var(--t2);border-radius:var(--rx);cursor:pointer;font-size:15px;display:flex;align-items:center;justify-content:center;transition:all var(--tr)}
.nb button:hover,.abtn:hover{background:var(--hov);color:var(--t1)}
.abtn{width:34px;height:34px;background:var(--bg3)}
.uiw{flex:1;display:flex;align-items:center;gap:8px}
.uiw span{font-size:13px;flex-shrink:0}
#url{width:100%;border:0;background:0 0;color:var(--t1);font-family:var(--f);font-size:13px;outline:0;padding:5px 0}
#url::placeholder{color:var(--tm)}
.go{display:flex;align-items:center;gap:5px;padding:5px 14px;background:var(--ac);color:#fff;border:0;border-radius:var(--rs);font-family:var(--f);font-weight:600;font-size:12px;cursor:pointer;transition:all var(--tr);white-space:nowrap}
.go:hover{background:var(--ac2);transform:translateY(-1px)}
.acts{display:flex;gap:4px;flex-shrink:0}

/* ── Panel ───────────────────────────────── */
.panel{width:280px;background:var(--bg2);border-right:1px solid var(--bd);overflow-y:auto;flex-shrink:0;transition:margin .25s,opacity .25s}
.panel.hide{margin-left:-280px;opacity:0;pointer-events:none}
.ph{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--bd)}
.ph h3{font-size:12px;font-weight:600;color:var(--t2);text-transform:uppercase;letter-spacing:.6px}
.px{width:26px;height:26px;border:0;background:0 0;color:var(--tm);border-radius:var(--rx);cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:center}
.px:hover{background:var(--hov);color:var(--t1)}
.cats{padding:10px}
.cat{margin-bottom:14px}
.ct{font-size:10px;font-weight:600;color:var(--tm);text-transform:uppercase;letter-spacing:.8px;padding:0 8px 6px}
.el{display:flex;flex-direction:column;gap:3px}
.eo{cursor:pointer}.eo input{display:none}
.ec{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:var(--rs);border:1px solid transparent;transition:all var(--tr)}
.ec:hover{background:var(--bg3)}
.eo input:checked+.ec{background:rgba(108,99,255,.1);border-color:var(--ac)}
.ei{font-size:18px;flex-shrink:0}
.en{flex:1;display:flex;flex-direction:column;min-width:0}
.en span:first-child{font-size:12px;font-weight:500;color:var(--t1)}
.en span:last-child{font-size:10px;color:var(--tm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ck{font-size:13px;color:var(--ac);opacity:0;transition:opacity var(--tr)}
.eo input:checked+.ec .ck{opacity:1}

/* ── Viewport ────────────────────────────── */
.vp{flex:1;display:flex;flex-direction:column;position:relative;overflow:hidden;background:#0d0e1a}

/* Welcome */
.ws{flex:1;display:flex;align-items:center;justify-content:center}
.wc{text-align:center;padding:40px}
.wl{font-size:64px;margin-bottom:12px;animation:fl 3s ease-in-out infinite}
@keyframes fl{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}
.wc h1{font-size:32px;font-weight:700;background:linear-gradient(135deg,var(--ac),#a78bfa,#f472b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:6px}
.wc p{color:var(--tm);font-size:15px;margin-bottom:28px}
.ql{display:flex;gap:10px;flex-wrap:wrap;justify-content:center}
.ql button{padding:9px 18px;background:var(--bg3);border:1px solid var(--bd);border-radius:var(--r);color:var(--t1);font-family:var(--f);font-size:13px;cursor:pointer;transition:all var(--tr)}
.ql button:hover{background:var(--hov);border-color:var(--ac);transform:translateY(-2px);box-shadow:var(--sh)}

/* Loading */
.lo{position:absolute;inset:0;background:rgba(13,14,26,.92);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:50;backdrop-filter:blur(4px)}
.sp{width:44px;height:44px;border:3px solid var(--bg3);border-top-color:var(--ac);border-radius:50%;animation:sn .8s linear infinite;margin-bottom:14px}
@keyframes sn{to{transform:rotate(360deg)}}
.lo p{color:var(--t2);font-size:13px}.lo .le{color:var(--ac);font-size:11px;margin-top:3px;font-weight:500}

/* Info bar */
.ib{display:flex;align-items:center;gap:10px;padding:5px 14px;background:var(--bg2);border-bottom:1px solid var(--bd);font-size:11px;flex-shrink:0}
.is{padding:2px 7px;border-radius:4px;font-weight:600;font-family:var(--fm);font-size:10px}
.is.ok{background:rgba(74,222,128,.15);color:var(--ok)}
.is.wn{background:rgba(251,191,36,.15);color:var(--wn)}
.is.er{background:rgba(248,113,113,.15);color:var(--er)}
.ie{padding:2px 7px;background:rgba(108,99,255,.1);color:var(--ac);border-radius:4px;font-weight:500;font-size:10px}
.it{flex:1;color:var(--t2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ia{display:flex;gap:3px}
.ia button{padding:2px 7px;border:0;background:var(--bg3);color:var(--t2);border-radius:4px;cursor:pointer;font-size:11px;transition:all var(--tr)}
.ia button:hover{background:var(--hov);color:var(--t1)}
.ia button.on{background:var(--ac);color:#fff}

/* Frame / source / screenshot / error */
.rf{flex:1;width:100%;border:0;background:#fff}
.sv{flex:1;overflow:auto;padding:18px;background:var(--bg1)}
.sv pre{margin:0}.sv code{font-family:var(--fm);font-size:11px;line-height:1.6;color:var(--t2);white-space:pre-wrap;word-break:break-all}
.ssv{flex:1;overflow:auto;display:flex;align-items:flex-start;justify-content:center;padding:18px;background:var(--bg1)}
.ssv img{max-width:100%;height:auto;border-radius:var(--r);box-shadow:var(--sh)}
.ev{flex:1;display:flex;align-items:center;justify-content:center}
.evc{text-align:center;padding:40px}
.evc .eic{font-size:44px}.evc h2{font-size:18px;margin:14px 0 6px;color:var(--er)}
.evc p{color:var(--tm);max-width:380px}

@media(max-width:768px){
  .panel{width:240px}.panel.hide{margin-left:-240px}
  .brand b{display:none}.nb{display:none}
}
</style>
</head>
<body>
<div class="app">
  <!-- Navbar -->
  <header class="nav">
    <div class="brand"><span style="font-size:22px">🌐</span><b>WebNav</b></div>
    <div class="urlc">
      <form id="frm" class="urlbar">
        <div class="nb">
          <button type="button" id="bk" title="Précédent">←</button>
          <button type="button" id="fw" title="Suivant">→</button>
          <button type="button" id="re" title="Actualiser">↻</button>
        </div>
        <div class="uiw"><span>🔒</span>
          <input type="text" id="url" placeholder="Entrer une URL ou une recherche…" autocomplete="off" spellcheck="false" required>
        </div>
        <button type="submit" class="go">Aller →</button>
      </form>
    </div>
    <div class="acts">
      <button class="abtn" id="tp" title="Panneau moteur">⚙️</button>
      <button class="abtn" id="tv" title="Changer de vue">👁️</button>
    </div>
  </header>

  <div class="main">
    <!-- Engine panel -->
    <aside class="panel" id="pnl">
      <div class="ph"><h3>Moteur de rendu</h3><button class="px" id="cp">✕</button></div>
      <div class="cats">
        <div class="cat"><h4 class="ct">⚡ Légers (sans JS)</h4><div class="el" id="lightE"></div></div>
        <div class="cat"><h4 class="ct">🖥️ Headless (avec JS)</h4><div class="el" id="headE"></div></div>
      </div>
    </aside>

    <!-- Viewport -->
    <main class="vp" id="vp">
      <div class="ws" id="ws">
        <div class="wc">
          <div class="wl">🌐</div><h1>WebNav</h1>
          <p>Navigateur web multi-moteur</p>
          <div class="ql">
            <button data-u="https://www.wikipedia.org">📚 Wikipedia</button>
            <button data-u="https://news.ycombinator.com">📰 Hacker News</button>
            <button data-u="https://github.com">🐙 GitHub</button>
            <button data-u="https://httpbin.org/html">🧪 HTTPBin</button>
          </div>
        </div>
      </div>
      <div class="lo" id="lo" style="display:none"><div class="sp"></div><p>Chargement…</p><p class="le" id="leng"></p></div>
      <div class="ib" id="ib" style="display:none">
        <span class="is" id="ist"></span><span class="ie" id="ien"></span><span class="it" id="iti"></span>
        <div class="ia">
          <button id="bs" title="Source">{ }</button>
          <button id="bss" title="Screenshot" style="display:none">📸</button>
        </div>
      </div>
      <iframe id="rf" class="rf" style="display:none" sandbox="allow-same-origin"></iframe>
      <div class="sv" id="sv" style="display:none"><pre><code id="sc"></code></pre></div>
      <div class="ssv" id="ssv" style="display:none"><img id="si" alt="Screenshot"></div>
      <div class="ev" id="ev" style="display:none"><div class="evc"><span class="eic">⚠️</span><h2>Erreur</h2><p id="em"></p></div></div>
    </main>
  </div>
</div>

<script>
(function(){
'use strict';

// ── Données moteurs (injectées par Flask) ───────
const ENGINES=__ENGINES_JSON__;

// ── Construction du panneau ─────────────────────
const lightEl=document.getElementById('lightE');
const headEl=document.getElementById('headE');
ENGINES.forEach((e,i)=>{
  const lbl=document.createElement('label');lbl.className='eo';
  lbl.innerHTML=`<input type="radio" name="eng" value="${e.id}" ${i===0?'checked':''}>`+
    `<div class="ec"><span class="ei">${e.icon}</span>`+
    `<div class="en"><span>${e.label}</span><span>${e.desc}</span></div>`+
    `<span class="ck">✓</span></div>`;
  (e.cat==='light'?lightEl:headEl).appendChild(lbl);
});

// ── Refs DOM ────────────────────────────────────
const $=id=>document.getElementById(id);
const frm=$('frm'),urlI=$('url'),lo=$('lo'),leng=$('leng'),
      ws=$('ws'),rf=$('rf'),sv=$('sv'),sc=$('sc'),
      ssv=$('ssv'),si=$('si'),ev=$('ev'),em=$('em'),
      ib=$('ib'),ist=$('ist'),ien=$('ien'),iti=$('iti'),
      bs=$('bs'),bss=$('bss'),pnl=$('pnl');

let cur=null,view='render',hist=[],hi=-1;

function eng(){const c=document.querySelector('input[name="eng"]:checked');return c?c.value:'requests'}
function hide(){for(const x of[ws,rf,sv,ssv,ev])x.style.display='none'}
function show(v){
  hide();view=v;bs.classList.remove('on');bss.classList.remove('on');
  if(v==='render')rf.style.display='block';
  else if(v==='source'){sv.style.display='block';bs.classList.add('on')}
  else if(v==='shot'){ssv.style.display='flex';bss.classList.add('on')}
}
function stat(c){ist.textContent=c;ist.className='is '+(c>=200&&c<300?'ok':c>=300&&c<400?'wn':'er')}

async function nav(url){
  const e=eng();urlI.value=url;
  lo.style.display='flex';leng.textContent='Moteur : '+e;hide();
  try{
    const [pR,mR]=await Promise.all([
      fetch('/proxy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url,engine:e})}),
      fetch('/browse',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url,engine:e})})
    ]);
    const md=await mR.json();
    if(md.error){lo.style.display='none';hide();em.textContent=md.error;ev.style.display='flex';ib.style.display='none';return}
    cur=md;hi++;hist=hist.slice(0,hi);hist.push({url,engine:e});
    urlI.value=md.url||url;ib.style.display='flex';stat(md.status);ien.textContent=md.engine;iti.textContent=md.title;
    if(md.screenshot){bss.style.display='inline-flex';si.src='data:image/png;base64,'+md.screenshot}else bss.style.display='none';
    sc.textContent=md.html||'';
    const pH=await pR.text();
    rf.src=URL.createObjectURL(new Blob([pH],{type:'text/html;charset=utf-8'}));
    show('render');
  }catch(err){hide();em.textContent=err.message;ev.style.display='flex';ib.style.display='none'}
  finally{lo.style.display='none'}
}

frm.addEventListener('submit',e=>{e.preventDefault();const u=urlI.value.trim();if(u)nav(u)});
document.querySelectorAll('.ql button').forEach(b=>b.addEventListener('click',()=>nav(b.dataset.u)));
$('tp').addEventListener('click',()=>pnl.classList.toggle('hide'));
$('cp').addEventListener('click',()=>pnl.classList.add('hide'));
bs.addEventListener('click',()=>{if(cur)show(view==='source'?'render':'source')});
bss.addEventListener('click',()=>{if(cur&&cur.screenshot)show(view==='shot'?'render':'shot')});
$('tv').addEventListener('click',()=>{
  if(!cur)return;const vs=['render','source'];if(cur.screenshot)vs.push('shot');
  show(vs[(vs.indexOf(view)+1)%vs.length]);
});
$('re').addEventListener('click',()=>{if(cur)nav(urlI.value.trim())});
$('bk').addEventListener('click',()=>{if(hi>0){hi--;const h=hist[hi];const r=document.querySelector(`input[name="eng"][value="${h.engine}"]`);if(r)r.checked=true;nav(h.url)}});
$('fw').addEventListener('click',()=>{if(hi<hist.length-1){hi++;const h=hist[hi];const r=document.querySelector(`input[name="eng"][value="${h.engine}"]`);if(r)r.checked=true;nav(h.url)}});
urlI.focus();
})();
</script>
</body>
</html>"""


@app.route('/')
def index():
    engines_list = [
        {'id': k, **ENGINE_META[k]}
        for k in ENGINE_REGISTRY
    ]
    html = INDEX_HTML.replace(
        '__ENGINES_JSON__',
        json.dumps(engines_list, ensure_ascii=False)
    )
    return Response(html, content_type='text/html; charset=utf-8')


@app.route('/browse', methods=['POST'])
def browse():
    data = request.get_json() or request.form
    url = (data.get('url') or '').strip()
    eng = (data.get('engine') or 'requests').strip().lower()

    if not url:
        return jsonify({'error': 'URL requise'}), 400
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    if eng not in ENGINE_REGISTRY:
        return jsonify({'error': f"Moteur inconnu : {eng}"}), 400

    try:
        engine = ENGINE_REGISTRY[eng]()
        result = run_engine(engine, url)
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/proxy', methods=['POST'])
def proxy():
    data = request.get_json() or request.form
    url = (data.get('url') or '').strip()
    eng = (data.get('engine') or 'requests').strip().lower()

    if not url:
        return Response('URL requise', status=400)
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        engine = ENGINE_REGISTRY.get(eng, RequestsEngine)()
        result = run_engine(engine, url)
        html = result.get('html', '')
        base_tag = f'<base href="{url}">'
        for tag in ['<head>', '<HEAD>']:
            if tag in html:
                html = html.replace(tag, f'{tag}{base_tag}', 1)
                break
        else:
            html = base_tag + html
        return Response(html, content_type='text/html; charset=utf-8')
    except Exception as e:
        return Response(f'Erreur: {e}', status=500)


# ─────────────────────────────────────────────────────────────────
# 4. POINT D'ENTRÉE
# ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"""
    ╔══════════════════════════════════════════╗
    ║          🌐  WebNav démarré              ║
    ║   http://localhost:{port:<5}                 ║
    ║                                          ║
    ║   Moteurs disponibles :                  ║
    ║   📡 requests    ⚡ httpx                ║
    ║   🍜 mechanicalsoup                      ║
    ║   🌐 selenium-chrome  🦊 selenium-firefox ║
    ║   🎭 playwright  🤖 pyppeteer            ║
    ╚══════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=port, debug=False)
