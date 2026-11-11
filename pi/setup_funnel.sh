#!/bin/bash
# Publica o Node-RED na internet com Tailscale Funnel (HTTPS, endereço fixo *.ts.net).
# Rodar na Pi DEPOIS de ligar a senha do Node-RED (node_red_senha.py):
#     sudo bash ~/irrigacao/setup_funnel.sh
set -euo pipefail

if [ ! -f /home/pi/.node-red/irrigacao-auth.js ]; then
    echo "ERRO: o Node-RED ainda está sem senha. Antes rode:"
    echo "    python3 ~/irrigacao/node_red_senha.py && sudo systemctl restart nodered"
    exit 1
fi

echo "== 1/3 Instalando o Tailscale (repositório oficial)"
if ! command -v tailscale >/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled

echo "== 2/3 Entrando na sua conta Tailscale"
if ! tailscale status >/dev/null 2>&1; then
    echo "Abra o link que aparecer abaixo e faça login (conta gratuita)."
    tailscale up --hostname=irrigacao
fi

echo "== 3/3 Ligando o Funnel na porta 1880 (Node-RED)"
if ! tailscale funnel --bg 1880; then
    echo
    echo "O Funnel ainda não está liberado na sua rede Tailscale."
    echo "Abra o link mostrado acima (ou https://login.tailscale.com/admin/settings/features),"
    echo "ative HTTPS e Funnel, e rode este script de novo."
    exit 1
fi

echo
tailscale funnel status
URL="https://$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
echo
echo "PRONTO. De qualquer lugar:"
echo "    Dashboard: $URL/ui   (usuário: irrigacao)"
echo "    Editor:    $URL/     (usuário: admin)"
echo "O Funnel continua ativo depois de reiniciar a Pi. Para desligar: sudo tailscale funnel reset"
