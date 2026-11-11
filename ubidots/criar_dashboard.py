#!/usr/bin/env python3
"""Cria (ou atualiza) no Ubidots o device "irrigacao", as 6 variáveis e o dashboard
"Irrigação" (um widget HTML Canvas com painel.html/.css/.js, parecido com o do Node-RED).

Uso:  UBIDOTS_TOKEN=BBUS-... python3 ubidots/criar_dashboard.py
      (sem a variável de ambiente, lê o token de pi/ubidots.json)

Rodar de novo atualiza o código do widget sem mudar o link do dashboard.
"""
import json
import os
import sys
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
API = "https://industrial.api.ubidots.com/api"
DEVICE = "irrigacao"
DASH = "irrigacao"
VARIAVEIS = [  # rótulo, nome, unidade, ícone
    ("solo", "Umidade do solo", "%", "sprout"),
    ("temperatura", "Temperatura", "°C", "thermometer"),
    ("umidade_ar", "Umidade do ar", "%", "tint"),
    ("agua", "Reservatório (1 = com água)", None, "water"),
    ("bomba", "Bomba (1 = ligada)", None, "power-off"),
    ("modo_auto", "Modo automático (1 = auto)", None, "robot"),
]
ALTURA = 26  # unidades da grade do Ubidots (~40 px cada)


def token():
    t = os.environ.get("UBIDOTS_TOKEN", "").strip()
    if not t:
        try:
            with open(os.path.join(AQUI, "..", "pi", "ubidots.json")) as f:
                t = json.load(f).get("token", "").strip()
        except FileNotFoundError:
            pass
    if not t:
        sys.exit("Defina UBIDOTS_TOKEN ou crie pi/ubidots.json com o token.")
    return t


TOKEN = token()


def api(metodo, caminho, corpo=None):
    req = urllib.request.Request(
        API + caminho, method=metodo,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers={"X-Auth-Token": TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode()
            return r.status, (json.loads(txt) if txt.strip() else None)
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt)
        except ValueError:
            return e.code, txt


def garantir_device():
    if api("GET", f"/v2.0/devices/~{DEVICE}/")[0] == 404:
        c, r = api("POST", "/v2.0/devices/", {"label": DEVICE, "name": "Irrigação",
                                             "description": "Raspberry Pi 4 + Node-RED: irrigação automática"})
        print("device criado" if c == 201 else f"erro ao criar device: {c} {r}")
    for lab, nome, un, icone in VARIAVEIS:
        if api("GET", f"/v2.0/devices/~{DEVICE}/variables/~{lab}/")[0] == 404:
            corpo = {"label": lab, "name": nome, "properties": {"_icon": icone}}
            if un:
                corpo["unit"] = un
            c, r = api("POST", f"/v2.0/devices/~{DEVICE}/variables/", corpo)
            print(f"variável {lab}:", "criada" if c == 201 else f"erro {c} {r}")


def settings_widget():
    def ler(nome):
        with open(os.path.join(AQUI, nome), encoding="utf-8") as f:
            return f.read()
    return {"code": {"html": ler("painel.html"), "css": ler("painel.css"), "javascript": ler("painel.js")},
            "lazyLoad": False, "libraries": [], "messageText": "Irrigação",
            "ubidotsReady": False, "isReactEnabled": False}


UX = {"hideHeader": True, "__customStyle": {"boxShadow": "none", "borderRadius": 0,
                                            "backgroundColor": "#F4F4F6"}}


def criar_dashboard():
    camada = "000000000000000000000001"
    pos = {"x": 0, "y": 0, "w": 24, "h": ALTURA}
    modelo = [
        {"__model__": "dashboard", "label": DASH, "name": "Irrigação",
         "description": "Irrigação automática: Raspberry Pi 4 + Node-RED (T3, acesso pela internet)",
         "tags": ["irrigacao"], "timeframe": {"startDate": "now-1h", "endDate": "now"},
         "isEditable": True, "order": 0,
         "context": {"size": None, "isDynamic": False, "displayName": "name",
                     "__customStyle": {"dashboard": {"color": "#1C1D21", "backgroundColor": "#F4F4F6"}},
                     "hasBackground": False, "widgetsOpacity": 1, "floatingWidgets": False,
                     "timestampFormat": "DD/MM/YYYY HH:mm", "hideDatePicker": True,
                     "hideDashboardLayers": True, "hideHeaderFooterWidgets": True,
                     "widgetVerticalSpacing": "15", "widgetHorizontalSpacing": "15"}},
        {"__model__": "widget", "name": "Painel da irrigação", "layer": camada, "type": "canvas",
         "position": {**pos, camada: pos}, "settings": settings_widget(), "uxSettings": UX},
        {"__model__": "layer", "name": "Default Layer: Irrigação", "layer": camada, "position": 0,
         "settings": {"label": "default-layer-irrigacao", "width": "setByDashboard", "visible": True,
                      "alignment": "setByDashboard", "customWidth": 0, "displayName": "default layer"}},
    ]
    c, r = api("POST", "/v2.0/dashboards/_/import_models", modelo)
    if c not in (200, 201):
        sys.exit(f"erro ao importar o dashboard: {c} {json.dumps(r, ensure_ascii=False)[:800]}")
    return r["id"]


def atualizar_widget(dash_id):
    c, r = api("GET", f"/v1.6/dashboards/{dash_id}/widgets/")
    canvas = [w for w in (r or {}).get("results", []) if w.get("type") == "canvas"]
    if not canvas:
        return False
    w = canvas[0]
    pos = dict(w["position"])
    for k, v in list(pos.items()):
        if isinstance(v, dict):
            pos[k] = {**v, "h": ALTURA}
    pos["h"] = ALTURA
    c, r = api("PATCH", f"/v1.6/widgets/{w['id']}/",
               {"settings": settings_widget(), "ux_settings": UX, "position": pos})
    if c not in (200, 201):
        sys.exit(f"erro ao atualizar o widget: {c} {json.dumps(r, ensure_ascii=False)[:500]}")
    return True


def main():
    garantir_device()
    c, r = api("GET", f"/v2.0/dashboards/~{DASH}/")
    if c == 200:
        dash_id = r["id"]
        print("dashboard existente: widget", "atualizado" if atualizar_widget(dash_id) else "não encontrado")
    else:
        dash_id = criar_dashboard()
        print("dashboard criado")
    print(f"https://stem.ubidots.com/app/dashboards/{dash_id}")


if __name__ == "__main__":
    main()
