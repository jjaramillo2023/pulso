"""Rejilla de puntos de España con las fronteras reales de las comunidades para la vista «Comunidades».

Fuente: es-atlas 0.6.0 (límites del IGN, CC BY 4.0), guardado en datos_geo/es_atlas_autonomous_regions.json.
Salida: frontend/mapa_ccaa.js con MAPA_CCAA = {ar, paso, cn, pts: [[x, y, id, borde], ...]} en coordenadas 0-1
(x relativa al ancho, y al alto; paso = separación entre puntos relativa al ancho).

Uso: cd trabajo && ../.venv/bin/python 09_mapa_ccaa.py
"""
import json
import math

import numpy as np

from armonizar import RAIZ

FUENTE = RAIZ / "datos_geo" / "es_atlas_autonomous_regions.json"
SALIDA = RAIZ / "frontend" / "mapa_ccaa.js"
INE_A_ID = {"01": "AN", "02": "AR", "03": "AS", "04": "IB", "05": "CN", "06": "CB", "07": "CL", "08": "CM", "09": "CT",
            "10": "VC", "11": "EX", "12": "GA", "13": "MD", "14": "MC", "15": "NA", "16": "PV", "17": "RI"}
COS = math.cos(math.radians(40))   # proyección equirrectangular centrada en la península
PASO = 0.118                       # separación entre puntos (unidades proyectadas) → unos 3.000 puntos
CN_DESPLAZ = (5.4, 8.3)            # Canarias se dibuja en un recuadro abajo a la izquierda (grados lon, lat)


def anillos(topo):
    """Decodifica la TopoJSON: devuelve {id: [anillo exterior o hueco como array (n, 2) de lon/lat]}."""
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcos = []
    for arco in topo["arcs"]:
        a = np.cumsum(np.array(arco, dtype=float), axis=0)
        arcos.append(np.column_stack([a[:, 0] * sx + tx, a[:, 1] * sy + ty]))

    def anillo(indices):
        partes = [arcos[i] if i >= 0 else arcos[~i][::-1] for i in indices]
        return np.vstack([p if k == 0 else p[1:] for k, p in enumerate(partes)])

    salida = {}
    for g in topo["objects"]["autonomous_regions"]["geometries"]:
        rid = INE_A_ID.get(g["id"])
        if not rid:
            continue   # Ceuta, Melilla y Gibraltar no se dibujan
        poligonos = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        salida[rid] = [[anillo(r) for r in pol] for pol in poligonos]
    return salida


def proyectar(lonlat, rid):
    lon, lat = lonlat[:, 0], lonlat[:, 1]
    if rid == "CN":
        lon, lat = lon + CN_DESPLAZ[0], lat + CN_DESPLAZ[1]
    return np.column_stack([lon * COS, -lat])


def dentro(px, py, anillo):
    """Regla par-impar vectorizada: qué puntos (px, py) caen dentro del anillo."""
    x, y = anillo[:, 0], anillo[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    res = np.zeros(px.shape, dtype=bool)
    for a, b, c, d in zip(x, y, x2, y2):
        cruza = ((b > py) != (d > py)) & (px < (c - a) * (py - b) / (d - b + 1e-12) + a)
        res ^= cruza
    return res


def main():
    regiones = {rid: [[proyectar(r, rid) for r in pol] for pol in pols] for rid, pols in anillos(json.loads(FUENTE.read_text())).items()}
    todos = np.vstack([r for pols in regiones.values() for pol in pols for r in pol])
    x0, y0 = todos.min(axis=0) - PASO
    x1, y1 = todos.max(axis=0) + PASO

    # rejilla hexagonal: filas alternas desplazadas medio paso
    dy = PASO * math.sqrt(3) / 2
    filas = np.arange(y0, y1, dy)
    px = np.concatenate([np.arange(x0 + (PASO / 2 if i % 2 else 0), x1, PASO) for i in range(len(filas))])
    py = np.concatenate([np.full(len(np.arange(x0 + (PASO / 2 if i % 2 else 0), x1, PASO)), f) for i, f in enumerate(filas)])
    region = np.full(px.shape, "", dtype=object)
    extra = []
    for rid, pols in regiones.items():
        for pol in pols:
            ex, huecos = pol[0], pol[1:]
            mx, Mx = ex.min(axis=0), ex.max(axis=0)
            caja = (px >= mx[0]) & (px <= Mx[0]) & (py >= mx[1]) & (py <= Mx[1]) & (region == "")
            idx = np.where(caja)[0]
            dentro_pol = dentro(px[idx], py[idx], ex)
            for h in huecos:
                dentro_pol &= ~dentro(px[idx], py[idx], h)
            region[idx[dentro_pol]] = rid
            # islas o trozos sin ningún punto de la rejilla: un punto en su centro para que no desaparezcan
            area = abs(np.dot(ex[:, 0], np.roll(ex[:, 1], 1)) - np.dot(ex[:, 1], np.roll(ex[:, 0], 1))) / 2
            if not dentro_pol.any() and area > PASO * PASO * .15:
                extra.append((*ex.mean(axis=0), rid))
    sel = region != ""
    puntos = [(x, y, r) for x, y, r in zip(px[sel], py[sel], region[sel])] + extra

    # punto de borde: algún vecino de la rejilla pertenece a otra comunidad (se dibuja más pequeño y marca la frontera)
    clave = {(round(x / PASO * 2), round(y / dy)): r for x, y, r in puntos}
    vecinos = [(2, 0), (-2, 0), (1, 1), (-1, 1), (1, -1), (-1, -1)]
    w, h = x1 - x0, y1 - y0
    pts = []
    for x, y, r in puntos:
        i, j = round(x / PASO * 2), round(y / dy)
        borde = any(clave.get((i + a, j + b), r) != r for a, b in vecinos)
        pts.append([round((x - x0) / w, 4), round((y - y0) / h, 4), r, int(borde)])

    # recuadro de Canarias (normalizado), para dibujar su marco
    cn = np.array([[p[0], p[1]] for p in pts if p[2] == "CN"])
    marco = [round(float(v), 4) for v in (*cn.min(axis=0), *cn.max(axis=0))]
    datos = {"ar": round(w / h, 4), "paso": round(PASO / w, 5), "cn": marco, "pts": pts}
    SALIDA.write_text('"use strict";\n// Rejilla de puntos de España por comunidad (fronteras: es-atlas / IGN, CC BY 4.0). Generado por trabajo/09_mapa_ccaa.py.\n'
                      f"const MAPA_CCAA = {json.dumps(datos, ensure_ascii=False, separators=(',', ':'))};\n")
    cuenta = {}
    for p in pts:
        cuenta[p[2]] = cuenta.get(p[2], 0) + 1
    print(f"{len(pts)} puntos · proporción {w / h:.3f} · {SALIDA.stat().st_size / 1024:.0f} KB")
    print(dict(sorted(cuenta.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
