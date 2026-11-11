#!/usr/bin/env python3
"""Gera fluxo_irrigacao.json (aba do Node-RED + dashboard v1 node-red-dashboard)."""
import hashlib
import json
import os

TAB = "a1a1000000000001"
nodes = []


def _id(type_, kw):
    """ID estável (prefixo a1a1 + hash do tipo/nome): inserir um nó novo não muda
    o ID dos outros, o que evitava erros do dashboard no deploy a quente."""
    chave = f"{type_}|{kw.get('name') or kw.get('label') or kw.get('title') or ''}"
    base = "a1a1" + hashlib.sha1(chave.encode()).hexdigest()[:12]
    i, nid = 0, base
    while any(n["id"] == nid for n in nodes):
        i += 1
        nid = "a1a1" + hashlib.sha1(f"{chave}|{i}".encode()).hexdigest()[:12]
    return nid


def node(type_, x=0, y=0, wires=None, z=TAB, **kw):
    n = {"id": _id(type_, kw), "type": type_, **kw}
    if z:
        n["z"] = z
        n["x"], n["y"] = x, y
    if wires is not None:
        n["wires"] = wires
    nodes.append(n)
    return n["id"]


# ------------------------------------------------------------ config
nodes.append({"id": TAB, "type": "tab", "label": "Irrigação", "disabled": False,
              "info": "Dashboard da irrigação. O controle roda no serviço Python "
                      "(~/irrigacao/irrigacao.py); aqui só MQTT + interface."})
broker = node("mqtt-broker", z=None, name="Mosquitto local", broker="localhost", port="1883",
              clientid="nodered-irrigacao", autoConnect=True, usetls=False, protocolVersion="4",
              keepalive="30", cleansession=True, autoUnsubscribe=True,
              birthTopic="", closeTopic="", willTopic="")
ui_tab = node("ui_tab", z=None, name="Irrigação", icon="fa-tint", order=1, disabled=False, hidden=False)


def grupo(nome, ordem, largura=6):
    return node("ui_group", z=None, name=nome, tab=ui_tab, order=ordem, disp=True,
                width=str(largura), collapse=False, className="")


g_sens = grupo("Sensores", 1)
g_bomba = grupo("Bomba e reservatório", 2)
g_hist = grupo("Histórico (última hora)", 3, 12)
g_diag = grupo("Diagnóstico", 4)
g_ajuda = grupo("Como funciona o modo automático", 5)

# ------------------------------------------------------------ saída de comandos
mqtt_out = node("mqtt out", 1150, 660, name="irrigacao/cmd", topic="irrigacao/cmd",
                qos="1", retain="false", broker=broker, wires=[])

# ------------------------------------------------------------ widgets de exibição
def gauge(nome, g, ordem, unidade, mn, mx, cores, segs, y):
    return node("ui_gauge", 760, y, group=g, order=ordem, width=3, height=3, gtype="gage",
                title=nome, label=unidade, format="{{value | number:1}}", min=mn, max=mx,
                colors=cores, seg1=segs[0], seg2=segs[1], name=nome, className="")


w_solo = gauge("Umidade do solo", g_sens, 1, "%", 0, 100, ["#ca3838", "#e6e600", "#00b500"], ["30", "60"], 40)
w_temp = gauge("Temperatura", g_sens, 2, "°C", 0, 50, ["#00b0f0", "#00b500", "#ca3838"], ["18", "32"], 80)
w_umid = gauge("Umidade do ar", g_sens, 3, "%", 0, 100, ["#e6e600", "#00b500", "#00b0f0"], ["40", "70"], 120)
w_chart = node("ui_chart", 760, 160, group=g_hist, order=1, width=12, height=6, label="",
               chartType="line", legend="true", xformat="HH:mm", interpolate="linear",
               nodata="Aguardando dados...", dot=False, ymin="0", ymax="100",
               removeOlder="1", removeOlderPoints="", removeOlderUnit="3600", cutout=0,
               useOneColor=False, useUTC=False,
               colors=["#1f77b4", "#2ca02c", "#d62728", "#ff7f0e", "#9467bd",
                       "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22"],
               outputs=1, useDifferentColor=False, className="", name="Histórico", wires=[[]])


