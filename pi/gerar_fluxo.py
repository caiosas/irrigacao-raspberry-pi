#!/usr/bin/env python3
"""Gera fluxo_irrigacao.json (aba do Node-RED + dashboard v1 node-red-dashboard)."""
import json
import os

TAB = "a1a1000000000001"
nid = iter(f"a1a1{i:012x}" for i in range(2, 1000))
nodes = []


def node(type_, x=0, y=0, wires=None, z=TAB, **kw):
    n = {"id": next(nid), "type": type_, **kw}
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
g_cfg = grupo("Configuração", 4)
g_diag = grupo("Diagnóstico", 5)

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

f_lim = wrap_cmd("limiar", 540)
w_lim = node("ui_slider", 760, 540, name="Limiar", label="Regar abaixo de (%)", tooltip="",
             group=g_cfg, order=1, width=6, height=1, passthru=False, outs="end", topic="limiar",
             topicType="str", min="5", max="90", step="1", className="", wires=[[f_lim]])


def numero(rotulo, chave, ordem, mn, mx, y):
    f = wrap_cmd(chave, y)
    return node("ui_numeric", 760, y, name=rotulo, label=rotulo, tooltip="", group=g_cfg,
                order=ordem, width=6, height=1, wrap=False, passthru=False, topic=chave,
                topicType="str", format="{{value}}", min=mn, max=mx, step=5, className="",
                wires=[[f]])


w_trega = numero("Tempo de rega (s)", "tempo_rega", 2, 5, 300, 580)
w_tesp = numero("Espera p/ infiltrar (s)", "tempo_espera", 3, 0, 1800, 620)
w_tmax = numero("Máx. manual (s)", "tempo_max_manual", 4, 5, 600, 660)

f_boia = wrap_cmd("boia_fechada_tem_agua", 700)
w_boia = node("ui_switch", 760, 700, name="Lógica da boia", label="Contato fechado = tem água",
              tooltip="Inverta se o reservatório aparecer vazio com água",
              group=g_cfg, order=5, width=6, height=1, passthru=False, decouple="true",
              topic="boia", topicType="str", style="", onvalue="true", onvalueType="bool",
              onicon="", oncolor="", offvalue="false", offvalueType="bool", officon="",
              offcolor="", animate=True, className="", wires=[[f_boia]])

botao("Calibrar: SECO", g_cfg, 6, {"calibrar": "seco"}, 740, "#8d6e63")
botao("Calibrar: MOLHADO", g_cfg, 7, {"calibrar": "molhado"}, 780, "#1565c0")

# ------------------------------------------------------------ distribuição do estado
DISTRIB = r"""
const d = msg.payload;
const out = new Array(15).fill(null);
const ult = context.get('ult') || {};
// envia só quando muda (evita brigar com o usuário mexendo no controle)
function seMudou(i, chave, valor) {
    if (ult[chave] !== valor) { ult[chave] = valor; out[i] = { payload: valor }; }
}

if (!d || d.online === false) {
    out[14] = { payload: '🔴 OFFLINE (serviço parado)' };
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
seMudou(8, 'limiar', c.limiar);
seMudou(9, 'tempo_rega', c.tempo_rega);
seMudou(10, 'tempo_espera', c.tempo_espera);
seMudou(11, 'tempo_max_manual', c.tempo_max_manual);
seMudou(12, 'boia', c.boia_fechada_tem_agua);

const e = d.erros || {};
out[13] = { payload: [
    ['Tensão do solo (A0)', d.solo_v === null ? '—' : d.solo_v.toFixed(3) + ' V'],
    ['Calibração', `seco ${c.solo_seco_v} V · molhado ${c.solo_molhado_v} V`],
    ['Contato da boia', d.boia_fechada ? 'fechado' : 'aberto'],
    ['Temp / umid. ar', `${fmt(d.temp, ' °C')} / ${fmt(d.umid_ar, ' %')}`],
    ['ADS1115', e.ads ? 'ERRO: ' + e.ads : 'ok', !!e.ads],
    ['DHT22', e.dht ? 'ERRO: ' + e.dht
        : `ok · última leitura há ${d.dht_idade ?? '—'} s · ${d.dht_taxa}% das tentativas`, !!e.dht],
    ['Atualizado', new Date(d.ts).toLocaleTimeString('pt-BR')],
]};
out[14] = { payload: '🟢 online' };
node.status({ fill: d.bomba ? 'green' : 'grey', shape: 'dot',
              text: `solo ${fmt(d.solo_pct, '%')} · bomba ${d.bomba ? 'ON' : 'off'}` });
context.set('ult', ult);
return out;
"""

f_dist = node("function", 470, 300, name="Distribui estado", func=DISTRIB.strip(), outputs=15,
              timeout=0, noerr=0, initialize="", finalize="", libs=[],
              wires=[[w_solo], [w_temp], [w_umid], [w_chart], [w_res], [w_bomba], [w_motivo],
                     [w_modo], [w_lim], [w_trega], [w_tesp], [w_tmax], [w_boia], [w_diag],
                     [w_online]])
node("mqtt in", 220, 300, name="irrigacao/estado", topic="irrigacao/estado", qos="1",
     datatype="json", broker=broker, nl=False, rap=True, rh=0, inputs=0, wires=[[f_dist]])

saida = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fluxo_irrigacao.json")
with open(saida, "w") as f:
    json.dump(nodes, f, indent=2, ensure_ascii=False)
print(f"{len(nodes)} nós -> {saida}")
