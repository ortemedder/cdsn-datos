#!/usr/bin/env python3
# cronica.py v1.0 - «Parte del día» de Caballeros de Sion escrito por la IA (API de Claude, Batch API)
# Lo ejecuta GitHub Actions cada hora por la mañana (.github/workflows/cronica.yml). Ajustes en cronica_config.json.
#   python3 tools/cronica.py            -> modo normal: envía el lote cuando toca y recoge el parte cuando está listo
#   python3 tools/cronica.py local      -> solo prepara los datos y dice cuánto ocupan (sin API, gratis)
#   python3 tools/cronica.py contar     -> cuenta los tokens exactos con la API (gratis) y lo guarda en cronica_medida.json
#   python3 tools/cronica.py forzar     -> envía ya, sin mirar hora ni día libre, y se publica en cuanto llega (para probar)
# Resultado: cronica_ia.json (la web lo enseña a la hora de publicar). Estado interno: cronica_estado.json.
import json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

VER = "c1.0"
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
    # --- nuestros sistemas ---
    L = ["#sis|ctrl|inf|antes|dif|2ª|inf2ª|nfac|estados(act/pend/recup)|pob|economía|seg|Powerplay(pot,est,ref,soc)|"
         "visitas(hoy,7d,30d)|portanaves48h|est.CDSN|dato(h tras tick)|hist.inf(últimos)"]
    for n in sorted(sis, key=lambda n: int(S(n)[1:])):
        s = sis[n]
        sx = s.get("sis") or {}
        pp = s.get("pp") or {}
        est = "/".join(",".join(s.get(k) or []) or "-" for k in ("activos", "pendientes", "recuperando"))
        pn48 = sum(1 for v in (s.get("pn") or {}).values() if (v.get("t") or 0) > ahora - 172800)
        prop = sum(1 for e in (s.get("estaciones") or {}).values() if e.get("f") == F.get("faccion"))
        hi = ",".join(r1(v) for _, v in (s.get("hinf") or [])[-6:])
        dato = f"{((s.get('t') or 0) - tg) / 3600:+.0f}" if s.get("t") else "-"
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
    L = ["#sis: @facción inf% gobierno [estados activos] ..."]
    for n in sorted(sis, key=lambda n: int(S(n)[1:])):
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
        if n in sis:
            L.append(S(n) + ": " + "; ".join(f"{FA(f)} " + ",".join(r1(v) for _, v in p[-5:]) for f, p in fs.items()))
    partes["HISTORIAL DE INFLUENCIA DE LAS OTRAS FACCIONES (últimos puntos, del más viejo al más nuevo)"] = L or ["sin datos"]
    # --- noticias de las últimas 48 h (incluye el resumen diario de las 21:00) ---
    L = []
    for t, txt, sec, *_ in [x for x in (F.get("noticias") or []) if x[0] > ahora - 172800]:
        txt = re.sub(r"\*\*", "", str(txt))
        for nom in sorted(S.d, key=len, reverse=True):
            if nom in txt:
                txt = txt.replace(nom, S(nom))
        L.append(f"{datetime.fromtimestamp(t, MAD):%d/%m %H:%M} [{sec}] {txt}")
    partes["NOTICIAS DEL ESCUCHA (últimas 48 h; los resúmenes diarios van con [resumen])"] = L or ["ninguna"]

    def montar(p):
        cab = (f"DATOS DE CABALLEROS DE SION (CDSN) · generados {hoy:%d/%m/%Y %H:%M} (hora de España)\n"
               f"Último tick global: {datetime.fromtimestamp(tg, MAD):%d/%m %H:%M} · siguiente tick hacia "
               f"{datetime.fromtimestamp(tg + 86400, MAD):%d/%m %H:%M}\n"
               f"Sistemas controlados al día tras el tick: {len(al_dia)} de {len(ctrl)}\n")
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
    return texto, {"al_dia": len(al_dia), "ctrl": len(ctrl), "tick": tg, "car": len(texto),
                   "tokens_aprox": int(len(texto) / 3.2), "nombres": list(S.d)}


