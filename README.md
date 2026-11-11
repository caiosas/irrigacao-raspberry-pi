# Irrigação automática — Raspberry Pi 4 + Node-RED

Sistema de irrigação para a disciplina de microcontroladores. A Raspberry Pi 4 lê a umidade do solo, a temperatura e a umidade do ar e o nível do reservatório. Com essas leituras ela aciona uma bomba de 12 V, sozinha (modo automático) ou pelo dashboard do Node-RED (modo manual).

![Dashboard](docs/dashboard.jpg)

## Acesso rápido

| O quê | Endereço |
|---|---|
| **SSH** | `ssh pi@10.33.133.22` (ou `ssh pi@raspberrypi.local`) |
| **Dashboard** | http://10.33.133.22:1880/ui |
| **Editor do Node-RED** | http://10.33.133.22:1880 |

### Rede Wi-Fi

A Pi e o computador ou celular que acessa o dashboard precisam estar na **mesma rede**:

| | |
|---|---|
| **Rede (SSID)** | `CP-DET` |
| **Senha** | `Ywp2ENp5vlmgZXBLMX44` |

> O IP **10.33.133.22** é atribuído por DHCP e pode mudar.
> Se não responder, tente `raspberrypi.local`. Também dá para procurar a Pi na rede com
> `nmap -sn 10.33.133.0/24` e ver os MACs que começam com `2c:cf:67` (Raspberry Pi).
> O acesso é por chave SSH. O `sudo` pede senha, exceto para reiniciar os serviços do projeto (veja [Operação](#operação)).

## Hardware

O esquema completo está em [`sch.jpeg`](sch.jpeg). Ele usa duas fontes (USB-C da Pi + 12 V da bomba), não tem conversor buck e todos os GNDs são comuns.

| Componente | Ligação na Pi (pino **físico**) | Observação |
|---|---|---|
| Alimentação 3,3 V | 1 (3V3) | ADS1115, plaquinha do solo, DHT22 |
| GND comum | 6 | inclui o negativo da fonte de 12 V |
| ADS1115 (I²C) | 3 (SDA) · 5 (SCL) | ADDR no GND → endereço `0x48`; A0 = umidade do solo |
| Sonda de solo (forquilha + plaquinha) | A0 do ADS1115 | plaquinha em 3,3 V; DO livre |
| DHT22 | 7 (GPIO4) | pull-up R3 = 4,7 kΩ, C1 = 100 nF |
| Boia (contato seco) | 11 (GPIO17) | pull-up interno; contato fechado = 0 |
| Bomba 12 V via TIP122 | 13 (GPIO27) | R1 = 330 Ω na base, R2 = 10 kΩ base→GND, diodo 1N5822 em paralelo com a bomba |

Os pinos físicos 2 e 4 (5 V) **ficam livres**.

## Arquitetura

```mermaid
flowchart LR
    subgraph Pi["Raspberry Pi 4"]
        S["irrigacao.py<br/>(serviço systemd)"]
        M[("Mosquitto<br/>localhost:1883")]
        N["Node-RED<br/>dashboard :1880/ui"]
        S -- "irrigacao/estado" --> M --> N
        N -- "irrigacao/cmd" --> M --> S
    end
    ADS["ADS1115<br/>(solo)"] -- I²C --> S
    DHT["DHT22"] -- "GPIO4<br/>driver do kernel" --> S
    B["Boia"] -- GPIO17 --> S
    S -- GPIO27 --> T["TIP122 → bomba 12 V"]
```

- **`irrigacao.py`** é o "cérebro": lê os sensores, decide quando regar e controla a bomba. **As travas de segurança ficam aqui**, não no dashboard, então valem mesmo se o Node-RED cair.
- **Node-RED** é só a interface: mostra os dados e envia comandos via MQTT.
- **DHT22** é lido pelo driver do kernel (`dtoverlay=dht11,gpiopin=4`, que também atende o DHT22). Isso dispensa bibliotecas Python de bit-banging.
- **ADS1115** é lido direto por `smbus2`, em single-shot, com ganho ±4,096 V e média de 4 amostras.

### Segurança da bomba

- A bomba **nunca liga sem água** no reservatório (boia), e desliga se a água acabar. A boia é verificada a cada 0,5 s e só muda de estado depois de **3 s estável**. Sem esse filtro, a água agitada pela própria bomba balançava o flutuador e cortava a bomba na partida.
- **Modo manual:** a bomba desliga sozinha após `tempo_max_manual` segundos. Também desliga se a conexão MQTT cair.
- **Modo automático:** quando o solo fica abaixo do `limiar`, a bomba rega por `tempo_rega` s e depois espera `tempo_espera` s para a água infiltrar antes de medir de novo.
- Se o serviço parar ou travar, o GPIO27 é liberado e o **R2 de 10 kΩ** mantém a base do TIP122 em 0, ou seja, a bomba fica desligada.

## MQTT

| Tópico | Direção | Conteúdo |
|---|---|---|
| `irrigacao/estado` | Pi → dashboard (retido, a cada ~2 s) | JSON com `solo_v`, `solo_pct`, `temp`, `umid_ar`, `tem_agua`, `bomba`, `motivo`, `erros`, `cfg`… |
| `irrigacao/cmd` | dashboard → Pi | JSON com um ou mais comandos (abaixo) |

```jsonc
{"modo": "auto"}                 // ou "manual"
{"bomba": true}                  // só no manual; bloqueado sem água
{"limiar": 35}                   // % de umidade do solo para regar
{"tempo_rega": 10, "tempo_espera": 60, "tempo_max_manual": 60}
{"calibrar": "seco"}             // ou "molhado": grava a tensão atual do solo
{"boia_fechada_tem_agua": true}  // inverte a lógica da boia
```

Teste pelo terminal da Pi:

```bash
mosquitto_sub -h localhost -t irrigacao/estado -C 1     # ver estado
mosquitto_pub -h localhost -t irrigacao/cmd -m '{"modo":"manual"}'
```

A configuração fica salva em `~/irrigacao/config.json` (modelo em [`pi/config.example.json`](pi/config.example.json)).

## Calibração da umidade do solo

A plaquinha entrega **tensão alta com o solo seco** e **baixa com o solo molhado**. O percentual é calculado linearmente entre as duas tensões de referência:

| Referência | Tensão calibrada |
|---|---|
| Seco (forquilha seca, no ar) | 3,292 V → 0 % |
| Molhado (forquilha na água) | 1,468 V → 100 % |

O dashboard não tem botões de configuração. Para recalibrar, coloque a forquilha na condição desejada e rode na Pi:

```bash
mosquitto_pub -h localhost -t irrigacao/cmd -m '{"calibrar":"seco"}'     # forquilha seca/no ar
mosquitto_pub -h localhost -t irrigacao/cmd -m '{"calibrar":"molhado"}'  # forquilha na água
```

O painel *Diagnóstico* mostra a tensão do A0 em tempo real.

## Valores de controle

| Parâmetro | Valor | Motivo |
|---|---|---|
| `limiar` | 40 % | terra seca lê ~10–30 %, recém-regada ~60–90 % |
| `tempo_rega` | 5 s | a AD20P bombeia até ~4 L/min: 5 s ≈ até 300 mL por dose |
| `tempo_espera` | 300 s | a água leva minutos para chegar até a forquilha |
| `tempo_max_manual` | 30 s | limite de segurança do botão "Ligar bomba" no manual |

Para mudar um valor: `mosquitto_pub -h localhost -t irrigacao/cmd -m '{"limiar": 45}'`.

## Instalação do zero

Testado em Raspberry Pi OS / Debian 13 (trixie), com Node-RED 5 e `node-red-dashboard` 3.6 já instalados.

```bash
# no notebook: copiar os arquivos
ssh pi@10.33.133.22 'mkdir -p ~/irrigacao'
scp pi/* pi@10.33.133.22:irrigacao/

# na Pi: tudo que precisa de root (I2C, overlay do DHT22, mosquitto,
# serviço systemd, Node-RED no boot, sudoers restrito). Reinicia no fim.
sudo bash ~/irrigacao/setup_root.sh

# na Pi, depois do reboot: instalar a aba "Irrigação" no Node-RED
cd ~/irrigacao && python3 instalar_fluxo.py
```

`instalar_fluxo.py` usa a Admin API do Node-RED. Antes de alterar qualquer coisa ele salva um backup dos fluxos (`backup_flows_*.json`). Ele **desativa** (sem apagar) as abas antigas que usam `rpi-gpio`, porque uma delas usava o pino físico 3, que é o SDA do ADS1115.

Para alterar o dashboard, edite `pi/gerar_fluxo.py`, rode `python3 pi/gerar_fluxo.py` para gerar `fluxo_irrigacao.json`, copie para a Pi e rode `instalar_fluxo.py` de novo.

## Operação

```bash
sudo systemctl restart irrigacao     # sem senha (regra em /etc/sudoers.d/020_irrigacao)
sudo systemctl restart nodered       # sem senha
journalctl -u irrigacao -f           # log do serviço (bomba liga/desliga, comandos)
/usr/sbin/i2cdetect -y 1             # deve mostrar 48
cat /sys/bus/iio/devices/iio:device0/in_temp_input   # DHT22 em m°C
pinctrl get 4,17,27                  # estado dos pinos
```

## Arquivos

| Arquivo | Função |
|---|---|
| `pi/irrigacao.py` | serviço: sensores, controle, segurança, MQTT |
| `pi/irrigacao.service` | unidade systemd (roda como `pi`) |
| `pi/setup_root.sh` | configuração única com root |
| `pi/gerar_fluxo.py` | gera o fluxo do Node-RED (`fluxo_irrigacao.json`) |
| `pi/instalar_fluxo.py` | instala o fluxo via Admin API (com backup) |
| `pi/config.example.json` | configuração de exemplo |
| `sch.jpeg` | esquema elétrico |

## Problemas encontrados na montagem (e diagnóstico)

- **Nenhum sensor respondia:** o 3,3 V e/ou o GND não chegavam à placa. Pistas usadas: `i2cdetect` vazio, DHT22 com *timeout*, GPIO4 em 0 mesmo com o pull-up externo e a boia sempre em 1.
- **A0 fixo em 0,004 V** enquanto A1–A3 (soltos) davam ~0,91 V: o fio do AO estava ligado, mas a plaquinha do solo estava sem alimentação.
- **DHT22 com erro intermitente:** na Pi 4, o driver do kernel falha em ~50 % das leituras, porque interrupções atrapalham a temporização de microssegundos. As leituras que passam são válidas (o checksum é conferido). O serviço respeita ≥ 2 s entre tentativas e só reporta erro após 30 s sem nenhuma leitura boa.
- **A bomba era cortada na partida:** a boia oscilava por frações de segundo logo que o motor ligava (flutuador balançando com a água agitada e/ou ruído da partida). Resolvido com o filtro de 3 s. Se ainda houver ruído, dá para pôr um capacitor de 100 nF entre o GPIO17 e o GND e afastar o fio da boia dos fios da bomba.
- Boia e forquilha **não têm polaridade**. A plaquinha do solo, o DHT22 e o ADS1115 **têm** (VCC/GND).

## Pendências

- [ ] Calibração "molhado" da sonda de solo
- [ ] Confirmar a lógica da boia (contato fechado = reservatório cheio?)
- [ ] Teste da bomba com 12 V (com o diodo 1N5822 instalado e a bomba submersa)
- [ ] Medir a corrente de partida da bomba. Se passar de ~2 A, rever R1 ou trocar o TIP122 por um MOSFET logic-level
