#!/usr/bin/env python3
"""Serviço de irrigação: lê sensores, controla a bomba e conversa via MQTT.

Hardware (ver sch.jpeg):
  ADS1115 em I2C-1, endereço 0x48, canal A0 = umidade do solo (SOLO_AO)
  DHT22 no GPIO4, lido pelo driver do kernel (dtoverlay=dht11,gpiopin=4)
  Boia no GPIO17 com pull-up interno (contato fechado = 0)
  Bomba no GPIO27 -> R1 -> base do TIP122 (1 = liga)

MQTT (broker local):
  irrigacao/estado  (retido)  JSON com todas as leituras e o estado
  irrigacao/cmd               JSON com comandos, por exemplo:
      {"modo": "auto" | "manual"}
      {"regar": true}                    (uma dose de tempo_rega s, qualquer modo)
      {"bomba": false}                   (para a bomba, qualquer modo)
      {"bomba": true}                    (liga contínuo, só no manual, até tempo_max_manual)
      {"limiar": 35}                     (% de umidade para regar no auto)
      {"tempo_rega": 10, "tempo_espera": 60, "tempo_max_manual": 60}
      {"calibrar": "seco" | "molhado"}   (grava a leitura atual do solo)
      {"boia_fechada_tem_agua": true | false}

Segurança:
  - a bomba nunca liga sem água no reservatório (boia);
  - no manual, desliga sozinha após tempo_max_manual segundos;
  - no auto, rega tempo_rega s e espera tempo_espera s para a água infiltrar;
  - se o serviço cair, o GPIO é liberado e o R2 de 10 kΩ mantém a bomba desligada.
"""

import glob
import json
import logging
import os
import signal
import threading
import time

import paho.mqtt.client as mqtt
from gpiozero import Button, DigitalOutputDevice
from smbus2 import SMBus

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")

PIN_BOIA = 17
PIN_BOMBA = 27
ADS_ADDR = 0x48
I2C_BUS = 1

T_ESTADO = 2.0  # s entre publicações
T_DHT = 5.0     # s entre leituras do DHT22 (mínimo 2 s)
DHT_TOLERANCIA = 30  # s sem leitura boa antes de mostrar erro
BOIA_FILTRO = 3.0    # s que a boia precisa ficar estável para mudar de estado
T_CONTROLE = 0.5     # s entre verificações da boia/bomba

TOPIC_ESTADO = "irrigacao/estado"
TOPIC_CMD = "irrigacao/cmd"

DEFAULT_CONFIG = {
    "modo": "manual",
    "limiar": 40,            # % — terra seca lê ~10–30 %, recém-regada ~60–90 %
    "tempo_rega": 10,        # s — AD20P ~4 L/min: 10 s ≈ até 650 mL por dose
    "tempo_espera": 30,      # s — pausa para a água infiltrar antes de medir de novo
    "tempo_max_manual": 10,  # s — "Ligar bomba" no manual também rega 10 s
    "solo_seco_v": 3.292,    # calibrado: forquilha seca no ar
    "solo_molhado_v": 1.468, # calibrado: forquilha na água
    "boia_fechada_tem_agua": True,
}

log = logging.getLogger("irrigacao")


# ---------------------------------------------------------------- config
def carregar_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    except Exception as e:  # arquivo corrompido: usa padrão
        log.warning("config.json inválido (%s), usando padrão", e)
    return cfg


def salvar_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


# ---------------------------------------------------------------- sensores
class ADS1115:
    """Leitura single-shot, ±4,096 V (GAIN=1), 128 SPS."""

    def __init__(self, bus=I2C_BUS, addr=ADS_ADDR):
        self.bus = SMBus(bus)
        self.addr = addr

    def tensao(self, canal=0):
        mux = 0b100 + canal  # AINx contra GND
        cfg = (1 << 15) | (mux << 12) | (0b001 << 9) | (1 << 8) | (0b100 << 5) | 0b11
        self.bus.write_i2c_block_data(self.addr, 0x01, [cfg >> 8, cfg & 0xFF])
        time.sleep(0.01)
        for _ in range(10):  # espera fim da conversão (bit OS)
            hi, lo = self.bus.read_i2c_block_data(self.addr, 0x01, 2)
            if hi & 0x80:
                break
            time.sleep(0.002)
        hi, lo = self.bus.read_i2c_block_data(self.addr, 0x00, 2)
        raw = (hi << 8) | lo
        if raw & 0x8000:
            raw -= 1 << 16
        return raw * 4.096 / 32768.0


