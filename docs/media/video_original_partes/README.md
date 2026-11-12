# Demonstração completa — vídeo original

Este diretório contém as **19 partes binárias** do vídeo original de demonstração, totalizando **33.692.489 bytes** (cerca de 4 minutos e 13 segundos), com o áudio original preservado. A segmentação foi necessária por limites de transferência do conector GitHub; **não existe reencodificação**.

## Assistir ao vídeo

O arquivo original de 33.692.489 bytes já está publicado no GitHub Releases: **[Baixar demonstração completa — MP4](https://github.com/caiosas/irrigacao-raspberry-pi/releases/download/demonstracao-irrigacao-v1/demonstracao_completa.mp4)**. O GitHub verificou o mesmo SHA-256 informado abaixo.

Como alternativa independente do lançamento, baixe o repositório (Code → Download ZIP), extraia os arquivos e execute, a partir da raiz do projeto:

```bash
python3 docs/media/reconstruir_video.py
```

O programa juntará as partes no arquivo `docs/media/demonstracao_completa.mp4` e verificará a integridade pelo SHA-256. Não são exigidas bibliotecas externas.

**SHA-256 do arquivo completo:** `ecf04b0ca92556516e905826337bd39de32ae61c5cb15f7d9a46449bdf681c98`

A publicação foi concluída com sucesso pelo workflow [`.github/workflows/publicar_video.yml`](../../../.github/workflows/publicar_video.yml).
