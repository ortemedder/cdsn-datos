#!/usr/bin/env python3
# anarquicos.py v1.1 - sistemas anarquicos cerca de los sistemas que controla CDSN
# Lo ejecuta GitHub Actions una vez al dia (.github/workflows/anarquicos.yml).
# Lee faccion.json (sistemas con ctrl=True), pregunta a EDSM los sistemas a <= RADIO ly
# y guarda anarquicos.json. La web (cdsn-web, pestaña Anarquías) solo lee ese archivo.
# Version previa a Law & Disorder (9/12/2026): ya cuenta el gobierno nuevo «Criminal».
# v1.1: overlaps de mineria (overlaps.txt, fijo) con coordenadas de EDSM (solo la primera vez)
#       y, para cada sistema donde esta CDSN, los overlaps a <= RADIO_OVL ly (para la resistencia de la web).
import json, math, os, sys, time, urllib.parse, urllib.request

RADIO = 30                     # ly (si se desmadra, 20)
GOBIERNOS = ("anarchy", "criminal")   # Law & Disorder cambia Anarquía habitada por Criminal
RADIO_OVL = 20                 # ly: overlap «cerca» para la resistencia
DIAS_NUEVO = 7                 # «NUEVO» durante 7 dias desde que aparece
PAUSA = 1.5                    # segundos entre peticiones a EDSM
API = "https://www.edsm.net"
UA = "cdsn-anarquicos/1.0 (ortemedder@gmail.com)"
AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
SALIDA = os.path.join(RAIZ, "anarquicos.json")
PAD_L = {"coriolis starport", "orbis starport", "ocellus starport", "asteroid base",
         "planetary port", "dodec starport", "mega ship"}


def pide(ruta, params, intentos=4):
    url = API + ruta + "?" + urllib.parse.urlencode(params, doseq=True)
    for i in range(intentos):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60)
            quedan = r.headers.get("x-rate-limit-remaining")
            datos = json.loads(r.read().decode("utf-8") or "null")
            if quedan is not None and int(quedan) < 10:      # cerca del limite de EDSM: esperar
                time.sleep(int(r.headers.get("x-rate-limit-reset", "60")) / max(int(quedan), 1))
            time.sleep(PAUSA)
            return datos
        except Exception as e:
            print("  aviso EDSM:", e, file=sys.stderr)
            time.sleep(10 * (i + 1))
    return None


def dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def main():
    fac = json.load(open(os.path.join(RAIZ, "faccion.json"), encoding="utf-8"))
    nuestros = {n: s for n, s in fac.get("sistemas", {}).items()
                if s.get("ctrl") and not s.get("fuera") and s.get("pos")}
    try:
        antes = json.load(open(SALIDA, encoding="utf-8"))
    except Exception:
        antes = {}
    primero_antes = {n: a.get("primero") for n, a in antes.get("anarquicos", {}).items()}
    pad_antes = {n: a.get("pad") for n, a in antes.get("anarquicos", {}).items()}
    ahora = int(time.time())
    print(f"{len(nuestros)} sistemas controlados por CDSN, radio {RADIO} ly")

    anq, errores = {}, []
    for n, s in sorted(nuestros.items()):
        r = pide("/api-v1/sphere-systems", {"systemName": n, "radius": RADIO,
                                            "showInformation": 1, "showCoordinates": 1})
        if not isinstance(r, list):
            errores.append(n)
            print(" ", n, "-> sin respuesta")
            continue
        k = 0
        for x in r:
            inf = x.get("information") or {}
            gov = (inf.get("government") or "").strip()
            if not gov or not any(g in gov.lower() for g in GOBIERNOS) or not x.get("coords"):
                continue
            c = x["coords"]
            pos = [c["x"], c["y"], c["z"]]
            a = anq.setdefault(x["name"], {
                "pos": pos, "gov": gov, "fac": inf.get("faction"), "est": inf.get("factionState"),
                "pob": inf.get("population"), "seg": inf.get("security"), "eco": inf.get("economy"),
                "alg": inf.get("allegiance"), "cerca": {}})
            a["cerca"][n] = round(dist(pos, s["pos"]), 2)
            k += 1
        print(" ", n, "->", k, "anárquicos")

    # puerto grande (L): solo se pregunta la primera vez (las estaciones cambian poco)
    for n, a in anq.items():
        if pad_antes.get(n) in ("L", "M", "-"):
            a["pad"] = pad_antes[n]
            continue
        r = pide("/api-system-v1/stations", {"systemName": n})
        est = (r or {}).get("stations") if isinstance(r, dict) else None
        if est is None:
            a["pad"] = None
            continue
        est = [e for e in est if (e.get("type") or "").lower() != "fleet carrier"]
        if any((e.get("type") or "").lower() in PAD_L for e in est):
            a["pad"] = "L"
        elif any("outpost" in (e.get("type") or "").lower() for e in est):
            a["pad"] = "M"
        else:
            a["pad"] = "-"

    for n, a in anq.items():
        # primero = cuando apareció (0 = ya estaba en la primera lista, nunca sale como NUEVO)
        a["primero"] = (primero_antes.get(n) or 0) if n in primero_antes else (ahora if antes else 0)
        a["min"] = min(a["cerca"].values())

    # ---- overlaps de mineria ----
    pos_antes = {o["sys"]: o.get("pos") for o in antes.get("overlaps", [])}
    ovl = []
    try:
        for l in open(os.path.join(RAIZ, "overlaps.txt"), encoding="utf-8"):
            if l.strip() and not l.startswith("#"):
                c = [x.strip() for x in l.split("|")] + ["", "", "", ""]
                ovl.append({"m": c[0], "sys": c[1], "anillo": c[2], "quien": c[3], "pos": pos_antes.get(c[1])})
    except FileNotFoundError:
        pass
    conocidas = {n: s.get("pos") for n, s in fac.get("sistemas", {}).items() if s.get("pos")}
    for k in ("vecinos", "zona", "expansion"):
        for n, v in (fac.get(k) or {}).items():
            if v.get("pos"):
                conocidas.setdefault(n, v["pos"])
    for o in ovl:
        if not o["pos"] and o["sys"] in conocidas:
            o["pos"] = conocidas[o["sys"]]
    faltan = sorted({o["sys"] for o in ovl if not o["pos"]})
    for i in range(0, len(faltan), 20):
        r = pide("/api-v1/systems", [("systemName[]", x) for x in faltan[i:i + 20]] + [("showCoordinates", 1)])
        for x in r if isinstance(r, list) else []:
            if x.get("coords"):
                for o in ovl:
                    if o["sys"].lower() == x["name"].lower():
                        o["pos"] = [x["coords"]["x"], x["coords"]["y"], x["coords"]["z"]]
    ovl_cerca = {}
    for n, s in fac.get("sistemas", {}).items():
        if not s.get("pos") or s.get("fuera"):
            continue
        l = sorted(([o["sys"], o["m"], round(dist(o["pos"], s["pos"]), 1)] for o in ovl if o["pos"]
                    and dist(o["pos"], s["pos"]) <= RADIO_OVL), key=lambda t: t[2])
        if l:
            ovl_cerca[n] = l
    print(f"overlaps: {len(ovl)} ({sum(1 for o in ovl if o['pos'])} con coordenadas), {len(ovl_cerca)} sistemas de CDSN con alguno cerca")

    lista = {n: sorted(([an, a["cerca"][n]] for an, a in anq.items() if n in a["cerca"]),
                       key=lambda t: t[1]) for n in nuestros}
    salida = {
        "ver": "a1.1", "t": ahora, "radio": RADIO, "fuente": "EDSM",
        "nota": "Versión previa a Law & Disorder (Crimen y castigo, 9/12/2026)",
        "primera_vez": not antes, "dias_nuevo": DIAS_NUEVO,
        "nuestros": {n: {"pos": s["pos"], "anq": lista[n]} for n, s in nuestros.items()},
        "anarquicos": anq, "errores": errores,
        "radio_ovl": RADIO_OVL, "overlaps": ovl, "ovl_cerca": ovl_cerca}
    if len(errores) > len(nuestros) // 2 and antes:
        print("Demasiados errores de EDSM: se deja el archivo de ayer", file=sys.stderr)
        return 1
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, separators=(",", ":"))
    print(f"OK: {len(anq)} anárquicos, {len(errores)} errores")
    return 0


if __name__ == "__main__":
    sys.exit(main())
