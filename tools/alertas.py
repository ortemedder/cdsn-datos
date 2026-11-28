#!/usr/bin/env python3
# alertas.py a1.2 - Calcula UNA sola vez las alertas de cada sistema de CDSN y las guarda en alertas.json.
# Mismas reglas que tenía la web (app.js v1.43: alerta0, alerta, hueco, imprescindibles, CMDRs de CDSN), para que
# la web, el radar y el parte de la IA lean las mismas alertas. Lo lanza GitHub Actions cada vez que el escucha sube
# faccion.json (.github/workflows/alertas.yml).
#   python3 tools/alertas.py          -> escribe alertas.json
#   python3 tools/alertas.py ver      -> además enseña las alertas por pantalla
import json, os, re, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

VER = "a1.2"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = "Caballeros de Sion"
DIAS_CONF = 7
TIPO = {"war": "Guerra", "civilwar": "Guerra civil", "election": "Elecciones"}
FASES = {"victoria": ("VICTORIA SEGURA", "fa", 0, 0), "a_un_dia": ("A UN DÍA DE GANAR", "fa", 1, 0),
         "defensa": ("DEFENSA EN CURSO", "fa", 1, 0), "disputado": ("DISPUTADO", "di", 0, 0),
         "igualado": ("DISPUTADO", "di", 1, 0), "decisivo": ("DÍA DECISIVO", "gr", 1, 1),
         "derrota": ("SISTEMA EN DERROTA", "gr", 1, 1), "sin_remedio": ("SISTEMA EN DERROTA", "gr", 1, 1)}
EST_ES = {"UnderRepairs": "en reparación", "Damaged": "dañada", "Abandoned": "abandonada", "UnderAttack": "bajo ataque",
          "Construction": "en construcción", "Evacuated": "evacuada"}
SEGN = {"$SYSTEM_SECURITY_high;": 3, "$SYSTEM_SECURITY_medium;": 2, "$SYSTEM_SECURITY_low;": 1,
        "$GAlAXY_MAP_INFO_state_anarchy;": 0, "$GALAXY_MAP_INFO_state_anarchy;": 0, "$GALAXY_MAP_INFO_state_lawless;": 0}
SEGT = ["sin ley", "baja", "media", "alta"]
MIN_BUENOS = ["Platinum", "Painite", "LTD", "Void Opals", "Osmium"]
MIN_ES = {"Platinum": "Platino", "Painite": "Painita", "Osmium": "Osmio", "Void Opals": "Ópalos del vacío"}
CRIT = re.compile(r"DECISIVO|DERROTA|RETIRADA INMINENTE|^RETIRADA$|POSIBLE ATAQUE|^HUECO")
NOW = time.time()
# a1.2: operaciones propias (operaciones.txt) y FLASH
OVR = re.compile(r"^(POSIBLE ATAQUE|BAJADA|ACTIVIDAD INUSUAL|VENTAJA BAJA|PRESENCIA EN PELIGRO|PROBABLE POWERPLAY|EXPANSIÓN ENEMIGA|HUECO|POSIBLE HUECO)")
FLASH_FRESCO = 6 * 3600   # el dato del sistema tiene que tener menos de 6 h


def ruta(n):
    return os.path.join(RAIZ, n)


