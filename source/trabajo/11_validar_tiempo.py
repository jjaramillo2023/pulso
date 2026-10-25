"""Validación en el tiempo del modo verde con todas las preguntas que el CIS repite entre olas.

Para cada pregunta de opinión del banco ampliado que vuelve a aparecer en la ola siguiente (mismo
enunciado y mismas respuestas), el modelo entrenado con la ola anterior, aplicado a las 25.000
personas, se compara con lo que respondió la gente en la ola siguiente, que el modelo no vio.

Comparaciones (error medio por opción, en pp, sin NS/NC):
  pulso            el modelo de la ola anterior, tal cual (lo que daría el semáforo verde hoy)
  persistencia     repetir el resultado bruto de la ola anterior en cada grupo (sin modelo)
  pulso_reanclado  pulso con el total nacional fijado al de la ola nueva: mide solo el reparto por grupos
  sin_modelo       el total nacional de la ola nueva en todos los grupos (referencia de pulso_reanclado)
  ruido            error esperado solo por el tamaño de la muestra de la ola nueva en cada grupo

Salida: resultados/validacion_temporal/por_pregunta.csv y resumen.csv
Uso: cd trabajo && ../.venv/bin/python 11_validar_tiempo.py
"""
import importlib
import json
import re

import numpy as np
import pandas as pd

from armonizar import RAIZ, cargar_cis, cargar_poblacion

validar_ambar = importlib.import_module("10_validar_ambar_rojo")
AMPLIADO = RAIZ / "resultados" / "banco_ampliado"
SALIDA = RAIZ / "resultados" / "validacion_temporal"
# orden real de las olas (8825 es anual y no se repite)
FECHA = {3528: "2025-10", 3535: "2025-12", 3536: "2025-12", 3554: "2026-02", 3560: "2026-05",
         3569: "2026-06", 3575: "2026-07", 3577: "2026-09"}
# datos del hogar o del entrevistado y compras del hogar: no son opinión
NO_OPINION = r"^(CURSOMULTIPLE|INGREHOG|MOMENNAC|NUMPERSONAS|P25B|P36|VIVIENDA|PERPRIN|P1_)"
DESGLOSES = [None, "sexo", "grupo_edad", "ccaa"]
NSNC = "NS/NC"


def respuestas(df, r):
    """Misma recodificación que 06_banco_ampliado.py."""
    cods = {int(k): l for k, l in r["opciones"].items()}
    es_escala = len(cods) >= 10 and all(str(k) in l or l.split()[0].isdigit() for k, l in cods.items() if l)
    mapa = {k: ("Bajo (0-3)" if k <= 3 else "Medio (4-6)" if k <= 6 else "Alto (7-10)") for k in cods} if es_escala else cods
    return df[r["variable"]].map(lambda x: mapa.get(int(x), NSNC) if pd.notna(x) else NSNC)


def reparto(pesos, indicadoras, grupos, opciones):
    p = indicadoras.reindex(columns=opciones, fill_value=0).mul(pesos, axis=0)
    t = p.groupby(grupos).sum() if grupos is not None else p.sum().to_frame("Total").T
    return t.div(t.sum(axis=1), axis=0) * 100


def reanclar(probs, pesos, total):
    ajustado = probs.copy()
    for _ in range(50):
        actual = ajustado.mul(pesos, axis=0).sum() / pesos.sum() * 100
        ajustado = ajustado * (total / actual.replace(0, np.nan)).fillna(1)
        ajustado = ajustado.div(ajustado.sum(axis=1), axis=0)
    return ajustado


