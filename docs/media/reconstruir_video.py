#!/usr/bin/env python3
"""Reúne as 19 partes do vídeo original e valida a integridade (sem reencodificação)."""
from pathlib import Path
import hashlib

BASE = Path(__file__).resolve().parent
PARTES = BASE / "video_original_partes"
SAIDA = BASE / "demonstracao_completa.mp4"
SHA256_ESPERADO = "ecf04b0ca92556516e905826337bd39de32ae61c5cb15f7d9a46449bdf681c98"
TAMANHO_ESPERADO = 33692489

def main():
    h = hashlib.sha256()
    total = 0
    with SAIDA.open("wb") as dst:
        for n in range(1, 20):
            entrada = PARTES / f"parte_{n:02d}.part"
            if not entrada.is_file():
                raise FileNotFoundError(f"Falta {entrada}")
            with entrada.open("rb") as src:
                while bloco := src.read(1024 * 1024):
                    dst.write(bloco)
                    h.update(bloco)
                    total += len(bloco)
    if total != TAMANHO_ESPERADO or h.hexdigest() != SHA256_ESPERADO:
        SAIDA.unlink(missing_ok=True)
        raise RuntimeError("Integridade do vídeo falhou. Nenhum MP4 foi mantido.")
    print(f"Vídeo reconstituído: {SAIDA} ({total:,} bytes); SHA-256 validado.")

if __name__ == "__main__":
    main()
