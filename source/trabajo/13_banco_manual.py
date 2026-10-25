"""Preguntas del CIS añadidas a mano al banco ampliado como evidencia directa (semáforo verde).

06_banco_ampliado.py descarta voto, líderes y preguntas con decenas de categorías; aquí se añaden
a mano, con las opciones agrupadas para que se lean bien y redacciones alternativas («alias») para encontrarlas
al preguntar de forma coloquial:
- Elecciones (barómetro 3577, sep 2026). Es la intención DIRECTA de voto que dijo la gente al CIS,
  no la estimación de voto que publica el CIS (que corrige con recuerdo de voto y simpatía).
- El problema que más afecta a cada persona (barómetros 3528, 3536 y 3577: tres olas, con evolución),
  con las ~95 categorías del CIS agrupadas por temas.
El CIS solo entrevista a españoles: como en el resto del banco, las personas extranjeras de la
población sintética reciben la respuesta media de los encuestados con su mismo perfil.

Se puede relanzar: sustituye sus propias entradas en banco.json y revision_llm.json.
Si se vuelve a ejecutar 06_banco_ampliado.py, hay que ejecutar este script después.

Uso: cd trabajo && ../.venv/bin/python 13_banco_manual.py
"""
import json

import pandas as pd

from armonizar import RAIZ, cargar_cis, cargar_poblacion
from modelo import crear_codificador, entrenar, predecir_poblacion

AMPLIADO = RAIZ / "resultados" / "banco_ampliado"
FECHAS = {3528: "oct 2025", 3536: "dic 2025", 3577: "sep 2026"}
NACIONALISTAS = "Partidos nacionalistas y regionalistas"
PREGUNTAS = [
    {"estudio": 3577, "variable": "INTENCIONGR", "etiqueta": "Intención de voto en unas supuestas elecciones generales",
     "texto": "Si mañana se celebrasen elecciones generales, ¿a qué partido votaría? (intención directa de voto)",
     "alias": ["¿A quién vas a votar en las próximas elecciones?", "¿Por quién votarías en las próximas elecciones generales?",
               "¿A qué partido votarías si hubiera elecciones mañana?", "¿Qué partido vas a votar en las elecciones?"],
     "no_misma": r"\bgan(a|ara|aria|e|en)\b|\bvencer|\bgobernar",  # predecir quién gana no es la intención propia
     "opciones": {1: "PSOE", 2: "PP", 3: "Vox", 21: "Sumar", 8: "Podemos", 28: "Se Acabó la Fiesta",
                  901: NACIONALISTAS, 902: NACIONALISTAS, 1201: NACIONALISTAS, 1601: NACIONALISTAS, 1602: NACIONALISTAS,
                  503: NACIONALISTAS, 1501: NACIONALISTAS, 101: NACIONALISTAS,
                  6: "Otros partidos", 29: "Otros partidos", 8995: "Otros partidos",
                  8996: "En blanco o nulo", 9977: "En blanco o nulo", 9997: "No votaría", 9998: "No sabe todavía"}},
    {"estudio": 3577, "variable": "PREFPTER", "etiqueta": "Preferencia personal como presidente del Gobierno central",
     "texto": "¿Quién preferiría que fuera el presidente o la presidenta del Gobierno?",
     "alias": ["¿Quién te gustaría que fuera el presidente del Gobierno?", "¿Quién es tu candidato preferido para presidir el Gobierno?"],
     "opciones": {1: "Pedro Sánchez", 2: "Alberto Núñez Feijóo", 3: "Santiago Abascal", 4: "Yolanda Díaz",
                  8: "Isabel Díaz Ayuso", **{k: "Otro líder" for k in (5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 96)},
                  97: "Ninguno"}},
    {"estudio": 3577, "variable": "PROBVOTO", "etiqueta": "Escala de probabilidad (0-10) de ir a votar en elecciones generales",
     "texto": "Del 0 al 10, ¿qué probabilidad hay de que vaya a votar en las próximas elecciones generales?",
     "alias": ["¿Vas a ir a votar en las próximas elecciones?", "¿Irás a votar en las elecciones generales?"],
     "opciones": {0: "0 Seguro que no iría a votar", **{k: str(k) for k in range(1, 10)}, 10: "10 Seguro que iría a votar"},
     "escala": True},
]
# Problema que más le afecta personalmente: categorías del CIS por tema; el resto, «Otros problemas».
GRUPOS_PROBLEMA = {  # máximo 5 opciones para que se lea bien en la presentación
    "La vivienda": [7, 36, 38, 81],
    "La economía, el empleo y el coste de la vida": [8, 12, 34, 35, 37, 42, 58, 79, 1, 9, 20, 32, 48, 62],
    "La sanidad y la salud": [6, 53, 63, 78],
    "La política": [11, 13, 24, 26, 30, 45, 46, 50, 51, 52, 56, 65, 70, 90, 91, 92, 93, 95, 451],
}
for estudio in FECHAS:
    PREGUNTAS.append({"estudio": estudio, "variable": "PPERSONAL1",
                      "etiqueta": "Problema que más le afecta personalmente (primer problema)",
                      "texto": "¿Cuál es el problema que más le afecta a usted personalmente?",
                      "alias": ["¿Qué problema te afecta más a ti personalmente?", "¿Cuál es tu principal problema hoy en día?"],
                      "opciones": {c: g for g, cs in GRUPOS_PROBLEMA.items() for c in cs},
                      "resto": "Otros problemas o ninguno", "ninguno": {997: "Otros problemas o ninguno"}})


