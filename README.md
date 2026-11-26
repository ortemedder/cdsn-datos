# cdsn-datos
«Estado de Caballeros de Sion en el BGS, para el Panel Elite»

`anarquicos.json`: sistemas anárquicos a ≤30 ly de los que controla CDSN. Lo calcula `tools/anarquicos.py` (EDSM) una vez al día con GitHub Actions (`.github/workflows/anarquicos.yml`).

`overlaps.txt`: overlaps de hotspots de minería (Platino, Painita, LTD; de edtools.cc), fijo, una línea `mineral | sistema | anillo | quién`. El script diario les pone coordenadas y guarda en `anarquicos.json` los que hay a ≤20 ly de cada sistema de CDSN (resistencia de la web).
