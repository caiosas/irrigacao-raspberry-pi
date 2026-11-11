#!/usr/bin/env python3
"""Instala/atualiza a aba "Irrigação" no Node-RED pela Admin API (rodar na Pi).

- faz backup dos fluxos atuais em ~/irrigacao/backup_flows_<data>.json
- desativa as abas antigas que usam rpi-gpio (o pino físico 3 é o SDA do ADS1115)
- substitui os nós com prefixo a1a1 (abas Irrigação e Ubidots) e faz deploy completo
- Ubidots: lê token/device de ~/irrigacao/ubidots.json (sem ele, a aba fica desativada)
"""
import json
import os
import re
import sys
import time
import urllib.request

API = "http://localhost:1880"
PREFIXO = "a1a1"
BASE = os.path.dirname(os.path.abspath(__file__))


def req(metodo, caminho, corpo=None, cab=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    r = urllib.request.Request(API + caminho, data=dados, method=metodo, headers={
        "Content-Type": "application/json", "Node-RED-API-Version": "v2", **(cab or {})})
    with urllib.request.urlopen(r, timeout=30) as resp:
        txt = resp.read().decode()
        return json.loads(txt) if txt else None


atual = req("GET", "/flows")
flows = atual["flows"]
bkp = os.path.join(BASE, time.strftime("backup_flows_%Y%m%d_%H%M%S.json"))
with open(bkp, "w") as f:
    json.dump(flows, f, indent=2, ensure_ascii=False)
print("backup:", bkp)

with open(os.path.join(BASE, "fluxo_irrigacao.json")) as f:
    novos = json.load(f)

# Ubidots: token e device vêm de ubidots.json (fora do git). Sem ele, a aba fica desativada.
TAB_UB = PREFIXO + "000000000002"
ub = {}
try:
    with open(os.path.join(BASE, "ubidots.json")) as f:
        ub = json.load(f)
except FileNotFoundError:
    pass
token = str(ub.get("token", "")).strip()
device = str(ub.get("device", "irrigacao")).strip().lower()
if token and not re.fullmatch(r"[a-z0-9_-]{1,50}", device):
    sys.exit(f"ubidots.json: device {device!r} inválido (use letras minúsculas, números, _ ou -)")
novos = json.loads(json.dumps(novos).replace("__UBIDOTS_DEVICE__", device))
for n in novos:
    if n["id"] == TAB_UB:
        n["disabled"] = not token
    if n["type"] == "mqtt-broker" and n.get("name") == "Ubidots" and token:
        n["credentials"] = {"user": token, "password": ""}
print(f"Ubidots: device '{device}'" if token else
      "Ubidots: sem ubidots.json com token -> aba 'Ubidots' desativada")

# abas que contêm nós de GPIO da aula -> desativar (não apaga nada)
abas_gpio = {n["z"] for n in flows if n.get("type", "").startswith("rpi-gpio") and n.get("z")}
for n in flows:
    if n["type"] == "tab" and n["id"] in abas_gpio and not n.get("disabled"):
        n["disabled"] = True
        print("aba desativada:", n.get("label"))

# o dashboard v1 só aceita um ui_base; mantém o existente
mantidos = [n for n in flows if not n["id"].startswith(PREFIXO)]
if not any(n["type"] == "ui_base" for n in mantidos):
    novos.append({"id": PREFIXO + "ffffffffffff", "type": "ui_base", "theme": {"name": "theme-light"},
                  "site": {"name": "Irrigação", "hideToolbar": "false", "allowSwipe": "false",
                           "lockMenu": "false", "allowTempTheme": "true", "dateFormat": "DD/MM/YYYY",
                           "sizes": {"sx": 48, "sy": 48, "gx": 6, "gy": 6, "cx": 6, "cy": 6, "px": 0, "py": 0}}})

# coloca a aba de irrigação primeiro no menu do dashboard
for n in mantidos:
    if n["type"] == "ui_tab":
        n["order"] = int(n.get("order") or 1) + 1

res = req("POST", "/flows", {"rev": atual["rev"], "flows": mantidos + novos},
          {"Node-RED-Deployment-Type": "full"})
print("deploy ok, rev", res.get("rev") if res else "?")
sys.exit(0)