class DHT22Kernel:
    """Lê o DHT22 pelo driver IIO do kernel (overlay dht11 aceita DHT22)."""

    def __init__(self):
        self.dir = None
        for d in glob.glob("/sys/bus/iio/devices/iio:device*"):
            try:
                with open(os.path.join(d, "name")) as f:
                    if "dht11" in f.read():
                        self.dir = d
                        break
            except OSError:
                pass

    def ler(self):
        if not self.dir:
            raise RuntimeError("driver dht11 não encontrado (overlay ativo? reiniciou?)")
        with open(os.path.join(self.dir, "in_temp_input")) as f:
            t = int(f.read()) / 1000.0
        with open(os.path.join(self.dir, "in_humidityrelative_input")) as f:
            h = int(f.read()) / 1000.0
        if not (-40 <= t <= 80 and 0 <= h <= 100):
            raise ValueError(f"leitura fora da faixa: {t} °C {h} %")
        return t, h


# ---------------------------------------------------------------- controle
class Irrigacao:
    def __init__(self):
        self.cfg = carregar_config()
        self.lock = threading.RLock()
        self.boia = Button(PIN_BOIA, pull_up=True, bounce_time=0.05)
        self.bomba = DigitalOutputDevice(PIN_BOMBA, active_high=True, initial_value=False)
        try:
            self.ads = ADS1115()
        except Exception as e:
            log.error("ADS1115: %s", e)
            self.ads = None
        self.dht = DHT22Kernel()
        self._agua_estavel = self._agua_ult_bruta = self.agua_bruta()
        self._agua_t_mudou = time.monotonic()

        self.solo_v = None
        self.temp = None
        self.umid_ar = None
        self.t_dht_ok = 0.0
        self.t_inicio = time.monotonic()
        self.dht_ok = 0
        self.dht_falhas = 0
        self.erros = {}
        self.bomba_desde = None
        self.motivo = "parada"
        self.espera_ate = 0.0       # fim da espera de infiltração (auto)
        self.rega_ate = 0.0         # fim do ciclo de rega (auto)

        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="irrigacao-py")
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_message = self._on_message
        self.mqtt.on_disconnect = self._on_disconnect
        self.mqtt.will_set(TOPIC_ESTADO, json.dumps({"online": False}), retain=True)

    # ------------------------------------------------ leituras
    def agua_bruta(self):
        fechado = self.boia.is_pressed  # contato fechado puxa o GPIO a 0
        return fechado if self.cfg["boia_fechada_tem_agua"] else not fechado

    def tem_agua(self):
        """Estado da boia filtrado: só muda se a leitura ficar estável BOIA_FILTRO s.

        A água agitada pela bomba (ou ruído da partida do motor) faz a boia
        oscilar por instantes; sem o filtro a trava cortava a bomba na partida.
        """
        agora = time.monotonic()
        bruta = self.agua_bruta()
        if bruta != self._agua_ult_bruta:
            self._agua_ult_bruta = bruta
            self._agua_t_mudou = agora
        if bruta != self._agua_estavel and agora - self._agua_t_mudou >= BOIA_FILTRO:
            self._agua_estavel = bruta
            log.info("boia: %s", "com água" if bruta else "SEM ÁGUA")
        return self._agua_estavel

    def solo_pct(self):
        if self.solo_v is None:
            return None
        seco, molhado = self.cfg["solo_seco_v"], self.cfg["solo_molhado_v"]
        if abs(seco - molhado) < 0.05:
            return None
        pct = (seco - self.solo_v) / (seco - molhado) * 100.0
        return round(max(0.0, min(100.0, pct)), 1)

    def ler_sensores(self):
        """Chamado SEM a trava: o I2C pode demorar se o ADS não responder."""
        v, erro = None, None
        if self.ads:
            try:
                # média de 4 leituras para reduzir ruído
                v = sum(self.ads.tensao(0) for _ in range(4)) / 4
            except Exception as e:
                erro = str(e) or type(e).__name__
        else:
            erro = "ADS1115 não inicializado"
        with self.lock:
            self.solo_v = v
            if erro:
                self.erros["ads"] = erro
            else:
                self.erros.pop("ads", None)
            if time.monotonic() - self.t_dht_ok > 60:  # dado velho demais
                self.temp = self.umid_ar = None

    def laco_dht(self, parar):
        """Thread própria: a leitura do DHT pode bloquear ~1 s no kernel.

        Na Pi 4 o driver do kernel falha em ~50% das leituras (interrupções
        atrapalham a temporização de µs). Valores com checksum errado são
        descartados, então só reportamos erro se ficar muito tempo sem leitura boa.
        """
        while not parar.is_set():
            try:
                t, h = self.dht.ler()
                with self.lock:
                    self.temp, self.umid_ar = t, h
                    self.t_dht_ok = time.monotonic()
                    self.dht_ok += 1
                    self.erros.pop("dht", None)
                parar.wait(T_DHT)
            except Exception as e:
                with self.lock:
                    self.dht_falhas += 1
                    if time.monotonic() - max(self.t_dht_ok, self.t_inicio) > DHT_TOLERANCIA:
                        self.erros["dht"] = f"sem leitura há mais de {DHT_TOLERANCIA} s ({e})"
                parar.wait(2.5)  # DHT22 exige >= 2 s entre leituras

    # ------------------------------------------------ bomba
    def _ligar(self, motivo):
        if not self.bomba.value:
            self.bomba.on()
            self.bomba_desde = time.monotonic()
            log.info("bomba LIGADA (%s)", motivo)
        self.motivo = motivo

    def _desligar(self, motivo):
        if self.bomba.value:
            self.bomba.off()
            log.info("bomba DESLIGADA (%s)", motivo)
        self.bomba_desde = None
        self.motivo = motivo

    def controlar(self):
        agora = time.monotonic()
        agua = self.tem_agua()
        ligada = bool(self.bomba.value)

        if ligada and not agua:
            self._desligar("sem água no reservatório")
            self.rega_ate = 0
            return

        if self.cfg["modo"] == "manual":
            if ligada and self.rega_ate and agora >= self.rega_ate:
                self._desligar("rega concluída")
                self.rega_ate = 0
            elif ligada and agora - self.bomba_desde >= self.cfg["tempo_max_manual"]:
                self._desligar("tempo máximo do manual")
            elif not ligada and not agua:
                self.motivo = "sem água no reservatório"
            elif not ligada and "sem água" in self.motivo:
                self.motivo = "parada (água ok)"  # a água voltou
            return

        # modo automático
        pct = self.solo_pct()
        if ligada:
            if agora >= self.rega_ate:
                self._desligar("fim do ciclo de rega")
                self.espera_ate = agora + self.cfg["tempo_espera"]
            return
        if pct is None:
            self.motivo = "auto: sem leitura do solo"
        elif not agua:
            self.motivo = "auto: sem água no reservatório"
        elif agora < self.espera_ate:
            self.motivo = f"auto: aguardando infiltração ({int(self.espera_ate - agora)} s)"
        elif pct < self.cfg["limiar"]:
            self.rega_ate = agora + self.cfg["tempo_rega"]
            self._ligar(f"auto: solo {pct}% < {self.cfg['limiar']}%")
        else:
            self.motivo = "auto: solo úmido"

    # ------------------------------------------------ MQTT
    def _on_connect(self, client, userdata, flags, rc, props=None):
        log.info("MQTT conectado (%s)", rc)
        client.subscribe(TOPIC_CMD)
        self.publicar()

    def _on_disconnect(self, client, userdata, flags, rc, props=None):
        log.warning("MQTT desconectado (%s)", rc)
        with self.lock:
            if self.cfg["modo"] == "manual":
                self._desligar("MQTT desconectado")

    def _on_message(self, client, userdata, msg):
        try:
            cmd = json.loads(msg.payload.decode() or "{}")
            if not isinstance(cmd, dict):
                raise ValueError("comando deve ser um objeto JSON")
        except Exception as e:
            log.warning("comando inválido %r: %s", msg.payload, e)
            return
        with self.lock:
            self.aplicar(cmd)
        self.publicar()

    def aplicar(self, cmd):
        log.info("comando: %s", cmd)
        mudou = False
        if cmd.get("modo") in ("auto", "manual") and cmd["modo"] != self.cfg["modo"]:
            self.cfg["modo"] = cmd["modo"]
            self._desligar(f"modo {cmd['modo']}")
            self.espera_ate = self.rega_ate = 0
            mudou = True
        for k, lo, hi in (("limiar", 0, 100), ("tempo_rega", 1, 300),
                          ("tempo_espera", 0, 3600), ("tempo_max_manual", 1, 600)):
            if k in cmd:
                try:
                    v = float(cmd[k])
                except (TypeError, ValueError):
                    continue
                self.cfg[k] = max(lo, min(hi, v))
                mudou = True
        # tempos novos valem também para a contagem/rega que já está em andamento
        agora = time.monotonic()
        if "tempo_espera" in cmd and self.espera_ate:
            self.espera_ate = min(self.espera_ate, agora + self.cfg["tempo_espera"])
        if "tempo_rega" in cmd and self.rega_ate and self.bomba.value:
            self.rega_ate = min(self.rega_ate, agora + self.cfg["tempo_rega"])
        if "boia_fechada_tem_agua" in cmd:
            self.cfg["boia_fechada_tem_agua"] = bool(cmd["boia_fechada_tem_agua"])
            mudou = True
        if cmd.get("calibrar") in ("seco", "molhado") and self.solo_v is not None:
            self.cfg[f"solo_{cmd['calibrar']}_v"] = round(self.solo_v, 3)
            mudou = True
        if cmd.get("regar"):
            # uma dose de rega (tempo_rega s) em qualquer modo, respeitando a boia
            if self.tem_agua():
                self.rega_ate = time.monotonic() + self.cfg["tempo_rega"]
                self._ligar("regando (pedido manual)")
            else:
                self.motivo = "sem água no reservatório, rega bloqueada"
        if "bomba" in cmd:
            if not cmd["bomba"]:
                # parar é sempre permitido; no auto, respeita a espera antes de regar de novo
                self._desligar("parada pelo usuário")
                self.rega_ate = 0
                if self.cfg["modo"] == "auto":
                    self.espera_ate = time.monotonic() + self.cfg["tempo_espera"]
            elif self.cfg["modo"] != "manual":
                self.motivo = "no automático, use 'Regar agora'"
            elif self.tem_agua():
                self.rega_ate = 0  # liga contínuo, limitado por tempo_max_manual
                self._ligar("manual")
            else:
                self.motivo = "sem água no reservatório, bomba bloqueada"
        if mudou:
            salvar_config(self.cfg)

    def estado(self):
        ligada = bool(self.bomba.value)
        return {
            "online": True,
            "ts": int(time.time() * 1000),
            "solo_v": None if self.solo_v is None else round(self.solo_v, 3),
            "solo_pct": self.solo_pct(),
            "temp": self.temp,
            "umid_ar": self.umid_ar,
            "dht_idade": int(time.monotonic() - self.t_dht_ok) if self.t_dht_ok else None,
            "dht_taxa": round(100 * self.dht_ok / max(1, self.dht_ok + self.dht_falhas)),
            "boia_fechada": self.boia.is_pressed,
            "tem_agua": self.tem_agua(),
            "bomba": ligada,
            "bomba_seg": int(time.monotonic() - self.bomba_desde) if ligada and self.bomba_desde else 0,
            "motivo": self.motivo,
            "erros": self.erros,
            "cfg": self.cfg,
        }

    def publicar(self):
        with self.lock:
            payload = json.dumps(self.estado(), ensure_ascii=False)
        self.mqtt.publish(TOPIC_ESTADO, payload, retain=True)

    # ------------------------------------------------ laço principal
    def rodar(self):
        parar = threading.Event()
        signal.signal(signal.SIGTERM, lambda *a: parar.set())
        signal.signal(signal.SIGINT, lambda *a: parar.set())
        # a boia age na hora, sem esperar o próximo ciclo
        self.boia.when_pressed = self.boia.when_released = self._boia_mudou

        self.mqtt.reconnect_delay_set(1, 10)
        self.mqtt.connect_async("localhost", 1883, keepalive=30)
        self.mqtt.loop_start()
        threading.Thread(target=self.laco_dht, args=(parar,), daemon=True).start()
        threading.Thread(target=self.laco_controle, args=(parar,), daemon=True).start()
        try:
            while not parar.is_set():
                self.ler_sensores()
                with self.lock:
                    self.controlar()
                self.publicar()
                parar.wait(T_ESTADO)
        finally:
            self.bomba.off()
            self.mqtt.publish(TOPIC_ESTADO, json.dumps({"online": False}), retain=True)
            self.mqtt.loop_stop()
            self.mqtt.disconnect()
            log.info("encerrado, bomba desligada")

    def laco_controle(self, parar):
        """Reavalia boia/bomba a cada T_CONTROLE s (o filtro da boia depende disso)
        e publica na hora quando a bomba ou a água mudam de estado."""
        while not parar.is_set():
            with self.lock:
                antes = (bool(self.bomba.value), self._agua_estavel)
                self.controlar()
                depois = (bool(self.bomba.value), self._agua_estavel)
            if antes != depois:
                self.publicar()
            parar.wait(T_CONTROLE)

    def _boia_mudou(self):
        with self.lock:
            self.controlar()
        self.publicar()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Irrigacao().rodar()
