"""Motor de pulso: de una pregunta en texto libre a un resultado por grupos con su confianza.

Modos:
- evidencia:  la pregunta coincide con una pregunta real del CIS → modelo entrenado con respuestas reales.
- analogia:   hay preguntas CIS parecidas → simulación con LLM, anclada en actitudes reales.
- simulacion: tema nuevo → simulación con LLM; resultado orientativo.
"""
import difflib
import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.request
from functools import lru_cache

import numpy as np
import pandas as pd

from armonizar import RAIZ, cargar_cis
from banco_preguntas import ESCALA_0_10, PREGUNTAS
from simulador import datos, elegir_arquetipos, expandir, simular

PERFILES = RAIZ / "resultados" / "perfiles"
AMPLIADO = RAIZ / "resultados" / "banco_ampliado"
CALIBRACION = RAIZ / "resultados" / "calibracion_simulador"
CACHE = RAIZ / "resultados" / "cache_consultas"
CACHE_COMPARAR = RAIZ / "resultados" / "cache_comparar"
OLLAMA = "http://localhost:11434"
MODELO_LLM = "llama3.1:8b"
MODELO_EMB = "bge-m3"
N_VISIBLES = 1200
N_ARQUETIPOS = 100
UMBRAL_RELEVANTE = 0.50  # actitudes CIS que se consideran relacionadas con la pregunta
UMBRAL_CANDIDATA = 0.60  # por debajo, ninguna pregunta CIS se parece (medido con bge-m3)
UMBRAL_MISMA = 0.83      # para usar la evidencia directa, además del juicio del LLM
# Modo demo (para grabar o presentar): las respuestas ya calculadas tardan lo que tardaría el motor y
# muestran las mismas fases. Segundos; 0 = al instante. Ej.: PULSO_ESPERA_VERDE=20 PULSO_ESPERA_LLM=120
ESPERA_DEMO = {"evidencia": float(os.environ.get("PULSO_ESPERA_VERDE", 0)), "llm": float(os.environ.get("PULSO_ESPERA_LLM", 0))}
TEMAS = ["Vivienda", "Soledad", "Tecnología e IA", "Medio ambiente", "Salud", "Consumo"]
TEMA_BANCO = {"vivienda": "Vivienda", "soledad": "Soledad", "tecnología e IA": "Tecnología e IA",
              "medio ambiente": "Medio ambiente", "salud": "Salud", "consumo": "Consumo"}
EDADES = [("18-29", 18, 29), ("30-44", 30, 44), ("45-59", 45, 59), ("60-74", 60, 74), ("75+", 75, 120)]
IDEOLOGIA_GRUPO = {"1-2": "Izquierda", "3-4": "Izquierda", "5-6": "Centro", "7-8": "Derecha", "9-10": "Derecha"}
# dimensiones extra de desglose: nombre visible → columna de la población y orden de sus valores
DIMENSIONES = {
    "Ideología": ("ideol_grupo", ["Izquierda", "Centro", "Derecha"]),
    "Estudios": ("estudios", ["Básicos", "Secundaria/FP", "Universitarios"]),
    "Trabajo": ("sitlab", ["Trabaja", "En paro", "Estudiante", "Jubilado", "Hogar/otros"]),
    "Renta del hogar": ("renta", ["Baja (Q1-Q2)", "Media (Q3)", "Alta (Q4-Q5)"]),
    "Vivienda": ("vivienda", ["Propiedad", "Alquiler", "Cesión u otra"]),
    "Vive solo": ("vive_solo", ["Vive solo/a", "Vive acompañado/a"]),
    "Uso de IA": ("usa_ia", ["Usa IA", "No usa IA"]),
    "Municipio": ("municipio", ["Ciudad grande", "Ciudad media", "Rural"]),
}
CCAA_ID = {"Galicia": "GA", "Asturias": "AS", "Cantabria": "CB", "País Vasco": "PV", "Navarra": "NA",
           "La Rioja": "RI", "Aragón": "AR", "Cataluña": "CT", "Castilla y León": "CL", "Madrid": "MD",
           "Castilla-La Mancha": "CM", "Extremadura": "EX", "C. Valenciana": "VC", "Murcia": "MC",
           "Andalucía": "AN", "Baleares": "IB", "Canarias": "CN", "Ceuta": "CE", "Melilla": "ML"}
ESCALA = {"bajo": "Bajo (0-3)", "medio": "Medio (4-6)", "alto": "Alto (7-10)"}
# Preguntas repetidas en varias olas del CIS: serie real para el gráfico de tendencia.
SERIES = {
    "clima_preocupacion": [(3536, "P1", "dic 2025"), (3577, "P13", "sep 2026")],
    "economia_personal": [(3528, "ECOPER", "oct 2025"), (3536, "ECOPER", "dic 2025"), (3577, "ECOPER", "sep 2026")],
    "economia_espana": [(3528, "ECOESP", "oct 2025"), (3536, "ECOESP", "dic 2025"), (3577, "ECOESP", "sep 2026")],
    "vivienda_precio_futuro": [(3569, "P17", "jun 2026"), (3575, "P17", "jul 2026")],
    "vivienda_comprar": [(3569, "P18", "jun 2026"), (3575, "P18", "jul 2026")],
}
FECHAS = {3528: "oct 2025", 3535: "dic 2025", 3536: "dic 2025", 3554: "feb 2026", 3560: "may 2026",
          3569: "jun 2026", 3575: "jul 2026", 3577: "sep 2026", 8825: "2025"}


