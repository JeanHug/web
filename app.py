# app.py
import os
import asyncio
import base64
from flask import Flask, render_template, request, jsonify, Response
from browser_engines import EngineFactory

app = Flask(__name__)

# ── Configuration ────────────────────────────────────────────────
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
AVAILABLE_ENGINES = EngineFactory.list_engines()


@app.route('/')
def index():
    """Page principale avec le formulaire de navigation."""
    return render_template('index.html', engines=AVAILABLE_ENGINES)


@app.route('/browse', methods=['POST'])
def browse():
    """
    Endpoint principal : reçoit URL + moteur choisi,
    retourne le contenu HTML rendu + screenshot éventuel.
    """
    data = request.get_json() or request.form
    url = data.get('url', '').strip()
    engine_name = data.get('engine', 'requests').strip()

    if not url:
        return jsonify({'error': 'URL requise'}), 400

    # Ajout automatique du schéma
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        engine = EngineFactory.create(engine_name)
        result = _run_engine(engine, url)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/proxy', methods=['POST'])
def proxy():
    """
    Mode proxy : renvoie le HTML brut pour affichage dans une iframe.
    """
    data = request.get_json() or request.form
    url = data.get('url', '').strip()
    engine_name = data.get('engine', 'requests').strip()

    if not url:
        return Response('URL requise', status=400)

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        engine = EngineFactory.create(engine_name)
        result = _run_engine(engine, url)
        html_content = result.get('html', '')
        # Injection d'une balise <base> pour résoudre les chemins relatifs
        base_tag = f'<base href="{url}">'
        if '<head>' in html_content.lower():
            html_content = html_content.replace('<head>', f'<head>{base_tag}', 1)
            html_content = html_content.replace('<HEAD>', f'<HEAD>{base_tag}', 1)
        else:
            html_content = base_tag + html_content
        return Response(html_content, content_type='text/html; charset=utf-8')
    except Exception as e:
        return Response(f'Erreur: {str(e)}', status=500)


def _run_engine(engine, url):
    """Exécute le moteur (sync ou async) et retourne le résultat unifié."""
    if asyncio.iscoroutinefunction(engine.fetch):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(engine.fetch(url))
        finally:
            loop.close()
    else:
        result = engine.fetch(url)
    return result


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
