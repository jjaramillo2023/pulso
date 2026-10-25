"""Entrena un modelo por pregunta del banco CIS y da a cada persona sintética su perfil de actitudes.

Salidas (resultados/perfiles/):
- probs/<id>.parquet: probabilidad de cada respuesta para cada persona sintética.
- actitudes_poblacion.parquet: P(polo) de cada pregunta por persona (base de los perfiles).
- banco.json: texto, opciones, distribución real CIS y calibración de cada pregunta.

Uso: cd trabajo && ../.venv/bin/python 03_perfiles_actitudes.py
"""
import json
from functools import lru_cache

import pandas as pd

from armonizar import RAIZ, cargar_cis, cargar_poblacion
from banco_preguntas import ESCALA_0_10, PREGUNTAS
from modelo import crear_codificador, entrenar, predecir_poblacion

SALIDA = RAIZ / "resultados" / "perfiles"
NSNC = "NS/NC"


@lru_cache(maxsize=None)
def encuesta(estudio):
    return cargar_cis(estudio)[0]


def agrupar(valores, grupos):
    """Convierte los códigos CIS en las categorías de la pregunta (resto → NS/NC)."""
    if grupos in ("escala_0_10", "escala_1_10"):
        mapa = {v: k for k, rango in ESCALA_0_10.items() for v in rango}
        mapa[0] = "bajo"
    else:
        mapa = {c: nombre for nombre, codigos in grupos.items() for c in codigos}
    return valores.map(lambda v: mapa.get(int(v), NSNC) if pd.notna(v) else NSNC)


def distribucion(pesos, probs):
    d = probs.mul(pesos, axis=0).sum()
    return (d / d.sum() * 100).round(1)


def main():
    (SALIDA / "probs").mkdir(parents=True, exist_ok=True)
    pob = cargar_poblacion()
    actitudes = pd.DataFrame({"id": pob["id"]})
    banco = []

    for q in PREGUNTAS:
        df = encuesta(q["estudio"]).copy()
        df["respuesta"] = agrupar(df[q["variable"]], q["grupos"])
        df = df.dropna(subset=["ccaa"])

        cod = crear_codificador(df, pob)
        modelo = entrenar(df, cod)
        probs = predecir_poblacion(modelo, cod, pob, df)
        probs.astype("float32").assign(id=pob["id"]).to_parquet(SALIDA / "probs" / f"{q['id']}.parquet")

        # P(polo) entre quienes responden (sin NS/NC): es lo que describe la actitud.
        validas = probs.drop(columns=[NSNC], errors="ignore")
        actitudes[q["id"]] = (validas[q["polo"]].sum(axis=1) / validas.sum(axis=1)).astype("float32")

        real = distribucion(df["peso"], pd.get_dummies(df["respuesta"]).astype(float))
        pred = distribucion(pob["peso"], probs)
        error = (pred - real.reindex(pred.index, fill_value=0)).abs().mean()
        banco.append({**{k: q[k] for k in ("id", "estudio", "variable", "tema", "texto", "polo", "frase")},
                      "opciones": list(real.index), "n": int(len(df)),
                      "real_cis": real.to_dict(), "poblacion_sintetica": pred.to_dict(),
                      "error_calibracion_pts": round(float(error), 2)})
        print(f"{q['id']:28s} n={len(df):5d}  error medio misma ola {error:4.1f} pts  "
              f"polo real {real.reindex(q['polo']).sum():5.1f}% · sintético {pred.reindex(q['polo']).sum():5.1f}%")

    actitudes.to_parquet(SALIDA / "actitudes_poblacion.parquet")
    (SALIDA / "banco.json").write_text(json.dumps(banco, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(banco)} preguntas · guardado en {SALIDA}")


if __name__ == "__main__":
    main()