def lee(n, d=None):
    try:
        with open(ruta(n), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return d


def c1(v):
    if v is None:
        return "—"
    return f"{v:.1f}".replace(".", ",")


def mes(n):
    return MIN_ES.get(n, n)


# ---------- listas a mano: imprescindibles, arquitectos, miembros ----------
def cargar_listas():
    niv, n_act = {}, 1
    try:
        for l in open(ruta("imprescindibles.txt"), encoding="utf-8"):
            x = l.strip()
            m = re.match(r"^\[\s*nivel\s*(\d+)\s*\]$", x, re.I)
            if m:
                n_act = int(m.group(1))
            elif x and not x.startswith("#"):
                niv[x.lower()] = n_act
    except OSError:
        pass
    arq = {}
    try:
        for l in open(ruta("arquitectos.txt"), encoding="utf-8"):
            if "=" in l and not l.lstrip().startswith("#"):
                a, b = [x.strip() for x in l.split("=", 1)]
                arq[a.lower()] = b
    except OSError:
        pass
    miem = {}
    try:
        with urllib.request.urlopen("https://raw.githubusercontent.com/ortemedder/cdsn-web/main/miembros.txt", timeout=20) as r:
            for l in r.read().decode("utf-8").splitlines():
                if l.strip() and not l.strip().startswith("#"):
                    miem[l.strip().lower()] = l.strip()
    except Exception:
        pass
    return niv, arq, miem


def cargar_ops():
    """a1.2: operaciones.txt -> {sistema_en_minúsculas: {"sys","txt","hasta"}} solo las que siguen vigentes.
    Formato: Sistema = qué hacemos · hasta DD/MM[/AAAA]. Sin fecha: 7 días desde el cambio del archivo."""
    out = {}
    try:
        mt = os.path.getmtime(ruta("operaciones.txt"))
        L = open(ruta("operaciones.txt"), encoding="utf-8").read().splitlines()
    except OSError:
        return out
    hoy = datetime.now(timezone.utc)
    for l in L:
        if "=" not in l or l.lstrip().startswith("#"):
            continue
        a, b = [x.strip() for x in l.split("=", 1)]
        if not a or not b:
            continue
        hasta = None
        m = re.search(r"[·\-,;]?\s*hasta\s+(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\s*$", b, re.I)
        if m:
            d, me, y = int(m.group(1)), int(m.group(2)), m.group(3)
            y = int(y) if y else hoy.year
            y = y + 2000 if y < 100 else y
            try:
                f = datetime(y, me, d, 23, 59, tzinfo=timezone(timedelta(hours=1)))
                if not m.group(3) and f < hoy - timedelta(days=180):
                    f = f.replace(year=y + 1)
                hasta = f.timestamp()
            except ValueError:
                hasta = None
            b = b[:m.start()].strip(" ·-,;")
        else:
            hasta = mt + 7 * 86400
        if hasta and hasta < NOW:
            continue
        out[a.lower()] = {"sys": a, "txt": b, "hasta": int(hasta) if hasta else None}
    return out


# ---------- ayudas (copiadas de la web) ----------
def dia_utc(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def pico(s):
    t = s.get("trafico") or {}
    for k in (0, 1):
        v = t.get(dia_utc(k), 0)
        m = sum(t.get(dia_utc(i), 0) for i in range(k + 1, k + 8)) / 7
        if v >= 5 and v >= 3 * max(m, 1):
            return {"v": v, "m": m, "dia": "ayer" if k else "hoy"}
    return None


def ataque(s):
    p = pico(s)
    if not p:
        return None
    inf, prev = s.get("inf"), s.get("prev")
    baja = prev is not None and prev - inf >= 1
    sube = prev is not None and inf - prev >= .5
    txt = f"{p['v']} pilotos {p['dia']} (media {c1(p['m'])})" + (
        f" y la influencia baja {c1(prev - inf)} puntos" if baja else f" y la influencia sube {c1(inf - prev)} puntos" if sube else "")
    return dict(p, baja=baja, sube=sube, txt=txt)


def fase_conf(g, p, dia):
    q = DIAS_CONF + 1 - dia
    if p + q < g:
        return "victoria"
    if g + q < p:
        return "sin_remedio"
    if p == 3 or (dia >= DIAS_CONF and abs(g - p) <= 1):
        return "decisivo"
    if g == 3 and p <= 1:
        return "a_un_dia"
    if g > p:
        return "defensa"
    if g < p:
        return "derrota"
    return "disputado" if g == 0 and dia <= 3 else "igualado"


def final_conf(g, p, dia):
    if g >= 4:
        return "victoria"
    if p >= 4:
        return "derrota"
    if dia >= DIAS_CONF:
        return "victoria" if g > p else "derrota" if p > g else "empate"
    return "sigue"


def juego_conf(g, p, dia):
    a, b = final_conf(g + 1, p, dia), final_conf(g, p + 1, dia)
    if a == "sigue" and b == "sigue":
        return ""
    return f"ganar = {a} · perder = {b}" + (f" · sin resultado = {final_conf(g, p, dia)}" if dia >= DIAS_CONF else "")


def conflicto(c):
    g, p, t = c.get("ganados") or 0, c.get("perdidos") or 0, (c.get("tipo") or "").lower()
    dia, exacto = c.get("dia") or 0, bool(c.get("dia_exacto"))
    if not dia:
        dia, exacto = min(DIAS_CONF, g + p + 1), False
    fase = c.get("fase") if c.get("fase") in FASES else fase_conf(g, p, dia)
    tit, tono, parp, alarma = FASES[fase]
    return {"g": g, "p": p, "dia": dia, "fase": fase, "tit": tit, "tono": tono, "parp": bool(parp), "alarma": bool(alarma),
            "ico": "✉" if t == "election" else "⚔", "juego": juego_conf(g, p, dia),
            "diaTxt": f"día {'' if exacto else '≥'}{dia}/{DIAS_CONF}"}


def amenazas(F):
    A = {}
    for desde, v in (F.get("vecinos") or {}).items():
        for e in v.get("exp") or []:
            for n, ly in e.get("obj") or []:
                A.setdefault(n, []).append({"n": e["n"], "desde": desde, "ly": ly})
    return A


def est_mal(s):
    E = list((s.get("estaciones") or {}).items())
    r = []
    for n, e in E:
        st = e.get("estado")
        if st and st != "Construction" and st in EST_ES and (e.get("f") == FAC or st in ("UnderAttack", "Damaged")) and not any(
                n2 != n and e.get("mid") and e2.get("mid") == e.get("mid") and (e2.get("t") or 0) > (e.get("t") or 0) for n2, e2 in E):
            r.append((n, e))
    return r


def est_tit(e):
    st = e.get("estado")
    return "ESTACIÓN BAJO ATAQUE" if st == "UnderAttack" else "ESTACIÓN DAÑADA" if st == "Damaged" else "ESTACIÓN " + EST_ES[st].upper()


def seg_baja(s):
    h = s.get("hsis") or []
    if len(h) < 2:
        return None
    a, b = h[-2], h[-1]
    x, y = SEGN.get(a[2]), SEGN.get(b[2])
    if x is not None and y is not None and y < x and NOW - b[0] < 3 * 86400:
        return {"de": SEGT[x], "a": SEGT[y]}
    return None


def dias_bajo(s):
    if (s.get("inf") or 0) >= 2.5:
        return 0
    t = s.get("t") or NOW
    for tt, v in reversed(s.get("hinf") or []):
        if v >= 2.5:
            break
        t = tt
    return max(0, (NOW - t) / 86400)


def d_bajo(s):
    d = dias_bajo(s)
    return "menos de 1 día" if d < 1 else f"{int(d)} {'día' if int(d) == 1 else 'días'}"


def min_sis(s):
    hot = list((s.get("hot") or {}).items())
    an = list((s.get("anillos") or {}).items())
    hb = list(dict.fromkeys(mes(x) for k, v in hot for x in v if x in MIN_BUENOS))
    virgen = any(v.get("res") == "Virgen" and re.search("metal", v.get("c") or "", re.I) for k, v in an)
    compra = sorted([{"e": e, "n": mes(m["n"]), "p": m.get("p") or 0} for e, x in (s.get("estaciones") or {}).items()
                     for m in ((x.get("mer") or {}).get("min") or []) if m.get("n") in MIN_BUENOS and (m.get("d") or 0) > 0],
                    key=lambda m: -m["p"])
    return hb, virgen, compra


def resist(s, ovl):
    p = 0
    v = (s.get("inf") or 0) - (s.get("segunda_inf") or 0)
    p += 3 if v >= 30 else 2 if v >= 15 else 1 if v >= 8 else 0
    nf = len(s.get("todas") or [])
    p += 2 if nf >= 7 else 1 if nf >= 5 else 0
    pob = (s.get("sis") or {}).get("pob") or 0
    p += 2 if pob >= 1e9 else 1 if pob >= 1e6 else 0
    sx = s.get("sis") or {}
    if re.search("extraction|refinery", f"{sx.get('eco') or ''} {sx.get('eco2') or ''}", re.I):
        p += 1
    ov = ovl.get(s["sys"]) or []
    hb, virgen, compra = min_sis(s)
    if (ov and ov[0][2] < 1) or hb:
        p += 2
    elif ov:
        p += 1
    elif virgen:
        p += 1
    if compra:
        p += 1
    if any(e.get("f") == FAC for e in (s.get("estaciones") or {}).values()):
        p += 1
    p = min(p, 10)
    return "alta" if p >= 6 else "media" if p >= 3 else "baja"


def fc_rec(s):
    t = NOW - 48 * 3600
    return sum(1 for v in (s.get("pn") or {}).values() if (v.get("t") or 0) >= t)


def pp_prob(s):
    pp = s.get("pp") or {}
    pot = pp.get("pot") or (pp.get("pots") or [None])[0]
    if not pot:
        return ""
    if s.get("prev") is not None and s["prev"] - s["inf"] >= 5:
        return ""
    fc, act = fc_rec(s), (pp.get("ref") or 0) + (pp.get("soc") or 0)
    if fc < 3 and act < 500:
        return ""
    ref = "—" if pp.get("ref") is None else pp.get("ref")
    soc = "—" if pp.get("soc") is None else pp.get("soc")
    return f"{str(fc) + ' portanaves y ' if fc else ''}Powerplay de {pot}" + (
        f" (refuerzo {ref} / socavamiento {soc})" if pp.get("ref") is not None or pp.get("soc") is not None else "")


def retirada(x):
    return "Retreat" in (x.get("act") or []) + (x.get("pend") or [])


# ---------- las alertas ----------
def hueco(s, niv, es_hist, AMZ):
    n = s["sys"]
    if not es_hist(n) and not niv.get(n.lower()):
        return None
    V = [x for x in s.get("todas") or [] if x.get("n") != FAC and retirada(x)]
    if not V:
        return None
    E, vistos = [], set()
    for e in sorted(AMZ.get(n) or [], key=lambda e: e["ly"]):
        if e["n"] not in vistos:
            vistos.add(e["n"])
            E.append(e)
    tipo = "IMPRESCINDIBLE" if niv.get(n.lower()) else "HISTÓRICO"
    txt = ", ".join(f"{x['n']} se retira ({c1(x.get('inf'))} %)" for x in V) + " · " + (
        f"{len(E)} facci{'ón en expansión puede' if len(E) == 1 else 'ones en expansión pueden'} llegar, la más cercana {E[0]['n']} a {c1(E[0]['ly'])} al"
        if E else "ninguna expansión enemiga cerca, por ahora")
    return {"tit": "HUECO EN " + tipo, "txt": txt, "grave": bool(E)}


def alerta0(s, ctx):
    niv, es_hist, AMZ, ovl = ctx
    inf = s.get("inf")
    for c in s.get("conflictos") or []:
        t = TIPO.get((c.get("tipo") or "").lower(), "Conflicto")
        ico = "✉" if (c.get("tipo") or "").lower() == "election" else "⚔"
        if c.get("estado") == "active":
            k = conflicto(c)
            return [2, k["tit"], f"{t} contra {c.get('contra')} · {k['diaTxt']} · {k['g']}-{k['p']}"
                    + (" (sin remedio)" if k["fase"] == "sin_remedio" else "") + (" · " + k["juego"] if k["juego"] else ""),
                    k["tono"], k["ico"], k["parp"], k["alarma"]]
        if c.get("estado") == "pending":
            return [2, t.upper() + " PEND.", f"contra {c.get('contra')} · empieza en el próximo tick", "pu", ico, False, False]
    if "Retreat" in (s.get("activos") or []) or "Retreat" in (s.get("pendientes") or []):
        return [2, "RETIRADA", f"influencia {c1(inf)} %", "gr"]
    if inf and 0 < inf < 2.5:
        return [2, "RETIRADA INMINENTE", f"{c1(inf)} % · {d_bajo(s)} por debajo del 2,5 % (se va a los 5–6)", "gr", "", True, True]
    vent = inf - (s.get("segunda_inf") or 0)
    if s.get("ctrl") and vent < 5:
        return [2, "VENTAJA BAJA", f"solo {c1(vent)} sobre {s.get('segunda')}", "gr"]
    at = ataque(s)
    if at and at["baja"]:
        pw, r = pp_prob(s), resist(s, ovl)
        if pw:
            return [1, "PROBABLE POWERPLAY", f"{at['txt']} · {pw} · resistencia {r}", "av", "⚡"]
        if r == "alta" and s["prev"] - inf < 3:
            return [1, "ACTIVIDAD INUSUAL", f"{at['txt']} · resistencia alta: poco preocupante", "av"]
        return [2, "POSIBLE ATAQUE", f"{at['txt']} · resistencia {r}", "gr", "", False, True]
    hu = hueco(s, niv, es_hist, AMZ)
    if hu:
        return [2 if hu["grave"] else 1, hu["tit"], hu["txt"], "gr" if hu["grave"] else "av", "⚠"]
    if s.get("prev") is not None and s["prev"] - inf >= 3:
        return [1, "BAJADA", f"{c1(inf - s['prev'])} desde ayer", "av"]
    if at and not at["sube"]:
        return [1, "ACTIVIDAD INUSUAL", at["txt"], "av"]
    if at:
        return [1, "ACTIVIDAD A FAVOR", at["txt"] + " (gente propia o ayuda externa)", "fa"]
    em = est_mal(s)
    if em:
        return [1, est_tit(em[0][1]), f"{em[0][0]} {EST_ES[em[0][1]['estado']]}" + (f" y {len(em) - 1} más" if len(em) > 1 else ""), "av"]
    am = AMZ.get(s["sys"])
    if am:
        return [1, "EXPANSIÓN ENEMIGA", f"{am[0]['n']} desde {am[0]['desde']} ({c1(am[0]['ly'])} al)" + (f" y {len(am) - 1} más" if len(am) > 1 else ""), "av", "🛸"]
    sb = seg_baja(s)
    if sb:
        return [1, "SEGURIDAD BAJADA", f"de {sb['de']} a {sb['a']}", "av"]
    if "Expansion" in (s.get("pendientes") or []):
        return [1, "EXPANSIÓN PEND.", "", "av"]
    return [0, "", "", "no"]


def alerta(s, ctx):
    niv = ctx[0]
    a = alerta0(s, ctx)
    nv = niv.get(s["sys"].lower()) or 0
    inf, prev = s.get("inf"), s.get("prev")
    if nv == 2:
        if a[0] == 2:
            return a
        if inf and 0 < inf < 10:
            return [2, "PRESENCIA EN PELIGRO", f"{c1(inf)} % (por debajo del 10 %) · ◇ imprescindible", "gr"]
        if prev is not None and prev - inf >= 1.5:
            return [2, "BAJADA", f"{c1(inf - prev)} desde ayer · ◇ imprescindible", "gr"]
        if a[1] in ("EXPANSIÓN ENEMIGA", "BAJADA", "ACTIVIDAD INUSUAL"):
            return [2, a[1], a[2] + " · ◇ imprescindible", "gr"] + a[4:7]
        return a
    if nv != 1:
        return a
    if a[0] == 1 and a[1] in ("BAJADA", "ACTIVIDAD INUSUAL", "PROBABLE POWERPLAY"):
        return [2, a[1], a[2] + " · ◆ imprescindible", "gr"] + a[4:7]
    if a[0]:
        return a
    vent = inf - (s.get("segunda_inf") or 0)
    if s.get("ctrl") and vent < 10:
        return [2, "VENTAJA BAJA", f"solo {c1(vent)} sobre {s.get('segunda')} · ◆ imprescindible", "gr"]
    if prev is not None and prev - inf >= 1.5:
        return [2, "BAJADA", f"{c1(inf - prev)} desde ayer · ◆ imprescindible", "gr"]
    return a


def calcula(F, A):
    """Devuelve {sistema: alerta} (lo usa también tools/cronica.py)."""
    niv, arq, miem = cargar_listas()
    es_hist = lambda n: bool(re.match(r"heredad", arq.get(n.lower(), ""), re.I))
    def cmdr(n):
        a = arq.get(n.lower(), "")
        return miem.get(a.lower(), "") if a and not re.match(r"heredad|coloniza", a, re.I) else ""
    ctx = (niv, es_hist, amenazas(F), A.get("ovl_cerca") or {})
    ops = cargar_ops()
    out = {}
    for n, s in (F.get("sistemas") or {}).items():
        if s.get("fuera") or s.get("inf") is None:
            continue
        s = dict(s, sys=n)
        a = alerta(s, ctx) + [None, None, None]
        nv, c = niv.get(n.lower()) or 0, cmdr(n)
        grupo = nv or (20 if c else 50 if es_hist(n) else 99)
        out[n] = {"niv": a[0], "tit": a[1], "txt": a[2], "tono": a[3], "ico": a[4] or "", "parp": bool(a[5]),
                  "alarma": bool(a[6]), "critico": bool(a[0] == 2 and CRIT.search(a[1] or "")), "grupo": grupo,
                  "imp": nv, "hist": es_hist(n), "cmdr": c}
        op = ops.get(n.lower())
        if op:   # a1.2: operación propia: no es un ataque, lo hacemos nosotros
            out[n]["op"] = op["txt"]
            if out[n]["niv"] == 0 or OVR.search(out[n]["tit"] or ""):
                antes = (out[n]["tit"] or "").lower()
                out[n].update({"niv": 1, "tit": "OPERACIÓN PROPIA", "tono": "av", "ico": "🛡", "parp": False, "alarma": False,
                               "critico": False, "txt": op["txt"] + (f" · ({antes})" if antes else "")})
    return out


def sistemas_nuevos(F):
    """a1.1: compara los sistemas de CDSN con los de la vez anterior y apunta noticias en noticias_extra.json
    (🎉 sistema nuevo, con su arquitecto si se sabe; 📉 sistema perdido). La web y el parte las juntan con las del escucha."""
    E = lee("noticias_extra.json", {}) or {}
    ahora = {n for n, s in (F.get("sistemas") or {}).items() if not s.get("fuera")}
    antes = set(E.get("conocidos") or [])
    N = E.get("noticias") or []
    if antes and ahora:
        niv, arq, miem = cargar_listas()
        for n in sorted(ahora - antes):
            a = arq.get(n.lower(), "")
            a = "" if re.match(r"heredad|coloniza", a, re.I) else a
            c = miem.get(a.lower(), "") if a else ""
            N.append([int(NOW), f"🎉 **{n}**: nuevo sistema para Caballeros de Sion"
                      + (f" · arquitecto **{c}** (CDSN) · ¡enhorabuena!" if c else f" · arquitecto {a}" if a else ""),
                      "expansion", 0, n, ""])
        for n in sorted(antes - ahora):
            N.append([int(NOW), f"📉 **{n}**: Caballeros de Sion ya no está en este sistema", "conflictos", 1, n, ""])
    E = {"ver": VER, "t": int(NOW), "conocidos": sorted(ahora) or sorted(antes), "noticias": N[-80:]}
    with open(ruta("noticias_extra.json"), "w", encoding="utf-8") as f:
        json.dump(E, f, ensure_ascii=False, separators=(",", ":"))
    return len(ahora - antes) if antes else 0


def main():
    F = lee("faccion.json", {}) or {}
    nn = sistemas_nuevos(F)
    if nn:
        print(f"{nn} sistemas nuevos de CDSN")
    out = calcula(F, lee("anarquicos.json", {}) or {})
    # a1.2: FLASH = alerta crítica en un imprescindible (nivel 1 o 2) con dato fresco (<6 h) y sin operación propia.
    # "desde" se guarda entre pasadas: el parte FLASH de la IA solo sale si sigue activo 1 h después (cronica.py).
    prev = (lee("alertas.json", {}) or {}).get("flash") or {}
    S = F.get("sistemas") or {}
    flash = {}
    for n, x in out.items():
        if x["critico"] and x["imp"] in (1, 2) and not x.get("op") and NOW - (S.get(n, {}).get("t") or 0) < FLASH_FRESCO:
            flash[n] = {"desde": (prev.get(n) or {}).get("desde") or int(NOW), "tit": x["tit"], "txt": x["txt"], "imp": x["imp"]}
    res = {"ver": VER, "t": int(NOW), "dato_t": F.get("t"), "n": len(out),
           "graves": sum(1 for x in out.values() if x["niv"] == 2), "avisos": sum(1 for x in out.values() if x["niv"] == 1),
           "flash": flash, "ops": list(cargar_ops().values()), "sistemas": out}
    with open(ruta("alertas.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    print(f"alertas.json: {len(out)} sistemas · {res['graves']} graves · {res['avisos']} avisos · flash {list(flash)} · ops {len(res['ops'])}")
    if len(sys.argv) > 1 and sys.argv[1] == "ver":
        for n, x in sorted(out.items(), key=lambda t: (-t[1]["niv"], t[1]["grupo"])):
            if x["niv"]:
                print(f"  {x['niv']} {x['tit']:<26} {n} · {x['txt'][:90]}")


if __name__ == "__main__":
    main()
