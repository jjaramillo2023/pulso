"""¿El ámbar acierta más que el rojo? Error medido de cada color de la simulación.

Las 23 preguntas de la calibración del simulador (04_calibrar_simulador.py) se tratan como nuevas:
se quita del índice la propia pregunta y sus otras olas, y se pasa cada una por la búsqueda y el
juez del motor, igual que una pregunta de un usuario. Así se sabe qué color le habría tocado
(ámbar si hay una pregunta CIS parecida, rojo si no) y se separa su error medido.

Salida: resultados/calibracion_simulador/por_modo.csv (resumen) y ruta_por_pregunta.csv
Uso: cd trabajo && ../.venv/bin/python 10_validar_ambar_rojo.py
"""
import numpy as np
import pandas as pd
import pyreadstat

from armonizar import MICRO, RAIZ
from banco_preguntas import PREGUNTAS
from motor import UMBRAL_CANDIDATA, UMBRAL_MISMA, Motor

SALIDA = RAIZ / "resultados" / "calibracion_simulador"
CONDICION = "actitudes_relevantes"  # la configuración que usa el motor
N_BOOT = 5000
SEMILLA = 20261020


def misma_pregunta():
    """(estudio, variable) → conjunto de (estudio, variable) que son la misma pregunta en otra ola del CIS
    (mismo enunciado en el libro de códigos y mismas respuestas)."""
    firmas = {}
    for d in sorted(MICRO.iterdir()):
        _, meta = pyreadstat.read_sav(str(d / f"{d.name}.sav"), metadataonly=True)
        for v, lab in zip(meta.column_names, meta.column_labels):
            vl = meta.variable_value_labels.get(v)
            if lab and vl:
                firma = (lab.strip().lower(), tuple(sorted(vl.items())))
                firmas.setdefault(firma, set()).add((int(d.name), v))
    return {x: grupo for grupo in firmas.values() for x in grupo}


def ruta(motor, q, olas):
    """Color que daría el motor a la pregunta si el CIS no la hubiera hecho nunca."""
    propia = olas.get((q["estudio"], q["variable"]), set()) | {(q["estudio"], q["variable"])}
    todas = [c for c in motor.buscar(q["texto"], todas=True) if (c[0]["estudio"], c[0]["variable"]) not in propia]
    candidatos = [c for c in todas[:3] if c[1] >= UMBRAL_CANDIDATA]
    if not candidatos:
        return "rojo", todas[0], "ninguna"
    relacion, (ref, sim) = motor.juzgar(q["texto"], candidatos)
    if relacion == "misma" and (ref["id"] != candidatos[0][0]["id"] or sim < UMBRAL_MISMA):
        relacion = "parecida"
    color = {"misma": "verde", "parecida": "ámbar", "ninguna": "rojo"}[relacion]
    return color, (ref, sim), relacion


def main():
    motor = Motor()
    olas = misma_pregunta()
    calib = pd.read_csv(SALIDA / "calibracion_por_pregunta.csv")
    calib = calib[calib["condicion"] == CONDICION].set_index("pregunta")
    filas = []
    for q in PREGUNTAS:
        if q["id"] not in calib.index:
            continue
        color, (ref, sim), relacion = ruta(motor, q, olas)
        filas.append({"pregunta": q["id"], "texto": q["texto"], "color": color, "relacion_juez": relacion,
                      "similitud": round(sim, 3), "pregunta_cis_parecida": ref["texto"], "estudio_parecida": ref["estudio"],
                      "error_total_pts": calib.loc[q["id"], "error_total_pts"],
                      "error_uniforme_pts": calib.loc[q["id"], "error_uniforme_pts"]})
        print(f"{q['id']:26s} {color:6s} sim {sim:.2f} · {ref['texto'][:70]}", flush=True)
    tabla = pd.DataFrame(filas)
    tabla.to_csv(SALIDA / "ruta_por_pregunta.csv", index=False)

    rng = np.random.default_rng(SEMILLA)
    resumen = []
    for color, g in tabla.groupby("color"):
        e = g["error_total_pts"].to_numpy()
        boot = [rng.choice(e, len(e)).mean() for _ in range(N_BOOT)]
        lo, hi = np.percentile(boot, [2.5, 97.5])
        resumen.append({"color": color, "preguntas": len(g), "error_total_pts": round(e.mean(), 2),
                        "ic95_bajo": round(lo, 1), "ic95_alto": round(hi, 1),
                        "error_uniforme_pts": round(g["error_uniforme_pts"].mean(), 2)})
    resumen = pd.DataFrame(resumen)
    resumen.to_csv(SALIDA / "por_modo.csv", index=False)
    print("\n=== Error medio por color (preguntas tratadas como nuevas, pp por opción)")
    print(resumen.to_string(index=False))


if __name__ == "__main__":
    main()