def main():
    pob = cargar_poblacion()
    cis = {}
    banco = json.loads((AMPLIADO / "banco.json").read_text(encoding="utf-8"))
    revision = json.loads((AMPLIADO / "revision_llm.json").read_text(encoding="utf-8"))
    ids = {f"{p['estudio']}_{p['variable']}" for p in PREGUNTAS}
    banco = [b for b in banco if b["id"] not in ids]
    for p in PREGUNTAS:
        estudio = p["estudio"]
        if estudio not in cis:
            cis[estudio] = cargar_cis(estudio)
        df_base, meta = cis[estudio][0].dropna(subset=["ccaa"]), cis[estudio][1]
        clave = f"{estudio}_{p['variable']}"
        cods = dict(p["opciones"])
        if "resto" in p:  # cualquier otra categoría sustantiva del cuestionario (no N.S./N.C.)
            cods.update({int(k): p["resto"] for k in meta.variable_value_labels[p["variable"]] if int(k) not in cods and int(k) < 997})
            cods.update(p["ninguno"])
        if p.get("escala"):  # escala 0-10 en tres tramos, como en 06_banco_ampliado.py
            mapa = {k: ("Bajo (0-3)" if k <= 3 else "Medio (4-6)" if k <= 6 else "Alto (7-10)") for k in cods}
            orden = ["Bajo (0-3)", "Medio (4-6)", "Alto (7-10)"]
        else:
            mapa, orden = cods, list(dict.fromkeys(cods.values()))
        df = df_base.copy()
        df["respuesta"] = df[p["variable"]].map(lambda x: mapa.get(int(x), "NS/NC") if pd.notna(x) else "NS/NC")
        cod = crear_codificador(df, pob)
        probs = predecir_poblacion(entrenar(df, cod), cod, pob, df)
        probs.astype("float32").to_parquet(AMPLIADO / "probs" / f"{clave}.parquet")
        real = pd.get_dummies(df["respuesta"]).astype(float).mul(df["peso"], axis=0).sum() / df["peso"].sum() * 100
        sint = probs.mul(pob["peso"], axis=0).sum() / pob["peso"].sum() * 100
        error = float((sint - real.reindex(sint.index, fill_value=0)).abs().mean())
        revision[clave] = {"estudio": str(estudio), "variable": p["variable"], "etiqueta": p["etiqueta"], "bloque": "",
                           "opciones": {str(k): v for k, v in cods.items()}, "valida": True, "pregunta": p["texto"],
                           "tema": "Sociedad"}
        banco.append({"id": clave, "estudio": estudio, "variable": p["variable"], "texto": p["texto"],
                      "etiqueta": p["etiqueta"], "tema": "Sociedad", "fecha": FECHAS[estudio], "n": int(len(df)), "alias": p.get("alias", []), **({"no_misma": p["no_misma"]} if "no_misma" in p else {}),
                      "opciones": [o for o in orden if o in probs.columns] + (["NS/NC"] if "NS/NC" in probs.columns else []),
                      "error_calibracion_pts": round(error, 2)})
        print(f"{clave:20s} n={len(df)} error {error:.2f} pp")
        print("   real CIS:  " + " · ".join(f"{k} {v:.1f}" for k, v in real.sort_values(ascending=False).items()))
        print("   sintética: " + " · ".join(f"{k} {v:.1f}" for k, v in sint.sort_values(ascending=False).items()))
    (AMPLIADO / "banco.json").write_text(json.dumps(banco, ensure_ascii=False, indent=1), encoding="utf-8")
    (AMPLIADO / "revision_llm.json").write_text(json.dumps(revision, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
