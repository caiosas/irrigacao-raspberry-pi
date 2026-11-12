# Demonstração completa — vídeo original

Este diretório contém as **19 partes binárias** do vídeo original de demonstração, totalizando **33.692.489 bytes** (cerca de 4 minutos e 13 segundos), com o áudio original preservado. A segmentação foi necessária por limites de transferência do conector GitHub; **não existe reencodificação**.

## Assistir ao vídeo

Acesse a [página de lançamentos](https://github.com/caiosas/irrigacao-raspberry-pi/releases) e procure o arquivo `demonstracao_completa.mp4` no lançamento **Demonstração do sistema de irrigação**.

Se o lançamento ainda não estiver disponível, baixe o repositório (Code → Download ZIP), extraia os arquivos e execute, a partir da raiz do projeto:

```bash
python3 docs/media/reconstruir_video.py
```

O programa juntará as partes no arquivo `docs/media/demonstracao_completa.mp4` e verificará a integridade pelo SHA-256. Não são exigidas bibliotecas externas.

**SHA-256 do arquivo completo:** `ecf04b0ca92556516e905826337bd39de32ae61c5cb15f7d9a46449bdf681c98`

A publicação automatizada como ativo de release está definida no workflow `.github/workflows/publicar_video.yml`, caso o GitHub Actions esteja habilitado no fork.
