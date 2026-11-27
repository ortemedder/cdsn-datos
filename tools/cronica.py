#!/usr/bin/env python3
# cronica.py v1.1 - «Parte del día» de Caballeros de Sion escrito por la IA (API de Claude, Batch API)
# Lo ejecuta GitHub Actions cada hora por la mañana (.github/workflows/cronica.yml). Ajustes en cronica_config.json.
#   python3 tools/cronica.py            -> modo normal: envía el lote cuando toca y recoge el parte cuando está listo
#   python3 tools/cronica.py local      -> solo prepara los datos y dice cuánto ocupan (sin API, gratis)
#   python3 tools/cronica.py contar     -> cuenta los tokens exactos con la API (gratis) y lo guarda en cronica_medida.json
#   python3 tools/cronica.py forzar     -> envía ya, sin mirar hora ni día libre, y se publica en cuanto llega (para probar)
# Resultado: cronica_ia.json (la web lo enseña a la hora de publicar). Estado interno: cronica_estado.json.
# c1.1 (27/11/2026): envío fijo («envio": "F", hora «enviar») y publicación al llegar («publicar": "al_llegar"): tras
#   enviar, espera en el mismo trabajo hasta ~30 min a que el lote termine. Traduce los #N/@N que se le escapen a la IA.
#   Marca los partes rotos («roto» + motivo + texto en bruto) y los perdidos (error de la API), sin reintentar.
#   Numeración del periódico: AÑO (año galáctico - 3311) y N.º continuo desde el primer parte automático («inicio»).
# c1.2 (27/11/2026): un parte por tick («envio": "T"): SITREP PM 2 h después del tick; si a las 08:00 no hay parte en
#   20 h, SITREP AM; nunca dos con menos de 8 h. Antigüedad de los datos (no concluir con datos de más de 2 días),
#   sistemas tranquilos en una línea, esfuerzo «auto» (medio si hay algo crítico, bajo si no) y seguimiento del parte anterior.
import json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

VER = "c1.2"
AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
MAD = ZoneInfo("Europe/Madrid")
API = "https://api.anthropic.com/v1"
MODELOS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
# $ por millón de tokens (Batch = 50 % del precio normal; Haiku >100k de entrada cobra la tarifa larga)
PRECIO = {"haiku": (0.05, 0.25, 0.25, 1.25), "sonnet": (1.0, 5.0, 1.0, 5.0), "opus": (2.0, 10.0, 2.0, 10.0)}
DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
GUARDA_DIAS = 30


def ruta(n):
    return os.path.join(RAIZ, n)