def texto(rotulo, g, ordem, y, largura=6):
    return node("ui_text", 760, y, group=g, order=ordem, width=largura, height=1, name=rotulo,
                label=rotulo, format="{{msg.payload}}", layout="row-spread", className="",
                style=False, font="", fontSize="", color="#000000")


w_res = texto("Reservatório", g_bomba, 1, 200)
w_bomba = texto("Bomba", g_bomba, 2, 240)
w_motivo = texto("Situação", g_bomba, 3, 280)
w_online = texto("Serviço", g_diag, 1, 320)
w_diag = node("ui_template", 760, 360, group=g_diag, name="Detalhes", order=2, width=6, height=5,
              format=("<div style='font-size:13px;line-height:1.6'>"
                      "<div ng-repeat='l in msg.payload'>"
                      "<b>{{l[0]}}:</b> <span ng-style=\"{color: l[2] ? '#d62728' : 'inherit'}\">{{l[1]}}</span>"
                      "</div></div>"),
              storeOutMessages=True, fwdInMessages=False, resendOnRefresh=True,
              templateScope="local", className="", wires=[[]])

AJUDA = """
<div style="font-size:13px;line-height:1.55">
  <ol style="margin:0 0 8px 0;padding-left:18px">
    <li>Quando a umidade do solo fica <b>abaixo de {{msg.payload.limiar}} %</b>,
        a bomba <b>rega por {{msg.payload.tempo_rega}} s</b>.</li>
    <li>Depois, o sistema <b>espera {{msg.payload.tempo_espera < 60 ? msg.payload.tempo_espera + ' s'
        : (msg.payload.tempo_espera / 60 | number:0) + ' min'}}</b>
        para a água descer pela terra até a forquilha.
        Em <i>Situação</i> aparece <b>"aguardando infiltração"</b> com a contagem.</li>
    <li>Ao fim da espera, mede de novo: se ainda estiver seco, rega mais uma dose;
        se passou de {{msg.payload.limiar}} %, mostra <b>"solo úmido"</b> e não faz nada.</li>
  </ol>
  <div style="opacity:.85">
    <b>Por que esperar?</b> Logo após regar, a água ainda está na superfície e o solo
    parece seco para o sensor. Sem a pausa, o sistema regaria várias vezes seguidas e
    encharcaria o vaso.<br>
    Durante a contagem a bomba não liga no automático. Para ligar na hora,
    desligue o <b>Modo automático</b> e use <b>Ligar bomba</b>
    (rega {{msg.payload.tempo_max_manual}} s e desliga sozinha).
    A bomba nunca liga com o reservatório vazio.
  </div>
</div>
"""
w_ajuda = node("ui_template", 760, 400, group=g_ajuda, name="Como funciona", order=1, width=6,
               height=7, format=AJUDA.strip(), storeOutMessages=True, fwdInMessages=False,
               resendOnRefresh=True, templateScope="local", className="", wires=[[]])

# ------------------------------------------------------------ controles (entrada e saída)
wrap = {}


def wrap_cmd(chave, y):
    f = node("function", 960, y, name=f"cmd {chave}",
             func=f"msg.payload = {{ {json.dumps(chave)}: msg.payload }};\nreturn msg;",
             outputs=1, wires=[[mqtt_out]])
    return f


f_modo = wrap_cmd("modo", 420)
w_modo = node("ui_switch", 760, 420, name="Modo", label="Modo automático", tooltip="",
              group=g_bomba, order=4, width=6, height=1, passthru=False, decouple="true",
              topic="modo", topicType="str", style="", onvalue="auto", onvalueType="str",
              onicon="", oncolor="", offvalue="manual", offvalueType="str", officon="",
              offcolor="", animate=True, className="", wires=[[f_modo]])

def botao(rotulo, g, ordem, payload, y, cor="", largura=3):
    return node("ui_button", 760, y, name=rotulo, group=g, order=ordem, width=largura, height=1,
                passthru=False, label=rotulo, tooltip="", color="", bgcolor=cor, className="",
                icon="", payload=json.dumps(payload), payloadType="json", topic="", topicType="str",
                wires=[[mqtt_out]])


botao("Ligar bomba", g_bomba, 5, {"bomba": True}, 460, "#2e7d32")
botao("Desligar bomba", g_bomba, 6, {"bomba": False}, 500, "#c62828")

# Configuração (limiar, tempos, calibração, lógica da boia) fica fora da tela:
# edite por MQTT (irrigacao/cmd) — ver README.