INSTRUCCIONES = """Eres el oficial de inteligencia de Caballeros de Sion (CDSN), una facción menor del juego Elite Dangerous dirigida por \
su escuadrón. Cada día escribes el «Parte del día», la portada de La Crónica de Sion, que leen los comandantes del escuadrón \
a las {publicar} (hora de España) antes de jugar.

Te paso los datos del BGS que recoge nuestro escucha de EDDN. Los sistemas van como #N y las facciones como @N: usa los \
diccionarios para saber sus nombres. En tu respuesta escribe SIEMPRE los nombres reales, nunca #N ni @N, y pon cada nombre de \
SISTEMA entre dobles corchetes, por ejemplo [[Ndabangluya]] (las facciones sin corchetes).

Reglas:
- Español de España, claro y directo, para jugadores. Nada de relleno.
- No inventes nada: si un dato no está, no lo supongas. Si los datos del tick están incompletos, dilo.
- Distingue lo que es un peligro real de lo que no (p. ej. Powerplay, o una bajada pequeña en un sistema con mucha ventaja).
- Mira tendencias (varios días), no solo el último cambio.
- Lo que hagan los comandantes antes del próximo tick cuenta para ese tick: si algo es urgente, di cuánto queda.
- Prioriza: primero lo que puede costarnos un sistema, después oportunidades.

Responde SOLO con un objeto JSON válido, sin texto antes ni después, con esta forma:
{{"titular": "frase corta", "entradilla": "2-3 frases con lo esencial del día",
 "puntos": [{{"titulo": "...", "texto": "..."}}],      (3 a 5 puntos clave)
 "hacer": ["acción concreta para hoy", "..."],         (2 a 5 acciones, la más importante primero)
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


def params(modelo, texto, cfg):
    p = {"model": MODELOS[modelo], "max_tokens": int(cfg.get("max_salida", 12000)),
         "system": INSTRUCCIONES.format(publicar=cfg.get("publicar", "15:00")),
         "messages": [{"role": "user", "content": texto}]}
    if cfg.get("esfuerzo", "medium") != "sin":
        p["thinking"] = {"type": "adaptive"}
        p["output_config"] = {"effort": cfg.get("esfuerzo", "medium")}
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
def toca_enviar(cfg, info, ahora):
    if not cfg.get("activo", True):
        return False, "desactivado en cronica_config.json"
    if DIAS[ahora.weekday()] in [d.lower().replace("é", "e") for d in cfg.get("dias_libres") or []]:
        return False, "hoy es día libre"
    pub = datetime.combine(ahora.date(), datetime.strptime(cfg.get("publicar", "15:00"), "%H:%M").time(), MAD)
    tarde = pub - timedelta(hours=1)            # como muy tarde 1 h antes de publicar
    if ahora >= pub:
        return False, "ya pasó la hora de publicar"
    modo = cfg.get("envio", "C").upper()
    if modo == "A":
        return ahora >= pub - timedelta(hours=3), "modo A: 3 h antes de publicar"
    if modo == "B":
        listo = (ahora.timestamp() - info["tick"]) / 3600 >= 16
        return listo or ahora >= tarde, "modo B: 16 h tras el tick"
    listo = info["ctrl"] and info["al_dia"] / info["ctrl"] >= 0.8
    return bool(listo or ahora >= tarde), f"modo C: {info['al_dia']}/{info['ctrl']} sistemas al día"


def guardar_parte(res, modelo, est, cfg, nombres):
    C = lee("cronica_ia.json", {"ver": VER, "partes": []})
    m = res["message"]
    txt = "".join(b.get("text", "") for b in m.get("content", []) if b.get("type") == "text")
    u = m.get("usage", {})
    tin = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    tout = u.get("output_tokens", 0)
    try:
        p = lee_json_modelo(txt)
    except Exception:
        p = {"titular": "Parte del día", "entradilla": txt[:3000], "puntos": [], "hacer": [], "oportunidad": ""}
    citados = set(re.findall(r"\[\[(.+?)\]\]", json.dumps(p, ensure_ascii=False)))
    p.update({"fecha": est["fecha"], "publicar_t": est["publicar_t"], "modelo": modelo, "id_modelo": MODELOS[modelo],
              "tick": est["info"]["tick"], "al_dia": est["info"]["al_dia"], "ctrl": est["info"]["ctrl"],
              "tokens_in": tin, "tokens_out": tout, "coste": coste(modelo, tin, tout),
              "dudosos": sorted(c for c in citados if c not in nombres), "t": int(time.time())})
    C["partes"] = [x for x in C["partes"] if not (x.get("fecha") == est["fecha"] and x.get("modelo") == modelo)] + [p]
    lim = (datetime.now(MAD) - timedelta(days=GUARDA_DIAS)).strftime("%Y-%m-%d")
    C["partes"] = [x for x in C["partes"] if x.get("fecha", "") >= lim]
    C.update({"ver": VER, "modelo": cfg.get("modelo"), "t": int(time.time())})
    escribe("cronica_ia.json", C)
    print(f"  parte de {modelo}: {tin} tokens de entrada, {tout} de salida, {p['coste']} $"
          + (f", nombres dudosos: {p['dudosos']}" if p["dudosos"] else ""))


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
    # recoger un lote pendiente
    if est.get("batch") and not est.get("recogido"):
        b = json.loads(api("GET", f"/messages/batches/{est['batch']}"))
        print(f"Lote {est['batch']}: {b.get('processing_status')}")
        if b.get("processing_status") == "ended" and b.get("results_url"):
            nombres = set((F.get("sistemas") or {})) | set(F.get("vecinos") or {}) | set(F.get("expansion") or {}) \
                | set(F.get("zona") or {}) | set((A or {}).get("anarquicos") or {})
            for linea in api("GET", "", url=b["results_url"]).splitlines():
                if not linea.strip():
                    continue
                r = json.loads(linea)
                if r["result"]["type"] == "succeeded":
                    guardar_parte(r["result"], r["custom_id"], est, cfg, nombres)
                else:
                    print(f"  {r['custom_id']}: {r['result']['type']} {json.dumps(r['result'])[:300]}")
            est["recogido"] = int(time.time())
            escribe("cronica_estado.json", est)
        return
    if est.get("fecha") == hoy and modo != "forzar":
        print("El parte de hoy ya se envió")
        return
    si, motivo = toca_enviar(cfg, info, ahora)
    print(("Enviar: " if si else "Aún no: ") + motivo)
    if not si and modo != "forzar":
        return
    pub = datetime.combine(ahora.date(), datetime.strptime(cfg.get("publicar", "15:00"), "%H:%M").time(), MAD)
    cuerpo = {"requests": [{"custom_id": m, "params": params(m, texto, cfg)} for m in modelos]}
    b = json.loads(api("POST", "/messages/batches", cuerpo))
    est = {"fecha": hoy, "batch": b["id"], "enviado": int(time.time()), "modelos": modelos,
           "publicar_t": int(time.time()) if modo == "forzar" or ahora >= pub else int(pub.timestamp()),   # forzar: se ve en cuanto llega "info": {k: info[k] for k in ("tick", "al_dia", "ctrl")},
           "tokens_aprox": info["tokens_aprox"], "motivo": motivo}
    escribe("cronica_estado.json", est)
    print(f"Lote enviado: {b['id']} ({', '.join(modelos)})")


if __name__ == "__main__":
    main()
