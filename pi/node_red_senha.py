#!/usr/bin/env python3
"""Liga a senha do Node-RED (editor e dashboard) antes de publicar na internet.

    python3 ~/irrigacao/node_red_senha.py        # rodar como pi (não precisa de sudo)

- editor  (http://.../)    -> adminAuth    (usuário "admin")
- dashboard (http://.../ui) -> httpNodeAuth (usuário "irrigacao")
As senhas ficam só como hash bcrypt em ~/.node-red/irrigacao-auth.js.
O settings.js ganha duas linhas que leem esse arquivo (backup em settings.js.bak-irrigacao).
Rodar de novo troca as senhas. Depois: sudo systemctl restart nodered
"""
import getpass
import os
import re
import shutil
import sys

try:
    import bcrypt
except ImportError:
    sys.exit("Falta o bcrypt para Python:  sudo apt install -y python3-bcrypt")

DIR = os.path.expanduser("~/.node-red")
SETTINGS = os.path.join(DIR, "settings.js")
AUTH = os.path.join(DIR, "irrigacao-auth.js")
MARCA = "// irrigacao: senha (node_red_senha.py)"
LINHAS = (f"    {MARCA}\n"
          "    adminAuth: require('./irrigacao-auth.js').adminAuth,\n"
          "    httpNodeAuth: require('./irrigacao-auth.js').httpNodeAuth,\n")


def pedir(rotulo):
    while True:
        s1 = getpass.getpass(f"Senha do {rotulo} (mín. 8 caracteres): ")
        if len(s1) < 8:
            print("  muito curta")
            continue
        if getpass.getpass("  repita: ") == s1:
            return s1
        print("  não confere, de novo")


def hash_(senha):
    # prefixo 2a: o formato que o Node-RED (bcryptjs) usa nos exemplos
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt(rounds=10, prefix=b"2a")).decode()


def inserir_no_settings(txt):
    """Coloca as duas linhas logo depois de 'module.exports = {'."""
    if MARCA in txt:
        return txt  # já inserido antes
    # uma chave adminAuth/httpNodeAuth não comentada, mais abaixo, sobrescreveria a nossa
    for chave in ("adminAuth", "httpNodeAuth"):
        if re.search(rf"^\s*{chave}\s*:", txt, re.M):
            sys.exit(f"{SETTINGS} já tem '{chave}:' ativo. Comente essa parte e rode de novo.")
    m = re.search(r"module\.exports\s*=\s*\{[^\n]*\n", txt)
    if not m:
        sys.exit(f"Não achei 'module.exports = {{' em {SETTINGS}.")
    return txt[:m.end()] + LINHAS + txt[m.end():]


def main():
    if not os.path.exists(SETTINGS):
        sys.exit(f"Não achei {SETTINGS}. O Node-RED já rodou alguma vez como este usuário?")
    print("O editor fica com o usuário 'admin'; o dashboard (/ui), com 'irrigacao'.")
    s_editor = pedir("EDITOR (admin)")
    s_dash = pedir("DASHBOARD (irrigacao)")

    conteudo = (
        "// Gerado por node_red_senha.py. Só hashes bcrypt, nunca a senha.\n"
        "module.exports = {\n"
        "    adminAuth: {\n"
        "        type: 'credentials',\n"
        f"        users: [{{ username: 'admin', password: '{hash_(s_editor)}', permissions: '*' }}],\n"
        "    },\n"
        f"    httpNodeAuth: {{ user: 'irrigacao', pass: '{hash_(s_dash)}' }},\n"
        "};\n")
    with open(AUTH, "w") as f:
        f.write(conteudo)
    os.chmod(AUTH, 0o600)

    with open(SETTINGS) as f:
        txt = f.read()
    novo = inserir_no_settings(txt)
    if novo != txt:
        shutil.copy2(SETTINGS, SETTINGS + ".bak-irrigacao")
        with open(SETTINGS, "w") as f:
            f.write(novo)
        print("settings.js atualizado (backup: settings.js.bak-irrigacao)")
    print("Senhas gravadas. Agora:  sudo systemctl restart nodered")


if __name__ == "__main__":
    main()
