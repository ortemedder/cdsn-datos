# cdsn-datos
«Estado de Caballeros de Sion en el BGS, para el Panel Elite»

`anarquicos.json`: sistemas anárquicos a ≤30 ly de los que controla CDSN. Lo calcula `tools/anarquicos.py` (EDSM) una vez al día con GitHub Actions (`.github/workflows/anarquicos.yml`).

`overlaps.txt`: overlaps de hotspots de minería (Platino, Painita, LTD; de edtools.cc), fijo, una línea `mineral | sistema | anillo | quién`. El script diario les pone coordenadas y guarda en `anarquicos.json` los que hay a ≤20 ly de cada sistema de CDSN (resistencia de la web).

## Parte del día (IA)
`tools/cronica.py` (c1.1) + `.github/workflows/cronica.yml` (cada hora desde las 07:00–08:00 de España). Envía a las 08:00 con Haiku y publica en cuanto llega (espera en el mismo trabajo); marca los partes rotos o perdidos y numera el periódico (AÑO y N.º). Prepara los datos «todo, pero limpio» (tablas, #N sistemas, @N facciones, tope en `cronica_config.json`), envía un lote a la Batch API de Claude cuando toca y guarda el parte en `cronica_ia.json`; la web lo publica a la hora de `publicar`. Ajustes en `cronica_config.json` (activo, publicar, envio A/B/C, dias_libres, modelo, prueba, esfuerzo, tope_tokens). Necesita el secreto `ANTHROPIC_API_KEY`. A mano: Actions > cronica > Run workflow (contar = medir tokens gratis, forzar = enviar ya).