def pares(banco, revision):
    """(id ola anterior, id ola siguiente) para cada pregunta repetida en olas consecutivas."""
    olas = validar_ambar.misma_pregunta()
    en_banco = {(b["estudio"], b["variable"]): b["id"] for b in banco}
    salida = []
    for grupo in {frozenset(g) for g in olas.values() if len(g) > 1}:
        serie = sorted((x for x in grupo if x[0] in FECHA and f"{x[0]}_{x[1]}" in revision), key=lambda x: FECHA[x[0]])
        for a, b in zip(serie, serie[1:]):
            if a in en_banco and FECHA[a[0]] < FECHA[b[0]] and not re.match(NO_OPINION, a[1]):
                salida.append((en_banco[a], f"{b[0]}_{b[1]}"))
    return sorted(salida)


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    banco = json.loads((AMPLIADO / "banco.json").read_text(encoding="utf-8"))
    revision = json.loads((AMPLIADO / "revision_llm.json").read_text(encoding="utf-8"))
    textos = {b["id"]: b["texto"] for b in banco}
    pob = cargar_poblacion()
    cis = {}
    filas = []
    for viejo, nuevo in pares(banco, revision):
        rv, rn = revision[viejo], revision[nuevo]
        for r in (rv, rn):
            if r["estudio"] not in cis:
                cis[r["estudio"]] = cargar_cis(r["estudio"])[0]
        antes = cis[rv["estudio"]].assign(respuesta=lambda d: respuestas(d, rv)).dropna(subset=["ccaa"])
        despues = cis[rn["estudio"]].assign(respuesta=lambda d: respuestas(d, rn)).dropna(subset=["ccaa"])
        antes, despues = antes[antes["respuesta"] != NSNC], despues[despues["respuesta"] != NSNC]
        probs = pd.read_parquet(AMPLIADO / "probs" / f"{viejo}.parquet")
        opciones = [o for o in probs.columns if o != NSNC]
        probs = probs[opciones].astype(float)
        probs = probs.div(probs.sum(axis=1), axis=0)
        total_nuevo = reparto(despues["peso"], pd.get_dummies(despues["respuesta"]).astype(float), None, opciones).iloc[0]
        ancladas = reanclar(probs, pob["peso"], total_nuevo)
        for grupo in DESGLOSES:
            gp = pob[grupo] if grupo else None
            gd, ga = (despues[grupo] if grupo else None), (antes[grupo] if grupo else None)
            real = reparto(despues["peso"], pd.get_dummies(despues["respuesta"]).astype(float), gd, opciones)
            n = despues.groupby(grupo).size() if grupo else pd.Series({"Total": len(despues)})
            real = real[n.reindex(real.index).fillna(0) >= 30]  # grupos con muy pocas entrevistas
            real = real[~real.index.isin(["NC"])]
            idx = real.index
            pred = {
                "pulso": reparto(pob["peso"], probs, gp, opciones),
                "persistencia": reparto(antes["peso"], pd.get_dummies(antes["respuesta"]).astype(float), ga, opciones),
                "pulso_reanclado": reparto(pob["peso"], ancladas, gp, opciones),
                "sin_modelo": pd.DataFrame([total_nuevo.to_numpy()] * len(idx), index=idx, columns=opciones),
            }
            fila = {"pregunta": viejo, "ola_siguiente": nuevo, "texto": textos[viejo], "desglose": grupo or "total",
                    "grupos": len(idx), "n_ola_siguiente": len(despues)}
            for nombre, tabla in pred.items():
                fila[nombre] = float((tabla.reindex(idx) - real).abs().mean(axis=1).mean())
            p = real / 100
            ruido = (np.sqrt(2 / np.pi) * np.sqrt(p * (1 - p) / n.reindex(idx).to_numpy()[:, None]) * 100).mean(axis=1)
            fila["ruido"] = float(ruido.mean())
            filas.append(fila)
        print(f"{viejo:18s} → {nuevo:18s} {textos[viejo][:70]}", flush=True)
    tabla = pd.DataFrame(filas).round(2)
    tabla.to_csv(SALIDA / "por_pregunta.csv", index=False)
    cols = ["pulso", "persistencia", "pulso_reanclado", "sin_modelo", "ruido"]
    resumen = tabla.groupby("desglose", sort=False)[cols].mean().round(2)
    resumen.insert(0, "preguntas", tabla.groupby("desglose", sort=False).size())
    resumen.to_csv(SALIDA / "resumen.csv")
    print(f"\n=== {tabla['pregunta'].nunique()} preguntas repetidas · error medio por opción (pp)")
    print(resumen.to_string())


if __name__ == "__main__":
    main()
