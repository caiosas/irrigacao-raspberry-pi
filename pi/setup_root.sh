#!/bin/bash
# Configuração que precisa de root. Rodar uma vez:  sudo bash ~/irrigacao/setup_root.sh
set -euo pipefail
CFG=/boot/firmware/config.txt
cd /home/pi/irrigacao

echo "== 1/6 Habilitando I2C"
raspi-config nonint do_i2c 0

echo "== 2/6 Driver do DHT22 no GPIO4"
if ! grep -q '^dtoverlay=dht11' "$CFG"; then
    cp "$CFG" "$CFG.bak-irrigacao"
    printf '\n[all]\n# Irrigacao: DHT22 no GPIO4 (driver do kernel)\ndtoverlay=dht11,gpiopin=4\n' >> "$CFG"
fi

echo "== 3/6 Instalando broker MQTT e paho-mqtt"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mosquitto mosquitto-clients python3-paho-mqtt
cat > /etc/mosquitto/conf.d/irrigacao.conf <<'EOF'
# Broker só para uso local (serviço Python <-> Node-RED)
listener 1883 localhost
allow_anonymous true
EOF
systemctl enable --now mosquitto
systemctl restart mosquitto

echo "== 4/6 Serviço de irrigação"
install -m 644 irrigacao.service /etc/systemd/system/irrigacao.service
systemctl daemon-reload
systemctl enable irrigacao

echo "== 5/6 Node-RED na inicialização"
systemctl enable nodered

echo "== 6/6 Permitir reiniciar só estes serviços sem senha"
cat > /etc/sudoers.d/020_irrigacao <<'EOF'
pi ALL=(root) NOPASSWD: /usr/bin/systemctl start irrigacao, /usr/bin/systemctl stop irrigacao, /usr/bin/systemctl restart irrigacao, /usr/bin/systemctl start nodered, /usr/bin/systemctl stop nodered, /usr/bin/systemctl restart nodered, /usr/bin/systemctl restart mosquitto, /usr/sbin/reboot
EOF
chmod 440 /etc/sudoers.d/020_irrigacao
visudo -cf /etc/sudoers.d/020_irrigacao

echo
echo "PRONTO. Reiniciando em 5 s para ativar I2C e DHT22..."
sleep 5
reboot
