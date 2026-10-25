"""Exporta la versión publicada de pulso (GitHub Pages): web + resultados ya calculados, sin servidor.

Uso: cd trabajo && ../.venv/bin/python 07_exportar_estatico.py
Salida: ~/maverick_versionJJ/publicar/ (repo git que se sube a GitHub Pages).
"""
import hashlib
import json
import re
import shutil

import numpy as np

from armonizar import RAIZ
from motor import CACHE, CACHE_COMPARAR

FRONTEND = RAIZ / "frontend"
DESTINO = RAIZ / "publicar"
DATOS = DESTINO / "datos"


def compactar(r):
    """Reduce decimales de las probabilidades de cada persona (ficheros más ligeros)."""
    for p in r["personas"]:
        p["p"] = [round(x, 3) for x in p["p"]]
    return r


def web():
    for f in ["estilos.css", "app.js", "mapa_datos.js", "mapa_ccaa.js"]:
        shutil.copy(FRONTEND / f, DESTINO / f)
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    html = html.replace('<script src="mapa_datos.js', '<script>window.PULSO_ESTATICO = true;</script>\n<script src="mapa_datos.js', 1)
    (DESTINO / "index.html").write_text(html, encoding="utf-8")
    (DESTINO / ".nojekyll").write_text("")


def consultas():
    (DATOS / "consultas").mkdir(parents=True, exist_ok=True)
    (DATOS / "comparar").mkdir(parents=True, exist_ok=True)
    comparaciones = {r.stem for r in CACHE_COMPARAR.glob("*.json")}
    elegidas = {}
    for ruta in sorted(CACHE.glob("*.json"), key=lambda r: r.stat().st_mtime):
        r = json.loads(ruta.read_text(encoding="utf-8"))
        if "grupos" not in r["agregados"]:  # consultas antiguas sin los desgloses nuevos
            continue
        clave = (r["pregunta"].strip().lower(), r.get("tipo", "pregunta"), tuple(r.get("mensajes") or []))
        elegidas[clave] = (ruta, r)  # si se repite, gana la más reciente
    indice = []
    for ruta, r in elegidas.values():
        (DATOS / "consultas" / ruta.name).write_text(json.dumps(compactar(r), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        comp = hashlib.sha1(r["pregunta"].strip().lower().encode()).hexdigest()[:16]
        if comp in comparaciones:
            shutil.copy(CACHE_COMPARAR / f"{comp}.json", DATOS / "comparar" / f"{comp}.json")
        lider = int(np.argmax(r["agregados"]["total"]))
        indice.append({"pregunta": r["pregunta"], "tipo": r.get("tipo", "pregunta"), "mensajes": r.get("mensajes") or [],
                       "tema": r["tema"], "modo": r["modo"], "lider": r["opciones"][lider], "valor": r["agregados"]["total"][lider],
                       "archivo": ruta.name, "comparar": f"{comp}.json" if comp in comparaciones else None})
    orden = {"evidencia": 0, "analogia": 1, "simulacion": 2}
    indice.sort(key=lambda e: (e["tema"], orden.get(e["modo"], 3), e["pregunta"]))
    (DATOS / "indice.json").write_text(json.dumps(indice, ensure_ascii=False, indent=0), encoding="utf-8")
    return indice


def validacion_y_poblacion():
    import servidor
    (DATOS / "validacion.json").write_text(json.dumps(servidor.validacion(), ensure_ascii=False), encoding="utf-8")
    for n in (1000, 25000):
        (DATOS / f"poblacion_{n}.csv").write_text(servidor.poblacion_csv(n), encoding="utf-8")


def main():
    DESTINO.mkdir(exist_ok=True)
    if DATOS.exists():
        shutil.rmtree(DATOS)
    DATOS.mkdir()
    web()
    indice = consultas()
    validacion_y_poblacion()
    tam = sum(f.stat().st_size for f in DESTINO.rglob("*") if f.is_file() and ".git" not in f.parts) / 1e6
    modos = {m: sum(e["modo"] == m for e in indice) for m in ("evidencia", "analogia", "simulacion")}
    print(f"{len(indice)} consultas exportadas {modos} · {sum(1 for e in indice if e['comparar'])} comparaciones · {tam:.1f} MB")


if __name__ == "__main__":
    main()