def lee(n, defecto=None):
    try:
        with open(ruta(n), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def escribe(n, d):
    with open(ruta(n), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1 if n != "cronica_ia.json" else None,
                  separators=None if n != "cronica_ia.json" else (",", ":"))


def limpio(x):
    """$economy_Industrial; -> Industrial"""
    if not isinstance(x, str):
        return x
    x = re.sub(r"^\$[a-zA-Z]+_", "", x).rstrip(";")
    return x.replace("SECURITY_", "")


def r1(x):
    return "" if x is None else (f"{x:.1f}" if isinstance(x, (int, float)) else str(x))


# ---------------------------------------------------------------------------------------------------
# 1) Datos «todo, pero limpio»: tablas de texto, #N para sistemas y @N para facciones
# ---------------------------------------------------------------------------------------------------
class Dic:
    def __init__(self, pref):
        self.p, self.d = pref, {}

    def __call__(self, nombre):
        if not nombre:
            return "-"
        if nombre not in self.d:
            self.d[nombre] = len(self.d) + 1
        return f"{self.p}{self.d[nombre]}"

    def lista(self):
        return "\n".join(f"{self.p}{i} = {n}" for n, i in sorted(self.d.items(), key=lambda t: t[1]))


def preparar(F, H, A, tope):
    S, FA = Dic("#"), Dic("@")
    ahora = time.time()
    tg = F.get("tick_global") or 0
    hoy = datetime.now(MAD)
    sis = {n: s for n, s in (F.get("sistemas") or {}).items() if not s.get("fuera")}
    ctrl = [n for n, s in sis.items() if s.get("ctrl")]
    al_dia = [n for n in ctrl if (sis[n].get("t") or 0) > tg]
    for n in sorted(sis, key=lambda n: (not sis[n].get("ctrl"), -(sis[n].get("inf") or 0))):
        S(n)                                    # nuestros sistemas primero: #1.. son los controlados

    def vis(s, dias):
        tr = s.get("trafico") or {}
        return sum(v for k, v in tr.items() if k >= (hoy - timedelta(days=dias)).strftime("%Y-%m-%d"))

    partes = {}
    # --- imprescindibles (imprescindibles.txt, a mano) e historicos (heredados de arquitectos.txt) ---
    niv, n_act = {}, 1
    try:
        with open(ruta("imprescindibles.txt"), encoding="utf-8") as f:
            for l in f:
                x = l.strip()
                m = re.match(r"^\[\s*nivel\s*(\d+)\s*\]$", x, re.I)
                if m:
                    n_act = int(m.group(1))
                elif x and not x.startswith("#"):
                    niv[x.lower()] = n_act
    except OSError:
        pass
    her = set()
    try:
        with open(ruta("arquitectos.txt"), encoding="utf-8") as f:
            for l in f:
                if "=" in l and not l.lstrip().startswith("#") and re.match(r"\s*heredad", l.split("=", 1)[1], re.I):
                    her.add(l.split("=", 1)[0].strip().lower())
    except OSError:
        pass
    Li = []
    for v in sorted(set(niv.values())):
        ns = [S(n) for n in sis if niv.get(n.lower()) == v]
        if ns:
            Li.append(f"nivel {v}: " + ", ".join(ns))
    Li.append("históricos (anteriores a la colonización): " + (", ".join(S(n) for n in sis if n.lower() in her) or "-"))
    partes["SISTEMAS IMPRESCINDIBLES (los elige el almirante; nivel 1 = los más importantes) E HISTÓRICOS"] = Li
    # huecos: otra faccion en retirada en un historico o imprescindible -> puede entrar una faccion de fuera
    amz = {}
    for desde, v in (F.get("vecinos") or {}).items():
        for e in v.get("exp") or []:
            for n, ly in e.get("obj") or []:
                if n not in amz or e["n"] not in amz[n] or ly < amz[n][e["n"]]:
                    amz.setdefault(n, {})[e["n"]] = ly
    Lh = []
    for n, s_ in sis.items():
        if n.lower() not in niv and n.lower() not in her:
            continue
        ret = [x["n"] for x in s_.get("todas") or [] if x.get("n") != F.get("faccion", "Caballeros de Sion")
               and "Retreat" in (x.get("act") or []) + (x.get("pend") or [])]
        if ret:
            E = sorted((amz.get(n) or {}).items(), key=lambda t: t[1])
            Lh.append(f"{S(n)}: se retira {', '.join(FA(r) for r in ret)} · {len(E)} facciones en expansión pueden llegar"
                      + (f" (la más cercana {FA(E[0][0])} a {E[0][1]:.1f} al)" if E else ""))
    if Lh:
        partes["HUECOS EN HISTÓRICOS/IMPRESCINDIBLES (otra facción se retira: puede entrar una de fuera y quitarnos influencia)"] = Lh
    # sistemas de CMDRs de CDSN: el arquitecto es miembro (miembros.txt de cdsn-web); el arquitecto no cambia nunca
    miem = {}
    try:
        with urllib.request.urlopen("https://raw.githubusercontent.com/ortemedder/cdsn-web/main/miembros.txt", timeout=20) as r:
            for l in r.read().decode("utf-8").splitlines():
                if l.strip() and not l.strip().startswith("#"):
                    miem[l.strip().lower()] = l.strip()
    except Exception:
        pass
    cmdr = {}
    try:
        with open(ruta("arquitectos.txt"), encoding="utf-8") as f:
            for l in f:
                if "=" in l and not l.lstrip().startswith("#"):
                    a, b = [x.strip() for x in l.split("=", 1)]
                    if b.lower() in miem:
                        cmdr[a.lower()] = miem[b.lower()]
    except OSError:
        pass
    Lc = [f"{S(n)}: {cmdr[n.lower()]}" for n in sis if n.lower() in cmdr]
    if Lc:
        partes["SISTEMAS DE CMDRS DE CDSN (su arquitecto es del escuadrón: si su sistema está en peligro, «avisar a» ese CMDR)"] = Lc
    # grupos de prioridad: 1 imprescindibles nivel 1, 2 nivel 2..., 20 CMDRs de CDSN, 50 historicos, 99 resto
    def grupo(n):
        return niv.get(n.lower()) or (20 if n.lower() in cmdr else 50 if n.lower() in her else 99)
    # tareas obligatorias: lo que se puede perder hoy, con las MISMAS alertas que la web (tools/alertas.py, a1.0)
    sys.path.insert(0, AQUI)
    import alertas as AL
    ALx = AL.calcula(F, A)
    ACC = {"⚔": "zonas de conflicto y misiones de combate a favor de CDSN",
           "✉": "misiones, comercio con beneficio y datos de exploración en estaciones de CDSN (sin violencia)"}
    OB = []
    for n, x in ALx.items():
        if n in sis and x["critico"]:
            if x["tit"].startswith("HUECO"):
                acc = "mantener la influencia de CDSN alta para que la facción que entre lo haga lo más baja posible"
            elif x["ico"] in ACC:
                acc = ACC[x["ico"]]
            else:
                acc = "subir influencia: misiones de CDSN, comercio con beneficio y datos de exploración"
            OB.append((n, f"{acc} · {x['tit']}: {x['txt']}"))
    partes["ALERTAS (las mismas que ve la web; niv 2 = grave, 1 = aviso; las expansiones enemigas leves no van)"] = [
        f"{S(n)}: {x['niv']} {x['tit']} · {x['txt']}" for n, x in sorted(ALx.items(), key=lambda t: (-t[1]['niv'], t[1]['grupo']))
        if n in sis and x["niv"] and not (x["niv"] == 1 and x["tit"] == "EXPANSIÓN ENEMIGA")] or ["ninguna"]
    OB.sort(key=lambda t: grupo(t[0]))
    OB = [(n, t + (f" · avisar a {cmdr[n.lower()]}" if n.lower() in cmdr else "")) for n, t in OB]
    if OB:
        partes["TAREAS OBLIGATORIAS (tienen que salir en «hacer», en este orden)"] = [f"{S(n)}: {t}" for n, t in OB]
    # --- c1.2: antigüedad de los datos y sistemas tranquilos (una línea) ---
    edad = {n: (ahora - (s_.get("t") or 0)) / 86400 for n, s_ in sis.items()}
    obn = {n for n, _ in OB}
    atk = set(((F.get("ataques") or {}).get("act") or {}))
    def tranquilo(n):
        s_ = sis[n]
        if n in obn or n in atk or s_.get("conflictos") or niv.get(n.lower()) or n.lower() in cmdr:
            return False
        mio = next((x for x in s_.get("todas") or [] if x.get("n") == F.get("faccion", "Caballeros de Sion")), {})
        if "Retreat" in (mio.get("act") or []) + (mio.get("pend") or []) or (s_.get("inf") or 0) < 5:
            return False
        dif = abs((s_.get("inf") or 0) - (s_.get("prev") or s_.get("inf") or 0))
        vent = (s_.get("inf") or 0) - (s_.get("segunda_inf") or 0)
        return dif < 2 and (not s_.get("ctrl") or vent >= 20)
    TQ = {n for n in sis if tranquilo(n)}
    viejos = [n for n in sis if edad[n] > 2 and (sis[n].get("ctrl") or niv.get(n.lower()) or n.lower() in cmdr or n.lower() in her)]
    partes["DATOS VIEJOS (más de 2 días sin datos nuevos: NO saques conclusiones de ellos; pide que alguien pase con EDMC)"] = [
        f"{S(n)}: {edad[n]:.0f} días" for n in sorted(viejos, key=lambda n: -edad[n])] or ["ninguno"]
    partes["SISTEMAS TRANQUILOS (sin conflicto, ventaja de 20+ puntos o sin control, cambio < 2 puntos): #sis inf dif edad(días)"] = [
        " ".join(f"{S(n)} {r1(sis[n].get('inf'))} {r1((sis[n].get('inf') or 0) - (sis[n].get('prev') or sis[n].get('inf') or 0))} "
                 f"{edad[n]:.0f}d" for n in sorted(TQ, key=lambda n: int(S(n)[1:])))] if TQ else ["ninguno"]
    # --- c1.2: seguimiento del parte anterior ---
    Cp = lee("cronica_ia.json", {"partes": []})
    prev = sorted([x for x in Cp.get("partes") or [] if x.get("t") and x["t"] < ahora - 6 * 3600 and not x.get("roto")
                   and not x.get("perdido")], key=lambda x: x["t"])
    if prev:
        pa = prev[-1]
        Ls = []
        th = " ".join(map(str, pa.get("hacer") or []))
        nh = re.findall(r"\[\[(.+?)\]\]", th) or [n for n in sorted(sis, key=len, reverse=True) if n in th]
        for n in dict.fromkeys(nh):
            if n not in sis:
                continue
            s_, f0 = sis[n], (pa.get("foto") or {}).get(n)
            d0 = datetime.fromtimestamp(pa["t"], MAD).strftime("%Y-%m-%d")
            v = sum(c for k, c in (s_.get("trafico") or {}).items() if k >= d0)
            ve = (s_.get("inf") or 0) - (s_.get("segunda_inf") or 0)
            Ls.append(f"{S(n)}: " + (f"{r1(f0[0])} → {r1(s_.get('inf'))} ({r1((s_.get('inf') or 0) - f0[0])}), ventaja {r1(f0[1])} → {r1(ve)}"
                                    if f0 else f"ahora {r1(s_.get('inf'))}, ventaja {r1(ve)}")
                      + f" · {v} visitas desde el parte · dato de hace {edad[n]:.0f} días")
        partes[f"SEGUIMIENTO DEL PARTE ANTERIOR ({datetime.fromtimestamp(pa['t'], MAD):%d/%m %H:%M}): lo que se pidió y qué ha pasado"] = Ls or ["sin datos"]
    # --- nuestros sistemas ---
    L = ["#sis|ctrl|inf|antes|dif|2ª|inf2ª|nfac|estados(act/pend/recup)|pob|economía|seg|Powerplay(pot,est,ref,soc)|"
         "visitas(hoy,7d,30d)|portanaves48h|est.CDSN|edad(días)|hist.inf(últimos)"]
    for n in sorted(sis, key=lambda n: int(S(n)[1:])):
        if n in TQ:
            continue
        s = sis[n]
        sx = s.get("sis") or {}
        pp = s.get("pp") or {}
        est = "/".join(",".join(s.get(k) or []) or "-" for k in ("activos", "pendientes", "recuperando"))
        pn48 = sum(1 for v in (s.get("pn") or {}).values() if (v.get("t") or 0) > ahora - 172800)
        prop = sum(1 for e in (s.get("estaciones") or {}).values() if e.get("f") == F.get("faccion"))
        hi = ",".join(r1(v) for _, v in (s.get("hinf") or [])[-6:])
        dato = f"{edad[n]:.1f}" if s.get("t") else "-"
        dif = (s.get("inf") or 0) - (s.get("prev") or s.get("inf") or 0) if s.get("inf") is not None else None
        L.append("|".join(map(str, [
            S(n), "C" if s.get("ctrl") else "", r1(s.get("inf")), r1(s.get("prev")), r1(dif) if dif else "0",
            FA(s.get("segunda")), r1(s.get("segunda_inf")), len(s.get("todas") or []), est,
            sx.get("pob") or "", f"{limpio(sx.get('eco'))}/{limpio(sx.get('eco2'))}", limpio(sx.get("seg")) or "",
            f"{pp.get('pot') or '-'},{pp.get('est') or '-'},{pp.get('ref', '')},{pp.get('soc', '')}" if pp else "-",
            f"{(s.get('trafico') or {}).get(hoy.strftime('%Y-%m-%d'), 0)},{vis(s, 7)},{vis(s, 30)}",
            pn48, prop, dato, hi])))
    partes["NUESTROS SISTEMAS (C = controlado por CDSN)"] = L
    # --- facciones de cada sistema ---
    L = ["#sis: @facción inf% gobierno [estados activos] ... (los tranquilos no van)"]
    for n in sorted(sis, key=lambda n: int(S(n)[1:])):
        if n in TQ:
            continue
        fs = sis[n].get("todas") or []
        L.append(S(n) + ": " + "; ".join(
            f"{FA(f.get('n'))} {r1(f.get('inf'))} {f.get('gov') or ''}{(' [' + ','.join(f.get('act') or []) + ']') if f.get('act') else ''}"
            for f in fs))
    partes["FACCIONES POR SISTEMA"] = L
    # --- conflictos ---
    L = []
    for n, s in sis.items():
        for c in s.get("conflictos") or []:
            L.append(f"{S(n)}: {json.dumps(c, ensure_ascii=False)}")
    partes["CONFLICTOS EN CURSO"] = L or ["ninguno"]
    # --- ataques, rivales, avances de vecinos, minería ---
    at = (F.get("ataques") or {}).get("act") or {}
    partes["POSIBLES ATAQUES (detectados por el escucha)"] = [
        f"{S(n)}: desde {datetime.fromtimestamp(a.get('ini', 0), MAD):%d/%m %H:%M}, visitas {a.get('v')}, antes {r1(a.get('antes'))}, "
        f"ahora {r1(a.get('inf'))}, quién {FA(a.get('quien'))}" for n, a in at.items()] or ["ninguno"]
    partes["RIVALES (facciones que nos han quitado influencia)"] = [
        f"{FA(f)}: veces {r.get('veces')}, motivo {r.get('motivo')}, sistemas {' '.join(S(x) for x in r.get('sis') or [])}"
        for f, r in (F.get("rivales") or {}).items()] or ["ninguno"]
    partes["VECINOS QUE AVANZAN HACIA NOSOTROS"] = [
        f"{FA(f)}: desde {' '.join(S(x) for x in v.get('orig') or [])} -> objetivos " +
        " ".join(f"{S(x)}({r1(d)}ly)" for x, d in sorted((v.get('obj') or {}).items(), key=lambda t: t[1])[:8])
        for f, v in (F.get("vec_av") or {}).items()] or ["ninguno"]
    L = []
    for n, s in sis.items():
        an = s.get("anillos") or {}
        hot = s.get("hot") or {}
        if an or hot:
            L.append(f"{S(n)}: anillos " + ", ".join(f"{k.replace(n + ' ', '')}({v.get('c')},{v.get('res', '?')})" for k, v in an.items())
                     + (" · hotspots " + ", ".join(f"{k.replace(n + ' ', '')}:" + "+".join(f"{m}x{c}" for m, c in v.items() if m != 't')
                                                for k, v in hot.items()) if hot else ""))
        compra = [f"{e}:{m['n']} {m['p']}" for e, x in (s.get("estaciones") or {}).items()
                  for m in ((x.get("mer") or {}).get("min") or [])[:3] if m.get("d")]
        if compra:
            L.append(f"{S(n)}: compran {'; '.join(compra[:4])}")
    for n, l in ((A or {}).get("ovl_cerca") or {}).items():
        if n in sis:
            L.append(f"{S(n)}: overlaps cerca " + ", ".join(f"{o[1]} en {S(o[0])} a {o[2]}ly" for o in l[:3]))
    partes["MINERÍA (anillos, hotspots, compras, overlaps)"] = L or ["sin datos"]
    # --- anarquías ---
    L = []
    for n, a in sorted(((A or {}).get("anarquicos") or {}).items(), key=lambda t: t[1].get("min", 99)):
        cerca = sorted((a.get("cerca") or {}).items(), key=lambda t: t[1])[:4]
        L.append(f"{S(n)} {a.get('gov')} facción {FA(a.get('fac'))} est {a.get('est') or '-'} pob {a.get('pob') or '-'} "
                 f"puerto {a.get('pad') or '?'} cerca de " + " ".join(f"{S(x)}({d}ly)" for x, d in cerca))
    partes[f"SISTEMAS ANÁRQUICOS A ≤{(A or {}).get('radio', 30)} LY DE LOS NUESTROS"] = L or ["sin datos"]
    # --- vecinos con algo ---
    L = []
    for n, v in sorted((F.get("vecinos") or {}).items(), key=lambda t: t[1].get("ly", 99)):
        ly = v.get("ly") or 99
        if v.get("propio") or n in sis or ly <= 0:
            continue                            # los nuestros ya van arriba
        if ((v.get("exp") or v.get("ret")) and ly <= 20) or ly <= 10:
            L.append(f"{S(n)} {r1(v.get('ly'))}ly de {S(v.get('junto'))} nfac {v.get('nfac')}"
                     + (" exp: " + ", ".join(f"{FA(e.get('n'))}({e.get('est')})" for e in v.get("exp") or []) if v.get("exp") else "")
                     + (" ret: " + ", ".join(FA(e.get("n") if isinstance(e, dict) else e) for e in v.get("ret") or []) if v.get("ret") else ""))
    partes["VECINOS A ≤20 LY CON EXPANSIONES/RETIRADAS, O A ≤10 LY"] = L or ["ninguno"]
    # --- candidatos a expansión ---
    L = [f"{S(n)} {r1(e.get('ly'))}ly de {S(e.get('junto'))} nfac {e.get('nfac')} pob {e.get('pob')} controla {FA(e.get('ctrl_n'))}"
         for n, e in sorted((F.get("expansion") or {}).items(), key=lambda t: t[1].get("ly", 99))[:20]]
    partes["MEJORES CANDIDATOS PARA EXPANDIRNOS (20 más cercanos)"] = L or ["ninguno"]
    # --- historial de rivales (últimos puntos) ---
    L = []
    for n, fs in ((H or {}).get("rivales") or {}).items():
        if n in sis and n not in TQ:
            L.append(S(n) + ": " + "; ".join(f"{FA(f)} " + ",".join(r1(v) for _, v in p[-5:]) for f, p in fs.items()))
    partes["HISTORIAL DE INFLUENCIA DE LAS OTRAS FACCIONES (últimos puntos, del más viejo al más nuevo)"] = L or ["sin datos"]
    # --- noticias de las últimas 48 h (incluye el resumen diario de las 21:00) ---
    # agrupadas como en la web: «Expansión activo» de cada sistema -> una linea al dia; «Elecciones/Guerra activo» fuera
    # si ya esta la noticia del conflicto; vecindario -> una linea al dia (el detalle ya va en VECINOS)
    N0 = [(x[0], re.sub(r"\*\*", "", str(x[1])), x[2]) for x in (F.get("noticias") or []) if x[0] > ahora - 172800 and x[2] != "escucha"]
    conf = [(t, x) for t, x, sec in N0 if sec == "conflictos" and re.match(r"^(✉|⚔)", x)]
    N1, G, V = [], {}, {}
    for t, txt, sec in N0:
        dia = datetime.fromtimestamp(t, MAD).strftime("%d/%m")
        m = re.match(r"^📣 (.+?): Expansión activo$", txt)
        if m:
            G.setdefault(dia, [t, []]); G[dia][0] = max(G[dia][0], t); G[dia][1].append(m.group(1)); continue
        m = re.match(r"^📣 (.+?): (Elecciones|Guerra|Guerra civil) activo$", txt)
        if m and any(m.group(1) in x and abs(tc - t) < 86400 for tc, x in conf):
            continue
        if sec == "vecindario" or (sec == "expansion" and txt.startswith("🛸")):
            V.setdefault(dia, [t, 0]); V[dia][0] = max(V[dia][0], t); V[dia][1] += 1; continue
        N1.append((t, txt, sec))
    for dia, (t, ss) in G.items():
        ss = list(dict.fromkeys(ss))
        N1.append((t, f"📣 Expansión de CDSN activa en {len(ss)} sistemas: " + ", ".join(ss), "expansion"))
    for dia, (t, k) in V.items():
        N1.append((t, f"🔭 {k} avisos de facciones vecinas en expansión (el detalle va en VECINOS)", "vecindario"))
    L = []
    for t, txt, sec in sorted(N1):
        for nom in sorted(S.d, key=len, reverse=True):
            if nom in txt:
                txt = txt.replace(nom, S(nom))
        L.append(f"{datetime.fromtimestamp(t, MAD):%d/%m %H:%M} [{sec}] {txt}")
    partes["NOTICIAS DEL ESCUCHA (últimas 48 h; los resúmenes diarios van con [resumen])"] = L or ["ninguna"]

    def montar(p):
        cab = (f"DATOS DE CABALLEROS DE SION (CDSN) · generados {hoy:%d/%m/%Y %H:%M} (hora de España)\n"
               f"Último tick global: {datetime.fromtimestamp(tg, MAD):%d/%m %H:%M} · siguiente tick hacia "
               f"{datetime.fromtimestamp(tg + 86400, MAD):%d/%m %H:%M}\n"
               f"Sistemas controlados por CDSN: {len(ctrl)}. De ellos, con dato nuevo recibido después del último tick: {len(al_dia)} "
               f"(los demás aún no los ha visitado nadie que suba datos; su información es de antes del tick)\n")
        cuerpo = "\n\n".join(f"== {k} ==\n" + "\n".join(v) for k, v in p.items())
        return cab + "\n== DICCIONARIO DE SISTEMAS ==\n" + S.lista() + "\n\n== DICCIONARIO DE FACCIONES ==\n" + FA.lista() + "\n\n" + cuerpo

    texto = montar(partes)
    # tope: recortar primero lo menos importante (aprox. 3,2 caracteres por token)
    orden = ["MEJORES CANDIDATOS PARA EXPANDIRNOS (20 más cercanos)", "VECINOS A ≤20 LY CON EXPANSIONES/RETIRADAS, O A ≤10 LY",
             "HISTORIAL DE INFLUENCIA DE LAS OTRAS FACCIONES (últimos puntos, del más viejo al más nuevo)",
             "NOTICIAS DEL ESCUCHA (últimas 48 h; los resúmenes diarios van con [resumen])"]
    for k in orden:
        while len(texto) / 3.2 > tope and k in partes and len(partes[k]) > 5:
            partes[k] = partes[k][:len(partes[k]) * 3 // 4] + [f"... (recortado por tamaño)"]
            texto = montar(partes)
    foto = {n: [round(s_.get("inf") or 0, 2), round((s_.get("inf") or 0) - (s_.get("segunda_inf") or 0), 2)] for n, s_ in sis.items()}
    return texto, {"al_dia": len(al_dia), "ctrl": len(ctrl), "tick": tg, "car": len(texto), "oblig": OB, "critico": bool(OB),
                   "foto": foto,
                   "tokens_aprox": int(len(texto) / 3.2), "nombres": list(S.d),
                   "dic_s": [n for n, _ in sorted(S.d.items(), key=lambda t: t[1])],
                   "dic_f": [n for n, _ in sorted(FA.d.items(), key=lambda t: t[1])]}


INSTRUCCIONES = """Eres el oficial de inteligencia de Caballeros de Sion (CDSN), una facción menor del juego Elite Dangerous dirigida por \
su escuadrón. Cada día escribes el «Parte del día», la portada de La Crónica de Sion, que leen los comandantes del escuadrón \
a las {publicar} (hora de España) antes de jugar.

Te paso los datos del BGS que recoge nuestro escucha de EDDN. Los sistemas van como #N y las facciones como @N: usa los \
diccionarios para saber sus nombres. En tu respuesta escribe SIEMPRE los nombres reales, nunca #N ni @N, y pon cada nombre de \
SISTEMA entre dobles corchetes, por ejemplo [[Ndabangluya]] (las facciones sin corchetes).

Reglas del BGS (cúmplelas al razonar; no las expliques):
- El control de un sistema SOLO cambia con un conflicto (guerra, guerra civil o elecciones). Que otra facción tenga más \
influencia NO nos quita el sistema por sí solo.
- Un conflicto empieza cuando dos facciones quedan a menos de 5 puntos de influencia. Si una facción nos adelanta de golpe \
sin pasar por esa franja, no hay conflicto y seguimos controlando el sistema.
- Guerra y guerra civil: se gana con combate (zonas de conflicto, misiones de combate). Elecciones: SIN violencia (misiones, \
comercio con beneficio, datos de exploración). Gana el conflicto quien gane 4 días; se pierde la estación «en juego».
- Una facción por debajo del 2,5 % puede entrar en retirada y salir del sistema; las nativas (llevan el nombre del sistema) \
no se van nunca. Si una se va, queda hueco y puede entrar otra por expansión.
- Subir influencia de CDSN: misiones para CDSN, comercio con beneficio, bonos y datos de exploración en estaciones de CDSN.

Reglas:
- Español de España, claro y directo, para jugadores. Nada de relleno.
- Cada cifra y cada nombre que escribas tiene que estar en los datos. No te corrijas dentro del texto: si dudas, no lo pongas.
- Mira la antigüedad de los datos: de un sistema con DATOS VIEJOS (más de 2 días) no saques conclusiones ni des su estado como \
actual; di que hace falta que alguien pase por él con EDMC para saber cómo está.
- Si hay SEGUIMIENTO DEL PARTE ANTERIOR, empieza la entradilla o un punto valorando en una frase si lo que se pidió ha servido \
(reconoce lo que mejora, insiste en lo que sigue igual o peor, y si algo no mejora tras dos partes, propón otra forma).
- Es el {edicion}: tenlo en cuenta en el tono (por la mañana, datos de la noche; por la tarde, recién pasado el tick).
- No inventes nada: si un dato no está, no lo supongas. Si los datos del tick están incompletos, dilo.
- Distingue lo que es un peligro real de lo que no (p. ej. Powerplay, o una bajada pequeña en un sistema con mucha ventaja).
- Mira tendencias (varios días), no solo el último cambio.
- Lo que hagan los comandantes antes del próximo tick cuenta para ese tick: si algo es urgente, di cuánto queda.
- Prioriza: primero lo que puede costarnos un sistema, después oportunidades.
- Los sistemas IMPRESCINDIBLES (sobre todo los de nivel 1) son los que el almirante no quiere perder: cualquier peligro en ellos \
va antes que el resto, aunque sea pequeño, y dilo. Los HISTÓRICOS también pesan más que un sistema cualquiera. Si en uno de ellos \
otra facción se retira (HUECOS), avisa del riesgo de que entre una facción de fuera, sobre todo si hay expansiones cerca.

Responde SOLO con un objeto JSON válido, sin texto antes ni después, con esta forma:
{{"titular": "frase corta", "entradilla": "2-3 frases con lo esencial del día",
 "puntos": [{{"titulo": "...", "texto": "..."}}],      (3 a 5 puntos clave)
 "hacer": ["[[Sistema]] · qué hacer · por qué", "..."], (máximo 5; primero las TAREAS OBLIGATORIAS en su orden; luego por \
grupos: imprescindibles nivel 1, nivel 2, sistemas de CMDRs de CDSN, históricos y el resto; nada de «revisar» o «visitar»: di \
la actividad concreta (combate, misiones, comercio, exploración); si el sistema es de un CMDR de CDSN, añade «avisar a NOMBRE»)
 "oportunidad": "una oportunidad para crecer o ayudar a CDSN",
 "riesgo": "bajo" | "medio" | "alto"}}"""


# ---------------------------------------------------------------------------------------------------
# 2) API de Claude
# ---------------------------------------------------------------------------------------------------
def api(metodo, camino, cuerpo=None, url=None):
    clave = os.environ.get("ANTHROPIC_API_KEY", "")
    if not clave:
        raise SystemExit("Falta el secreto ANTHROPIC_API_KEY en GitHub")
    req = urllib.request.Request(url or API + camino, method=metodo,
                                 data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                 headers={"x-api-key": clave, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Error de la API {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")


def params(modelo, texto, cfg, critico=True, edicion="PM"):
    nombre = "SITREP AM, el parte matutino" if edicion == "AM" else "SITREP PM, el parte vespertino"
    p = {"model": MODELOS[modelo], "max_tokens": int(cfg.get("max_salida", 12000)),
         "system": INSTRUCCIONES.format(publicar=cfg.get("publicar", "15:00"), edicion=nombre),
         "messages": [{"role": "user", "content": texto}]}
    ef = cfg.get("esfuerzo", "medium")
    if ef == "auto":                                    # c1.2: medio si hay algo crítico, bajo si el día está tranquilo
        ef = "medium" if critico else "low"
    if ef != "sin":
        p["thinking"] = {"type": "adaptive"}
        p["output_config"] = {"effort": ef}
    return p


def coste(modelo, tin, tout):
    a, b, c, d = PRECIO[modelo]
    largo = modelo == "haiku" and tin > 100000
    return round(tin / 1e6 * (c if largo else a) + tout / 1e6 * (d if largo else b), 4)


def lee_json_modelo(txt):
    txt = txt.strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt).strip()
    i, j = txt.find("{"), txt.rfind("}")
    return json.loads(txt[i:j + 1])


# ---------------------------------------------------------------------------------------------------
# 3) Cuándo enviar y recoger
# ---------------------------------------------------------------------------------------------------
def hora_hoy(ahora, hhmm):
    return datetime.combine(ahora.date(), datetime.strptime(hhmm, "%H:%M").time(), MAD)


def toca_enviar(cfg, info, ahora):
    if not cfg.get("activo", True):
        return False, "desactivado en cronica_config.json"
    if DIAS[ahora.weekday()] in [d.lower().replace("é", "e") for d in cfg.get("dias_libres") or []]:
        return False, "hoy es día libre"
    modo = cfg.get("envio", "F").upper()
    if modo == "T":                             # c1.2: un parte por tick
        ult, ult_t, tg = info.get("ult_tick") or 0, info.get("ult_t") or 0, info["tick"] or 0
        h_tras = float(cfg.get("horas_tras_tick", 2))
        if ahora.timestamp() - ult_t < 8 * 3600:
            return False, "hace menos de 8 h del último parte"
        if tg > ult and ahora.timestamp() >= tg + h_tras * 3600:
            info["edicion"] = "PM"
            return True, f"SITREP PM: {h_tras:g} h después del tick de las {datetime.fromtimestamp(tg, MAD):%H:%M}"
        if ahora >= hora_hoy(ahora, cfg.get("respaldo", "08:00")) and ahora.timestamp() - ult_t >= 20 * 3600:
            info["edicion"] = "AM"
            return True, f"SITREP AM: a las {cfg.get('respaldo', '08:00')} sin parte en 20 h"
        if tg > ult:
            return False, f"tick de las {datetime.fromtimestamp(tg, MAD):%H:%M} detectado: el parte sale {h_tras:g} h después"
        return False, "esperando al próximo tick"
    if modo == "F":                             # c1.1: hora fija de envío
        h = hora_hoy(ahora, cfg.get("enviar", "08:00"))
        return ahora >= h, f"envío fijo a las {cfg.get('enviar', '08:00')} ({info['al_dia']}/{info['ctrl']} sistemas con dato nuevo)"
    pub = hora_hoy(ahora, cfg.get("publicar") if re.match(r"^\d\d:\d\d$", str(cfg.get("publicar"))) else "15:00")
    tarde = pub - timedelta(hours=1)            # como muy tarde 1 h antes de publicar
    if ahora >= pub:
        return False, "ya pasó la hora de publicar"
    if modo == "A":
        return ahora >= pub - timedelta(hours=3), "modo A: 3 h antes de publicar"
    if modo == "B":
        listo = (ahora.timestamp() - info["tick"]) / 3600 >= 16
        return listo or ahora >= tarde, "modo B: 16 h tras el tick"
    listo = info["ctrl"] and info["al_dia"] / info["ctrl"] >= 0.8
    return bool(listo or ahora >= tarde), f"modo C: {info['al_dia']}/{info['ctrl']} sistemas al día"


BASURA = re.compile(r"perd[oó]n|me he liado|lo siento|^\s*\{|\"titular\"", re.I)


def traducir(o, ds, df):
    """Cambia los #N (sistemas, como [[Nombre]]) y @N (facciones) que se le escapen a la IA."""
    if isinstance(o, str):
        o = re.sub(r"(?<![\w\[])#(\d+)", lambda m: f"[[{ds[int(m.group(1)) - 1]}]]" if 0 < int(m.group(1)) <= len(ds) else m.group(0), o)
        return re.sub(r"(?<!\w)@(\d+)", lambda m: df[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(df) else m.group(0), o)
    if isinstance(o, list):
        return [traducir(x, ds, df) for x in o]
    if isinstance(o, dict):
        return {k: traducir(v, ds, df) for k, v in o.items()}
    return o


def roto(p, m):
    """Motivo por el que el parte no vale (vacío = está bien). No se reintenta: la web lo enseña como interceptado."""
    if m.get("stop_reason") == "max_tokens":
        return "cortado (llegó al límite de salida)"
    if not isinstance(p, dict):
        return "no es un JSON válido"
    if not str(p.get("titular") or "").strip() or not str(p.get("entradilla") or "").strip():
        return "falta el titular o la entradilla"
    if len(p.get("puntos") or []) < 2 or len(p.get("hacer") or []) < 1:
        return "faltan puntos clave o acciones"
    if BASURA.search(str(p.get("titular"))) or BASURA.search(str(p.get("entradilla"))[:200]):
        return "texto con basura (borradores, disculpas o JSON dentro)"
    return ""


def numeracion(C, fecha):
    """AÑO (año galáctico - 3311: 3312 = año 1) y N.º continuo desde el primer parte automático."""
    ini = C.get("inicio")
    if not ini:
        return None, None
    d = datetime.strptime(fecha, "%Y-%m-%d")
    return d.year + 1286 - 3311, (d - datetime.strptime(ini, "%Y-%m-%d")).days + 1


def guardar_parte(res, modelo, est, cfg, nombres, info_ahora=None):
    C = lee("cronica_ia.json", {"ver": VER, "partes": []})
    inf = est.get("info") or info_ahora or {"tick": 0, "al_dia": None, "ctrl": None}
    if res.get("type") != "succeeded" or "message" not in res:      # c1.1: transmisión perdida (error de la API)
        p = {"perdido": True, "motivo": res.get("type", "error"), "titular": "", "entradilla": ""}
        tin = tout = 0
    else:
        m = res["message"]
        txt = "".join(b.get("text", "") for b in m.get("content", []) if b.get("type") == "text")
        u = m.get("usage", {})
        tin = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        tout = u.get("output_tokens", 0)
        try:
            p = lee_json_modelo(txt)
        except Exception:
            p = None
        mot = roto(p, m)
        if not isinstance(p, dict):
            p = {"titular": "", "entradilla": "", "puntos": [], "hacer": [], "oportunidad": ""}
        p = traducir(p, est.get("dic_s") or [], est.get("dic_f") or [])
        if not mot:                                   # tareas obligatorias que la IA se haya saltado: van delante
            H = [str(h) for h in (p.get("hacer") or [])]
            falta = [f"[[{n}]] · {t}" for n, t in (est.get("oblig") or []) if not any(n in h for h in H)]
            if falta:
                p["hacer"] = falta + H
                p["anadidas"] = len(falta)
        if mot:
            p.update({"roto": True, "motivo": mot, "bruto": txt[:1500]})
    citados = set(re.findall(r"\[\[(.+?)\]\]", json.dumps(p, ensure_ascii=False)))
    if est.get("auto") and not C.get("inicio"):
        C["inicio"] = est["fecha"]                  # N.º 1 = primer parte automático (no las pruebas forzadas)
    anio, num = numeracion(C, est["fecha"])
    if num is not None:                             # c1.2: N.º por parte (AM y PM llevan cada uno el suyo); si se rehace, conserva el suyo
        igual = next((x for x in C["partes"] if x.get("fecha") == est["fecha"] and x.get("modelo") == modelo
                      and x.get("edicion", "") == est.get("edicion", "") and x.get("numero")), None)
        if igual:
            num = igual["numero"]
        else:
            C["n"] = max([C.get("n") or 0] + [x.get("numero") or 0 for x in C["partes"]]) + 1
            num = C["n"]
    pub_t = int(time.time()) if est.get("al_llegar") else est["publicar_t"]
    citados_h = set(re.findall(r"\[\[(.+?)\]\]", " ".join(map(str, p.get("hacer") or []))))
    p["foto"] = {n: v for n, v in (est.get("foto") or {}).items() if n in citados_h}   # para el seguimiento del próximo parte
    p["edicion"] = est.get("edicion", "")
    p.update({"fecha": est["fecha"], "publicar_t": pub_t, "modelo": modelo, "id_modelo": MODELOS[modelo],
              "anio": anio, "numero": num,
              "tick": inf["tick"], "al_dia": inf["al_dia"], "ctrl": inf["ctrl"],
              "tokens_in": tin, "tokens_out": tout, "coste": coste(modelo, tin, tout),
              "dudosos": sorted(c for c in citados if c not in nombres), "t": int(time.time())})
    C["partes"] = [x for x in C["partes"] if not (x.get("fecha") == est["fecha"] and x.get("modelo") == modelo
                                                  and x.get("edicion", "") == p["edicion"])] + [p]
    lim = (datetime.now(MAD) - timedelta(days=GUARDA_DIAS)).strftime("%Y-%m-%d")
    C["partes"] = [x for x in C["partes"] if x.get("fecha", "") >= lim]
    C.update({"ver": VER, "modelo": cfg.get("modelo"), "t": int(time.time())})
    escribe("cronica_ia.json", C)
    print(f"  parte de {modelo}: {tin} tokens de entrada, {tout} de salida, {p['coste']} $"
          + (f", nombres dudosos: {p['dudosos']}" if p["dudosos"] else "")
          + (f" · ROTO: {p['motivo']}" if p.get("roto") else "") + (" · PERDIDO" if p.get("perdido") else ""))


def main():
    modo = (sys.argv[1] if len(sys.argv) > 1 else "auto").lower()
    cfg = lee("cronica_config.json", {})
    F, H, A = lee("faccion.json", {}), lee("historial.json", {}), lee("anarquicos.json", {})
    texto, info = preparar(F, H, A, int(cfg.get("tope_tokens", 200000)))
    ahora = datetime.now(MAD)
    print(f"Datos: {info['car']:,} caracteres ≈ {info['tokens_aprox']:,} tokens; {info['al_dia']}/{info['ctrl']} sistemas al día")
    if modo == "local":
        with open(ruta("cronica_datos_prueba.txt"), "w", encoding="utf-8") as f:
            f.write(texto)
        return
    modelos = [m for m in (cfg.get("prueba") or []) if m in MODELOS] or [cfg.get("modelo", "sonnet")]
    if modo == "contar":
        med = {"t": int(time.time()), "caracteres": info["car"], "aprox": info["tokens_aprox"], "modelos": {}}
        for m in modelos:
            p = params(m, texto, cfg)
            p.pop("max_tokens", None)
            p.pop("output_config", None)
            n = json.loads(api("POST", "/messages/count_tokens", p)).get("input_tokens")
            a, b, c, d = PRECIO[m]
            med["modelos"][m] = {"tokens": n, "coste_entrada": round(n / 1e6 * (c if m == "haiku" and n > 100000 else a), 4)}
            print(f"  {m}: {n:,} tokens de entrada exactos ≈ {med['modelos'][m]['coste_entrada']} $ (con Batch)")
        escribe("cronica_medida.json", med)
        return
    est = lee("cronica_estado.json", {}) or {}
    hoy = ahora.strftime("%Y-%m-%d")
    nombres = set((F.get("sistemas") or {})) | set(F.get("vecinos") or {}) | set(F.get("expansion") or {}) \
        | set(F.get("zona") or {}) | set((A or {}).get("anarquicos") or {})

    def recoger(est):
        b = json.loads(api("GET", f"/messages/batches/{est['batch']}"))
        print(f"Lote {est['batch']}: {b.get('processing_status')}")
        if b.get("processing_status") != "ended" or not b.get("results_url"):
            return False
        for linea in api("GET", "", url=b["results_url"]).splitlines():
            if linea.strip():
                r = json.loads(linea)
                guardar_parte(r["result"], r["custom_id"], est, cfg, nombres, info)
        est["recogido"] = int(time.time())
        escribe("cronica_estado.json", est)
        return True

    # recoger un lote pendiente
    if est.get("batch") and not est.get("recogido"):
        recoger(est)
        return
    info["ult_tick"], info["ult_t"] = est.get("tick_parte") or 0, est.get("enviado") or 0
    if est.get("fecha") == hoy and modo != "forzar" and cfg.get("envio", "F").upper() != "T":
        print("El parte de hoy ya se envió")
        return
    si, motivo = toca_enviar(cfg, info, ahora)
    print(("Enviar: " if si else "Aún no: ") + motivo)
    if not si and modo != "forzar":
        return
    al_llegar = modo == "forzar" or not re.match(r"^\d\d:\d\d$", str(cfg.get("publicar", "")))
    pub = ahora if al_llegar else hora_hoy(ahora, cfg["publicar"])
    ed = info.get("edicion") or ("AM" if ahora.hour < 14 else "PM")
    cuerpo = {"requests": [{"custom_id": m, "params": params(m, texto, cfg, info.get("critico", True), ed)} for m in modelos]}
    b = json.loads(api("POST", "/messages/batches", cuerpo))
    est = {"fecha": hoy, "batch": b["id"], "enviado": int(time.time()), "modelos": modelos,
           "publicar_t": int(time.time()) if al_llegar or ahora >= pub else int(pub.timestamp()),
           "al_llegar": al_llegar, "auto": modo != "forzar",
           "info": {k: info[k] for k in ("tick", "al_dia", "ctrl")},
           "dic_s": info["dic_s"], "dic_f": info["dic_f"], "oblig": info.get("oblig") or [],
           "edicion": ed, "tick_parte": info["tick"], "foto": info.get("foto") or {},
           "tokens_aprox": info["tokens_aprox"], "motivo": motivo}
    escribe("cronica_estado.json", est)
    print(f"Lote enviado: {b['id']} ({', '.join(modelos)})")
    # c1.1: esperar aquí mismo (hasta ~30 min) para publicar en cuanto llegue
    for _ in range(int(cfg.get("espera_min", 30))):
        time.sleep(60)
        if recoger(est):
            break


if __name__ == "__main__":
    main()