def _post(ruta, cuerpo, timeout=120):
    req = urllib.request.Request(OLLAMA + ruta, data=json.dumps(cuerpo).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower().strip()


VACIAS = {"el", "la", "los", "las", "lo", "de", "del", "y", "e", "o", "u", "a", "al", "en", "un", "una", "unos", "unas"}


def _limpio(texto):
    """Sin acentos, signos ni espacios de más."""
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", _norm(texto)).split())


def _palabras(texto):
    """Palabras con contenido de una opción, en orden: «La economía, el empleo y el coste de la vida» → «coste economia empleo vida»."""
    return " ".join(sorted(set(_limpio(texto).split()) - VACIAS))


NSNC = _palabras("NS/NC")


def embeber(textos, tipo):
    prefijo = ""  # bge-m3 no usa prefijos
    v = np.array(_post("/api/embed", {"model": MODELO_EMB, "input": [prefijo + t for t in textos]})["embeddings"])
    return v / np.linalg.norm(v, axis=1, keepdims=True)


class Motor:
    def __init__(self):
        self.pob, banco = datos()
        definiciones = {q["id"]: q for q in PREGUNTAS}
        self.banco = [{**q, "grupos": definiciones[q["id"]]["grupos"], "etiquetas": definiciones[q["id"]].get("etiquetas")} for q in banco.values()]
        revision = AMPLIADO / "revision_llm.json"
        self.revision = json.loads(revision.read_text(encoding="utf-8")) if revision.exists() else {}
        # Banco ampliado (06_banco_ampliado.py): más preguntas reales del CIS, solo como evidencia.
        ya = {(q["estudio"], q["variable"]) for q in self.banco}
        ampliado = json.loads((AMPLIADO / "banco.json").read_text(encoding="utf-8")) if (AMPLIADO / "banco.json").exists() else []
        basura = lambda q: re.search(r"MUESTRA|ITEMCOMIENZO", q["variable"]) or any("MUESTRA" in str(o) for o in q["opciones"])
        self.indice = self.banco + [{**q, "tipo": "ampliado"} for q in ampliado if (q["estudio"], q["variable"]) not in ya and not basura(q)]
        self.pob["ideol_grupo"] = self.pob["ideologia"].map(IDEOLOGIA_GRUPO)
        self.edad = pd.cut(self.pob["edad"], [0, 29, 44, 59, 74, 200], labels=[e[0] for e in EDADES]).astype(str)
        self.estrato = self.pob["sexo"] + "|" + self.pob["grupo_edad"] + "|" + self.pob["estudios"]
        self._visibles()
        self._indexar_banco()
        CACHE.mkdir(parents=True, exist_ok=True)

    # ---------- preparación ----------
    def _visibles(self):
        """Las personas que se dibujan: muestra ponderada por peso poblacional (sin Ceuta y Melilla)."""
        base = self.pob[(self.pob["peso"] > 0) & ~self.pob["ccaa"].isin(["Ceuta", "Melilla"])]
        rng = np.random.default_rng(1200)
        self.idx_vis = rng.choice(base.index, N_VISIBLES, replace=False, p=base["peso"] / base["peso"].sum())

    def _indexar_banco(self):
        ruta = PERFILES / "embeddings_indice.npz"
        # cada pregunta se busca por su texto y por sus redacciones alternativas («alias»), si las tiene
        filas = [(i, t) for i, q in enumerate(self.indice) for t in [q["texto"], *q.get("alias", [])]]
        self._fila_item = np.array([i for i, _ in filas])
        textos = [t for _, t in filas]
        clave = hashlib.sha1(("|".join(textos) + MODELO_EMB).encode()).hexdigest()
        if ruta.exists():
            guardado = np.load(ruta)
            if str(guardado["clave"]) == clave:
                self.emb_banco = guardado["emb"]
                return
        self.emb_banco = embeber(textos, "documento")
        np.savez(ruta, emb=self.emb_banco, clave=clave)

    # ---------- interpretación ----------
    def buscar(self, pregunta, todas=False):
        por_fila = self.emb_banco @ embeber([pregunta], "consulta")[0]
        sims = np.full(len(self.indice), -1.0)
        np.maximum.at(sims, self._fila_item, por_fila)  # de cada pregunta, su redacción más parecida
        # a igualdad de parecido, mejor la ola más reciente del CIS
        sims = sims + np.array([0.03 if "2026" in (q.get("fecha") or FECHAS.get(q["estudio"], "")) else 0 for q in self.indice])
        orden = np.argsort(-sims)
        pares = [(self.indice[i], float(sims[i])) for i in orden]
        return pares if todas else pares[:3]

    def juzgar(self, pregunta, candidatos):
        """El LLM decide si alguna pregunta CIS es la misma, una parecida o ninguna."""
        lista = "\n".join(f"{j + 1}) {q['texto']}" for j, (q, _) in enumerate(candidatos))
        prompt = (f"Pregunta del usuario: «{pregunta}»\nPreguntas reales de encuestas del CIS:\n{lista}\n\n"
                  "¿Alguna mide EXACTAMENTE lo mismo (mismo concepto, y sus respuestas contestan la pregunta del usuario)? "
                  "Si no, ¿alguna trata un tema muy cercano?\n"
                  'Devuelve solo JSON: {"relacion": "misma" | "parecida" | "ninguna", "numero": 1}')
        try:
            r = _post("/api/chat", {"model": MODELO_LLM, "stream": False, "format": "json",
                                    "messages": [{"role": "user", "content": prompt}],
                                    "options": {"temperature": 0, "num_predict": 40}})
            d = json.loads(r["message"]["content"])
            relacion = d.get("relacion") if d.get("relacion") in ("misma", "parecida", "ninguna") else "ninguna"
            j = int(d.get("numero") or 1) - 1
            return relacion, candidatos[j if 0 <= j < len(candidatos) else 0]
        except (OSError, ValueError, KeyError, TypeError):
            return "parecida", candidatos[0]

    def proponer(self, pregunta):
        """Tema y opciones de respuesta para una pregunta nueva (LLM local)."""
        prompt = (f"Pregunta de encuesta: «{pregunta}»\n"
                  f"1) Clasifícala en uno de estos temas: {', '.join(TEMAS)}, Otro.\n"
                  "2) Si la pregunta ya enumera opciones, úsalas literalmente. Si no, propone entre 2 y 5 "
                  "respuestas cortas (máximo 5 palabras), excluyentes, en español neutro, sin 'No sabe'. "
                  "Usa nombres concretos y reales, nunca marcadores como 'Partido A' u 'Opción 1'. "
                  "Si pregunta por partidos políticos de España, usa: PSOE, PP, Vox, Sumar, Otros partidos.\n"
                  'Devuelve solo JSON: {"tema": "...", "opciones": ["...", "..."]}')
        try:
            r = _post("/api/chat", {"model": MODELO_LLM, "stream": False, "format": "json",
                                    "messages": [{"role": "user", "content": prompt}],
                                    "options": {"temperature": 0, "num_predict": 120}})
            d = json.loads(r["message"]["content"])
            opciones = [str(o).strip() for o in d.get("opciones", []) if str(o).strip()][:5]
            tema = d.get("tema") if d.get("tema") in TEMAS else "Otro"
        except (OSError, ValueError, KeyError):
            opciones, tema = [], "Otro"
        return tema, opciones if len(opciones) >= 2 else ["Sí", "No"]

    def voces(self, pregunta, opciones):
        """Una frase corta en primera persona por opción, para las citas y las fichas de las personas."""
        lista = "\n".join(f"- {o}" for o in opciones)
        prompt = (f"Pregunta: «{pregunta}»\nPara cada respuesta, escribe dos frases muy cortas (máximo 12 palabras) "
                  f"en primera persona que diría alguien en España que la elige. Español neutro, sin 'vosotros'.\n{lista}\n"
                  'Devuelve solo JSON: {"voces": [["frase", "frase"], ...]} en el mismo orden.')
        try:
            r = _post("/api/chat", {"model": MODELO_LLM, "stream": False, "format": "json",
                                    "messages": [{"role": "user", "content": prompt}],
                                    "options": {"temperature": 0.4, "num_predict": max(400, 60 * len(opciones))}}, timeout=300)
            d = json.loads(r["message"]["content"])
            # el modelo de 8B a veces escribe mal la clave («vocas»): vale la primera lista que devuelva
            v = d.get("voces") or next((x for x in d.values() if isinstance(x, list)), [])
            v = [[str(f).replace("—", ",") for f in par][:2] for par in v][:len(opciones)]
        except (OSError, ValueError, KeyError, TypeError):
            v = []
        return v + [["Es lo que pienso.", "Lo tengo claro."]] * (len(opciones) - len(v))

    # ---------- cálculo ----------
    def _agregados(self, probs):
        """probs: DataFrame (25.000 filas × opciones). Porcentajes ponderados total y por grupo."""
        p = probs.mul(self.pob["peso"], axis=0)

        def tabla(grupos):
            t = p.groupby(grupos).sum()
            return (t.div(t.sum(axis=1), axis=0) * 100).round(1)

        total = p.sum() / p.sum().sum() * 100
        ccaa = tabla(self.pob["ccaa"].map(CCAA_ID))
        return {
            "total": total.round(1).tolist(),
            "ccaa": {k: v.tolist() for k, v in ccaa.iterrows()},
            "sexo": {("F" if k == "Mujer" else "M"): v.tolist() for k, v in tabla(self.pob["sexo"]).iterrows()},
            "edad": {k: v.tolist() for k, v in tabla(self.edad).iterrows() if k != "nan"},
            "grupos": {dim: {k: v.tolist() for k, v in tabla(self.pob[col]).iterrows() if k in orden}
                       for dim, (col, orden) in DIMENSIONES.items()},
            "grupos_orden": {dim: orden for dim, (_, orden) in DIMENSIONES.items()},
        }

    def _personas(self, probs):
        vis = self.pob.loc[self.idx_vis]
        filas = []
        for i, (idx, p) in enumerate(vis.iterrows()):
            etiquetas = [p["estudios"] if p["estudios"] != "NC" else None,
                         p["sitlab"] if p["sitlab"] != "NC" else None,
                         f"Ideología {p['ideologia']}" if p["ideologia"] != "no consta" else "Nacionalidad extranjera"]
            filas.append({"i": i, "edad": int(p["edad"]), "sexo": "F" if p["sexo"] == "Mujer" else "M",
                          "ccaa": CCAA_ID[p["ccaa"]], "tags": [e for e in etiquetas if e],
                          "g": {dim: (p[col] if isinstance(p[col], str) else None) for dim, (col, _) in DIMENSIONES.items()},
                          "p": [round(float(x), 4) for x in probs.loc[idx].tolist()]})
        return filas

    def _serie(self, q, etiquetas=None, probs=None):
        if q.get("tipo") == "ampliado" and etiquetas is not None:
            return self._serie_ampliado(q, etiquetas, probs)
        puntos = []
        for estudio, variable, etiqueta in SERIES.get(q["id"], []):
            df = cargar_cis(estudio)[0]
            v = df[variable]
            validos = v.notna() & (v < 8)
            cod = [c for nombre, cods in (q["grupos"] or {}).items() if nombre in q["polo"] for c in cods]
            pct = (df.loc[validos & v.isin(cod), "peso"].sum() / df.loc[validos, "peso"].sum()) * 100
            puntos.append({"etiqueta": etiqueta, "valor": round(float(pct), 1)})
        return puntos

    def _serie_ampliado(self, q, etiquetas, probs):
        """Si la misma pregunta está en varias olas del CIS, evolución real de la opción ganadora."""
        olas = [x for x in self.indice if x.get("tipo") == "ampliado" and x["variable"] == q["variable"] and x["etiqueta"] == q["etiqueta"]]
        if len(olas) < 2:
            return []
        lider = etiquetas[int(np.argmax(probs.mul(self.pob["peso"], axis=0).sum().to_numpy()))]
        opciones = [o for o in etiquetas if o != "NS/NC"]
        puntos = []
        for ola in sorted(olas, key=lambda x: x["estudio"] if x["estudio"] < 8000 else 3500):
            try:
                real = self._real_cis(ola, opciones)["total"]
                puntos.append({"etiqueta": ola.get("fecha") or FECHAS.get(ola["estudio"], ""), "valor": real[opciones.index(lider)]})
            except (KeyError, ValueError, TypeError):
                continue
        return puntos if len(puntos) >= 2 else []

    def _evidencia(self, q, sim, informar):
        informar("respondiendo", 1, 1)
        if q.get("tipo") == "ampliado":
            probs = pd.read_parquet(AMPLIADO / "probs" / f"{q['id']}.parquet")
            orden = [o for o in q["opciones"] if o != "NS/NC"]
        else:
            probs = pd.read_parquet(PERFILES / "probs" / f"{q['id']}.parquet").drop(columns=["id"])
            orden = ["bajo", "medio", "alto"] if isinstance(q["grupos"], str) else list(q["grupos"])
        probs.index = self.pob.index
        opciones = [o for o in orden if o in probs.columns] + (["NS/NC"] if "NS/NC" in probs.columns else [])
        probs = probs[opciones].astype(float)
        probs = probs.div(probs.sum(axis=1), axis=0)
        etiquetas = self._etiquetas(q, opciones)
        n = q["n"]
        self._n_cis = self._muestras_cis(q)
        lider = max(range(len(opciones)), key=lambda j: probs.mul(self.pob["peso"], axis=0).sum().iloc[j])
        share = probs.mul(self.pob["peso"], axis=0).sum() / self.pob["peso"].sum()
        moe = 1.96 * np.sqrt(share.iloc[lider] * (1 - share.iloc[lider]) / n) * 100
        error = round(float(np.hypot(moe, q["error_calibracion_pts"])), 1)
        return probs, etiquetas, {
            "nivel": 3, "error_pp": error, "n": n,
            "texto": f"Modelo entrenado con {n:,} entrevistas del CIS".replace(",", ".")
                     + f" (estudio {q['estudio']}, {q.get('fecha') or FECHAS.get(q['estudio'], '')}) y aplicado a la población sintética.",
        }

    def _opciones_cis(self, q, opciones):
        """¿Las opciones que escribió el usuario son las de la pregunta del CIS (sin contar NS/NC)?"""
        if q.get("tipo") == "ampliado":
            orden = [o for o in q["opciones"] if o != "NS/NC"]
        else:
            orden = ["bajo", "medio", "alto"] if isinstance(q["grupos"], str) else list(q["grupos"])
        cis = {_palabras(e) for e in self._etiquetas(q, orden)}
        return {_palabras(o) for o in opciones if _palabras(o) not in (NSNC, "")} == cis  # sin artículos ni signos

    def _etiquetas(self, q, opciones):
        """Nombres legibles para las escalas 0-10 / 1-10 (con los extremos reales del cuestionario)."""
        if q.get("etiquetas"):
            mapa = dict(zip(["bajo", "medio", "alto"], q["etiquetas"]))
            return [mapa.get(o, o) for o in opciones]
        if q.get("tipo") == "ampliado" and "Bajo (0-3)" in opciones and q["id"] in self.revision:
            cods = {int(k): v for k, v in self.revision[q["id"]]["opciones"].items()}
            limpio = lambda t: re.sub(r"^\d+\s*", "", t).strip().capitalize() or t
            lo, hi = limpio(cods[min(cods)]), limpio(cods[max(cods)])
            a, b = min(cods), max(cods)
            mapa = {"Bajo (0-3)": f"{lo} ({a}-3)", "Medio (4-6)": "Intermedio (4-6)", "Alto (7-10)": f"{hi} (7-{b})"}
            return [mapa.get(o, o) for o in opciones]
        return [ESCALA.get(o, o) for o in opciones]

    def _muestras_cis(self, q):
        """Entrevistas reales detrás de cada grupo (para avisar cuando un grupo tiene pocas)."""
        df = cargar_cis(q["estudio"])[0]
        df = df[df[q["variable"]].notna()]
        edad = pd.cut(pd.to_numeric(df["EDAD"] if "EDAD" in df else df["P20"], errors="coerce"),
                      [0, 29, 44, 59, 74, 200], labels=[e[0] for e in EDADES]).astype(str)
        return {"ccaa": df["ccaa"].map(CCAA_ID).value_counts().to_dict(),
                "sexo": df["sexo"].map({"Mujer": "F", "Hombre": "M"}).value_counts().to_dict(),
                "edad": edad.value_counts().to_dict()}

    def _simulacion(self, pregunta, opciones, informar, relevantes=()):
        arquetipos = elegir_arquetipos(N_ARQUETIPOS)
        resp = simular(pregunta, opciones, arquetipos, relevantes=relevantes,
                       progreso=lambda k, total: informar("respondiendo", k, total))
        # Cada persona hereda la respuesta de sus arquetipos más parecidos (demografía + actitudes relacionadas).
        return expandir(resp, arquetipos, self.pob, actitudes=list(relevantes)[:3]), len(arquetipos)

    def factores(self, probs, lider, etiqueta, excluir=()):
        """Qué mueve la respuesta: diferencia en la opción ganadora entre quienes están arriba y abajo
        en cada actitud CIS (tercil alto vs bajo) y entre grupos de ideología y edad."""
        p, w = probs.iloc[:, lider].to_numpy(), self.pob["peso"].to_numpy()
        media = lambda m: float((p[m] * w[m]).sum() / max(w[m].sum(), 1e-9)) * 100
        salida = []
        for q in self.banco:
            if q["id"] in excluir:
                continue
            a = self.pob[q["id"]].to_numpy()
            lo, hi = np.quantile(a, [1 / 3, 2 / 3])
            dif = media(a >= hi) - media(a <= lo)
            salida.append({"factor": q["frase"], "dif_pp": round(dif, 1),
                           "texto": f"Entre quienes tienen más {q['frase']}, «{etiqueta}» {'sube' if dif > 0 else 'baja'} {abs(dif):.0f} pp."})
        ideol = self.pob["ideologia"]
        dif = media(ideol.isin(["1-2", "3-4"]).to_numpy()) - media(ideol.isin(["7-8", "9-10"]).to_numpy())
        salida.append({"factor": "ideología", "dif_pp": round(dif, 1),
                       "texto": f"La izquierda elige «{etiqueta}» {abs(dif):.0f} pp {'más' if dif > 0 else 'menos'} que la derecha."})
        edad = self.pob["edad"].to_numpy()
        dif = media(edad < 35) - media(edad >= 65)
        salida.append({"factor": "edad", "dif_pp": round(dif, 1),
                       "texto": f"Los menores de 35 eligen «{etiqueta}» {abs(dif):.0f} pp {'más' if dif > 0 else 'menos'} que los mayores de 65."})
        salida.sort(key=lambda f: -abs(f["dif_pp"]))
        return [f for f in salida if abs(f["dif_pp"]) >= 3][:3]

    def error_simulacion(self, modo=None):
        """Error medido de la simulación: por color si existe (10_validar_ambar_rojo.py), si no el global."""
        color = {"analogia": "ámbar", "simulacion": "rojo"}.get(modo)
        try:
            r = pd.read_csv(CALIBRACION / "por_modo.csv", index_col="color")
            return round(float(r.loc[color, "error_total_pts"]), 1)
        except (OSError, KeyError, ValueError):
            pass
        try:
            r = pd.read_csv(CALIBRACION / "resumen.csv", index_col=0)
            return round(float(r.loc["actitudes_relevantes", "error_total_pts"]), 1)
        except (OSError, KeyError, ValueError):
            return None

    # ---------- entrada principal ----------
    def responder(self, pregunta, opciones=None, informar=lambda *a: None, tipo="pregunta", mensajes=None):
        """tipo: «pregunta» (texto libre), «campana» (un mensaje o iniciativa) o «ab» (dos mensajes)."""
        mensajes = [m.strip() for m in (mensajes or []) if m and m.strip()]
        clave = hashlib.sha1(json.dumps([pregunta.strip().lower(), opciones or [], tipo, mensajes]).encode()).hexdigest()[:16]
        ruta = CACHE / f"{clave}.json"
        guardada = ruta if ruta.exists() else self._en_cache(pregunta, opciones, tipo, mensajes)
        if guardada:
            resultado = json.loads(guardada.read_text(encoding="utf-8"))
            self._progreso_demo(resultado, informar)
            informar("respondiendo", 1, 1)
            return resultado

        informar("interpretando", 0, 1)
        if tipo in ("campana", "ab"):
            return self._campana(tipo, mensajes, opciones, informar, ruta)
        todas = self.buscar(pregunta, todas=True)
        candidatos = [c for c in todas[:3] if c[1] >= UMBRAL_CANDIDATA]
        relevantes = [c[0]["id"] for c in todas if c[1] >= UMBRAL_RELEVANTE and c[0].get("tipo") != "ampliado"][:4]
        relacion, (q, sim) = self.juzgar(pregunta, candidatos) if candidatos else ("ninguna", todas[0])
        # El juez de 8B es permisivo: solo acepto "misma" si además es la candidata más parecida y muy similar.
        if relacion == "misma" and (q["id"] != candidatos[0][0]["id"] or sim < UMBRAL_MISMA):
            relacion = "parecida"
        # algunas preguntas del banco dicen qué NO responden (p. ej. la intención de voto no dice quién ganará)
        if relacion == "misma" and q.get("no_misma") and re.search(q["no_misma"], _norm(pregunta)):
            relacion = "parecida"
        referencia = self._referencia(q, sim)

        # con opciones escritas por el usuario solo se usa el modelo del CIS si son las mismas que las del CIS
        if relacion == "misma" and (not opciones or self._opciones_cis(q, opciones)):
            modo, tema = "evidencia", TEMA_BANCO.get(q["tema"], q["tema"])
            informar("convocando", 0, 1)
            probs, etiquetas, confianza = self._evidencia(q, sim, informar)
            confianza["n_grupos"] = self._n_cis
            serie = self._serie(q, etiquetas, probs)
        else:
            modo = "analogia" if relacion != "ninguna" else "simulacion"
            tema, propuestas = self.proponer(pregunta)
            etiquetas = opciones or propuestas
            if tema == "Otro" and modo == "analogia":
                tema = TEMA_BANCO.get(q["tema"], q["tema"])
            informar("convocando", 0, 1)
            probs, n_arq = self._simulacion(pregunta, etiquetas, informar, relevantes)
            confianza = self._confianza_simulacion(modo, n_arq, q)
            serie = []
            if modo == "simulacion":
                referencia = None
        return self._guardar(ruta, pregunta, tema, modo, referencia, etiquetas, probs, confianza, serie, relevantes,
                             excluir={q["id"]} if modo == "evidencia" else (), texto_voces=pregunta)

    @staticmethod
    def _clave_flexible(pregunta, opciones, tipo, mensajes):
        """La misma consulta aunque cambien mayúsculas, acentos, signos, espacios o falte algún artículo
        (escrita a mano en directo). Las opciones se comparan por sus palabras con contenido."""
        ops = frozenset(o for o in (_palabras(x) for x in (opciones or [])) if o not in (NSNC, ""))
        return _limpio(pregunta), ops, tipo or "pregunta", tuple(_limpio(m) for m in (mensajes or []))

    def _en_cache(self, pregunta, opciones, tipo, mensajes):
        """Busca una consulta ya calculada con la misma pregunta y opciones, aunque no esté escrita igual."""
        if not hasattr(self, "_indice_cache"):
            self._indice_cache = {}
            for r in sorted(CACHE.glob("*.json"), key=lambda r: r.stat().st_mtime):
                d = json.loads(r.read_text(encoding="utf-8"))
                q, ops, t, m = self._clave_flexible(d["pregunta"], d.get("opciones"), d.get("tipo", "pregunta"), d.get("mensajes"))
                self._indice_cache[(q, ops, t, m)] = r
                self._indice_cache.setdefault((q, None, t, m), r)
        q, ops, t, m = self._clave_flexible(pregunta, opciones, tipo, mensajes)
        exacta = self._indice_cache.get((q, ops if opciones else None, t, m))
        if exacta or not opciones:
            return exacta
        # una errata pequeña en la pregunta (p. ej. «ampañara»), con las mismas opciones
        parecidas = [(difflib.SequenceMatcher(None, q, k[0]).ratio(), r) for k, r in self._indice_cache.items()
                     if k[1] == ops and k[2] == t and k[3] == m]
        mejor = max(parecidas, default=(0, None), key=lambda x: x[0])
        return mejor[1] if mejor[0] >= .92 else None

    def _progreso_demo(self, r, informar):
        """Modo demo: recorre las fases del motor durante el tiempo configurado en vez de responder al instante."""
        espera = ESPERA_DEMO["evidencia" if r.get("modo") == "evidencia" else "llm"]
        if espera <= 0:
            return
        informar("interpretando", 0, 1); time.sleep(espera * .12)
        informar("convocando", 0, 1); time.sleep(espera * .1)
        n = int((r.get("confianza") or {}).get("n") or 0) if r.get("modo") != "evidencia" else 0
        if n > 1:  # simulación: «k de n perfiles» como cuando responde el LLM
            for k in range(1, n + 1):
                informar("respondiendo", k, n); time.sleep(espera * .7 / n)
        else:
            informar("respondiendo", 0, 1); time.sleep(espera * .7)
        informar("confianza", 1, 1); time.sleep(espera * .08)

    def _referencia(self, q, sim):
        return {"id": q["id"], "texto": q["texto"], "estudio": q["estudio"],
                "fecha": q.get("fecha") or FECHAS.get(q["estudio"], ""), "similitud": round(sim, 3)}

    def _confianza_simulacion(self, modo, n_arq, q, extra=""):
        error = self.error_simulacion(modo)
        return {
            "nivel": 2 if modo == "analogia" else 1, "error_pp": error, "n": n_arq,
            "texto": (f"Simulación con {n_arq} perfiles sintéticos españoles que responden con un modelo de lenguaje local, "
                      "a partir de sus actitudes medidas en el CIS. " + extra
                      + (f"Pregunta real más parecida: «{q['texto']}» (CIS {q['estudio']})."
                         if modo == "analogia" else "No hay ninguna pregunta parecida en las encuestas cargadas: resultado orientativo.")
                      + (f" En preguntas reales tratadas como nuevas, el error medio es de ±{error} pp." if error else "")),
        }

    def _campana(self, tipo, mensajes, opciones, informar, ruta):
        """Campaña o iniciativa (un mensaje) o test A/B (dos mensajes): siempre se simula, anclado en actitudes CIS."""
        corto = lambda m: m if len(m) <= 38 else m[:36].rstrip() + "…"
        if tipo == "ab":
            a, b = (mensajes + ["", ""])[:2]
            titulo = f"Test A/B: «{a}» frente a «{b}»"
            texto_llm = f"Ves dos mensajes de una campaña. ¿Cuál te convence más? Mensaje A: «{a}». Mensaje B: «{b}»."
            para_llm = [f"El mensaje A («{a}»)", f"El mensaje B («{b}»)", "Ninguno de los dos"]
            etiquetas = [f"A · {corto(a)}", f"B · {corto(b)}", "Ninguno"]
            busqueda = f"{a}. {b}"
        else:
            m = mensajes[0]
            titulo = f"Campaña: «{m}»"
            texto_llm = f"Imagina que te encuentras esta campaña o iniciativa: «{m}». ¿Qué te parece?"
            etiquetas = opciones or ["Me convence", "Me es indiferente", "No me convence"]
            para_llm, busqueda = etiquetas, m
        todas = self.buscar(busqueda, todas=True)
        q, sim = todas[0]
        relevantes = [c[0]["id"] for c in todas if c[1] >= UMBRAL_RELEVANTE and c[0].get("tipo") != "ampliado"][:4]
        modo = "analogia" if sim >= 0.70 else "simulacion"
        tema, _ = self.proponer(busqueda)
        informar("convocando", 0, 1)
        probs, n_arq = self._simulacion(texto_llm, para_llm, informar, relevantes)
        probs.columns = etiquetas
        confianza = self._confianza_simulacion(modo, n_arq, q, "Las campañas nunca tienen datos directos: se estiman. ")
        return self._guardar(ruta, titulo, tema, modo, self._referencia(q, sim) if modo == "analogia" else None,
                             etiquetas, probs, confianza, [], relevantes, tipo=tipo, mensajes=mensajes, texto_voces=texto_llm)

    def _guardar(self, ruta, pregunta, tema, modo, referencia, etiquetas, probs, confianza, serie, relevantes,
                 excluir=(), tipo="pregunta", mensajes=None, texto_voces=None):
        informar_lider = probs.mul(self.pob["peso"], axis=0).sum()
        lider = int(np.argmax(informar_lider.to_numpy()))
        resultado = {
            "factores": self.factores(probs, lider, etiquetas[lider], excluir=excluir),
            "actitudes_usadas": [next(b["frase"] for b in self.banco if b["id"] == i) for i in relevantes] if modo != "evidencia" else [],
            "pregunta": pregunta, "tipo": tipo, "mensajes": mensajes or [], "tema": tema, "modo": modo, "referencia": referencia,
            "opciones": etiquetas, "agregados": self._agregados(probs), "personas": self._personas(probs),
            "confianza": confianza, "serie": serie, "voces": self.voces(texto_voces or pregunta, etiquetas),
            "anios_disponibles": [2025, 2026], "n_poblacion": int(len(self.pob)),
        }
        ruta.write_text(json.dumps(resultado, ensure_ascii=False), encoding="utf-8")
        return resultado

    # ---------- comparación: LLM sin datos vs pulso vs CIS real ----------
    def _real_cis(self, q, etiquetas):
        """Distribución real (ponderada) de la pregunta en los microdatos CIS: total y por grupo de edad."""
        df = cargar_cis(q["estudio"])[0]
        v = df[q["variable"]]
        if q.get("tipo") == "ampliado":
            cods = {int(k): l for k, l in self.revision[q["id"]]["opciones"].items()}
            if "Bajo (0-3)" in q["opciones"]:
                mapa = {k: ("Bajo (0-3)" if k <= 3 else "Medio (4-6)" if k <= 6 else "Alto (7-10)") for k in cods}
            else:
                mapa = cods
        elif isinstance(q["grupos"], str):
            mapa = {c: n for n, r in ESCALA_0_10.items() for c in r}
            mapa[0] = "bajo"
        else:
            mapa = {c: n for n, cs in q["grupos"].items() for c in cs}
        nombres = v.map(lambda x: mapa.get(int(x)) if pd.notna(x) else None)
        legibles = dict(zip(sorted(set(mapa.values()), key=list(mapa.values()).index), self._etiquetas(q, list(dict.fromkeys(mapa.values())))))
        df = df.assign(op=nombres.map(legibles)).dropna(subset=["op"])
        df = df[df["op"].isin(etiquetas)]
        edad = pd.cut(pd.to_numeric(df["EDAD"] if "EDAD" in df else df["P20"], errors="coerce"),
                      [0, 29, 44, 59, 74, 200], labels=[e[0] for e in EDADES]).astype(str)
        def reparto(g):
            t = g.groupby("op")["peso"].sum().reindex(etiquetas, fill_value=0)
            return (t / t.sum() * 100).round(1).tolist() if t.sum() else None
        return {"total": reparto(df), "edad": {e: reparto(df[edad == e]) for e in [x[0] for x in EDADES]}, "n": int(len(df))}

    def comparar(self, pregunta, informar=lambda *a: None):
        """Para una pregunta con evidencia CIS: qué diría un LLM solo con demografía, qué dice pulso y qué dijo la gente."""
        clave = hashlib.sha1(pregunta.strip().lower().encode()).hexdigest()[:16]
        ruta = CACHE_COMPARAR / f"{clave}.json"
        if ruta.exists():
            return json.loads(ruta.read_text(encoding="utf-8"))
        r = self.responder(pregunta)
        if r["modo"] != "evidencia":
            raise ValueError("La comparación con datos reales solo existe para preguntas que el CIS ya hizo (semáforo verde).")
        ref = r["referencia"]
        q = next(x for x in self.indice if x["id"] == ref.get("id") or (x["texto"] == ref["texto"] and x["estudio"] == ref["estudio"]))
        opciones = [o for o in r["opciones"] if o != "NS/NC"]
        real = self._real_cis(q, opciones)
        arquetipos = elegir_arquetipos(N_ARQUETIPOS)
        resp = simular(pregunta, opciones, arquetipos, con_actitudes=False, progreso=lambda k, t: informar("respondiendo", k, t))
        w = arquetipos["peso_arquetipo"]
        llm_total = (resp.mul(w, axis=0).sum() / w.sum() * 100).round(1)
        edad_arq = pd.cut(arquetipos["edad"], [0, 29, 44, 59, 74, 200], labels=[e[0] for e in EDADES]).astype(str)
        llm_edad = resp.mul(w, axis=0).groupby(edad_arq).sum()
        llm_edad = (llm_edad.div(llm_edad.sum(axis=1), axis=0) * 100).round(1)
        idx = [r["opciones"].index(o) for o in opciones]
        norm = lambda v: (np.array([v[i] for i in idx]) / max(sum(v[i] for i in idx), 1e-9) * 100).round(1).tolist()
        pulso_total = norm(r["agregados"]["total"])
        pulso_edad = {e: norm(v) for e, v in r["agregados"]["edad"].items()}
        err = lambda a, b: round(float(np.mean(np.abs(np.array(a) - np.array(b)))), 1)
        salida = {
            "pregunta": pregunta, "cis": ref, "opciones": opciones, "n_real": real["n"],
            "real": real["total"], "pulso": pulso_total, "llm_solo": llm_total[opciones].tolist(),
            "error_pulso": err(pulso_total, real["total"]), "error_llm_solo": err(llm_total[opciones].tolist(), real["total"]),
            "edad": {e: {"real": real["edad"].get(e), "pulso": pulso_edad.get(e), "llm_solo": llm_edad.loc[e, opciones].tolist() if e in llm_edad.index else None}
                     for e in [x[0] for x in EDADES]},
        }
        CACHE_COMPARAR.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(salida, ensure_ascii=False), encoding="utf-8")
        return salida

    def historial(self):
        consultas = []
        for ruta in sorted(CACHE.glob("*.json"), key=lambda r: r.stat().st_mtime, reverse=True):
            d = json.loads(ruta.read_text(encoding="utf-8"))
            lider = int(np.argmax(d["agregados"]["total"]))
            consultas.append({"pregunta": d["pregunta"], "tema": d["tema"], "modo": d["modo"],
                              "lider": d["opciones"][lider], "valor": d["agregados"]["total"][lider],
                              "opciones": d["opciones"]})
        return consultas