# ------------------------------------------------------------ distribuição do estado
DISTRIB = r"""
const d = msg.payload;
const out = new Array(11).fill(null);
const ult = context.get('ult') || {};
// envia só quando muda (evita brigar com o usuário mexendo no controle)
function seMudou(i, chave, valor) {
    if (ult[chave] !== valor) { ult[chave] = valor; out[i] = { payload: valor }; }
}

if (!d || d.online === false) {
    out[9] = { payload: '🔴 OFFLINE (serviço parado)' };
    node.status({ fill: 'red', shape: 'ring', text: 'offline' });
    context.set('ult', ult);
    return out;
}
const fmt = (v, u) => (v === null || v === undefined) ? '—' : v.toFixed(1) + u;

if (d.solo_pct !== null) out[0] = { payload: d.solo_pct };
if (d.temp !== null) out[1] = { payload: d.temp };
if (d.umid_ar !== null) out[2] = { payload: d.umid_ar };

const pontos = [];
if (d.solo_pct !== null) pontos.push({ topic: 'Solo (%)', payload: d.solo_pct });
if (d.umid_ar !== null) pontos.push({ topic: 'Umid. ar (%)', payload: d.umid_ar });
if (d.temp !== null) pontos.push({ topic: 'Temp. (°C)', payload: d.temp });
pontos.push({ topic: 'Bomba (on=100)', payload: d.bomba ? 100 : 0 });
out[3] = pontos;

out[4] = { payload: d.tem_agua ? '💧 Com água' : '⚠️ VAZIO' };
out[5] = { payload: d.bomba ? `🟢 LIGADA (${d.bomba_seg} s)` : '⚪ Desligada' };
out[6] = { payload: d.motivo };

const c = d.cfg || {};
seMudou(7, 'modo', c.modo);
const ajuda = `${c.limiar}|${c.tempo_rega}|${c.tempo_espera}|${c.tempo_max_manual}`;
if (ult.ajuda !== ajuda) {
    ult.ajuda = ajuda;
    out[10] = { payload: { limiar: c.limiar, tempo_rega: c.tempo_rega, tempo_espera: c.tempo_espera,
                           tempo_max_manual: c.tempo_max_manual } };
}

const e = d.erros || {};
out[8] = { payload: [
    ['Tensão do solo (A0)', d.solo_v === null ? '—' : d.solo_v.toFixed(3) + ' V'],
    ['Calibração', `seco ${c.solo_seco_v} V · molhado ${c.solo_molhado_v} V`],
    ['Contato da boia', d.boia_fechada ? 'fechado' : 'aberto'],
    ['Temp / umid. ar', `${fmt(d.temp, ' °C')} / ${fmt(d.umid_ar, ' %')}`],
    ['ADS1115', e.ads ? 'ERRO: ' + e.ads : 'ok', !!e.ads],
    ['DHT22', e.dht ? 'ERRO: ' + e.dht
        : `ok · última leitura há ${d.dht_idade ?? '—'} s · ${d.dht_taxa}% das tentativas`, !!e.dht],
    ['Atualizado', new Date(d.ts).toLocaleTimeString('pt-BR')],
]};
out[9] = { payload: '🟢 online' };
node.status({ fill: d.bomba ? 'green' : 'grey', shape: 'dot',
              text: `solo ${fmt(d.solo_pct, '%')} · bomba ${d.bomba ? 'ON' : 'off'}` });
context.set('ult', ult);
return out;
"""

f_dist = node("function", 470, 300, name="Distribui estado", func=DISTRIB.strip(), outputs=11,
              timeout=0, noerr=0, initialize="", finalize="", libs=[],
              wires=[[w_solo], [w_temp], [w_umid], [w_chart], [w_res], [w_bomba], [w_motivo],
                     [w_modo], [w_diag], [w_online], [w_ajuda]])
node("mqtt in", 220, 300, name="irrigacao/estado", topic="irrigacao/estado", qos="1",
     datatype="json", broker=broker, nl=False, rap=True, rh=0, inputs=0, wires=[[f_dist]])

saida = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fluxo_irrigacao.json")
with open(saida, "w") as f:
    json.dump(nodes, f, indent=2, ensure_ascii=False)
print(f"{len(nodes)} nós -> {saida}")
