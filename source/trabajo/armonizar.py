"""Armoniza las variables del CIS y de la población sintética a las mismas categorías.

Ambas fuentes acaban con las columnas de PREDICTORES, para que un modelo entrenado
con respuestas reales del CIS se pueda aplicar a cada persona sintética.
"""
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat

RAIZ = Path(__file__).resolve().parent.parent
MICRO = RAIZ / "datos_cis" / "microdatos"
# La población del equipo: dentro del repo está en data/; en la carpeta de trabajo local, en repo_equipo/data/.
POBLACION = next((r for r in (RAIZ.parent / "data" / "poblacion_sintetica_procesada.csv",
                              RAIZ / "repo_equipo" / "data" / "poblacion_sintetica_procesada.csv") if r.exists()),
                 RAIZ.parent / "data" / "poblacion_sintetica_procesada.csv")

PREDICTORES = ["sexo", "grupo_edad", "ccaa", "estudios", "sitlab", "ideologia", "religion"]

GRUPOS_EDAD = [(18, 24, "18-24"), (25, 34, "25-34"), (35, 44, "35-44"),
               (45, 54, "45-54"), (55, 64, "55-64"), (65, 74, "65-74"), (75, 120, "75+")]

CCAA_CANON = {
    "andalucia": "Andalucía", "aragon": "Aragón", "asturias": "Asturias", "balears": "Baleares",
    "baleares": "Baleares", "canarias": "Canarias", "cantabria": "Cantabria",
    "castilla-la mancha": "Castilla-La Mancha", "castilla y leon": "Castilla y León",
    "cataluna": "Cataluña", "valenciana": "C. Valenciana", "extremadura": "Extremadura",
    "galicia": "Galicia", "madrid": "Madrid", "murcia": "Murcia", "navarra": "Navarra",
    "pais vasco": "País Vasco", "rioja": "La Rioja", "ceuta": "Ceuta", "melilla": "Melilla",
}


def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower().strip()


def canon_ccaa(texto):
    t = _norm(texto)
    for clave, nombre in CCAA_CANON.items():
        if clave in t:
            return nombre
    return np.nan


def grupo_edad(edad):
    edad = pd.to_numeric(edad, errors="coerce")
    salida = pd.Series("NC", index=edad.index, dtype=object)
    for lo, hi, g in GRUPOS_EDAD:
        salida[(edad >= lo) & (edad <= hi)] = g
    return salida


def bin_ideologia(valor):
    v = pd.to_numeric(valor, errors="coerce")
    if pd.isna(v) or v < 1 or v > 10:
        return "no consta"
    return {1: "1-2", 2: "1-2", 3: "3-4", 4: "3-4", 5: "5-6", 6: "5-6",
            7: "7-8", 8: "7-8", 9: "9-10", 10: "9-10"}[int(v)]


def grupo_religion(texto):
    t = _norm(texto)
    if "no practicante" in t:
        return "católico no practicante"
    if "practicante" in t:
        return "católico practicante"
    if "otra religion" in t:
        return "otra religión"
    if "agnostic" in t or "indiferente" in t:
        return "agnóstico/indiferente"
    if "ateo" in t:
        return "ateo"
    return "no consta"


# ---------------- CIS ----------------

CIS_ESTUDIOS = {1: "Básicos", 2: "Básicos", 3: "Básicos", 4: "Secundaria/FP", 5: "Secundaria/FP",
                6: "Universitarios"}
CIS_SITLAB = {1: "Trabaja", 2: "Jubilado", 3: "Jubilado", 4: "En paro", 5: "En paro",
              6: "Estudiante", 7: "Hogar/otros", 8: "Hogar/otros"}


def cargar_cis(estudio):
    """Devuelve (DataFrame con predictores armonizados + todas las variables originales, metadatos)."""
    sav = MICRO / str(estudio) / f"{estudio}.sav"
    df, meta = pyreadstat.read_sav(str(sav))
    etiq_ccaa = meta.variable_value_labels.get("CCAA", {})
    etiq_rel = meta.variable_value_labels.get("RELIGION", {})
    # Algunos estudios (ICC) usan otros nombres o no preguntan religión/situación laboral.
    sexo = df["SEXO"] if "SEXO" in df else df["P19"]
    edad = df["EDAD"] if "EDAD" in df else df["P20"]
    out = pd.DataFrame(index=df.index)
    out["sexo"] = sexo.map({1: "Hombre", 2: "Mujer"})
    out["grupo_edad"] = grupo_edad(edad)
    out["ccaa"] = df["CCAA"].map(etiq_ccaa).map(canon_ccaa)
    out["estudios"] = df["ESTUDIOS"].map(CIS_ESTUDIOS).fillna("NC")
    out["sitlab"] = df["SITLAB"].map(CIS_SITLAB).fillna("NC") if "SITLAB" in df else "NC"
    out["ideologia"] = df["ESCIDEOL"].map(bin_ideologia)
    out["religion"] = df["RELIGION"].map(etiq_rel).map(grupo_religion) if "RELIGION" in df else "no consta"
    peso = next((c for c in ("PESO", "PESO_V2") if c in df.columns), None)
    out["peso"] = pd.to_numeric(df[peso], errors="coerce").fillna(1.0) if peso else 1.0
    return pd.concat([out, df], axis=1), meta


# ---------------- Población sintética ----------------

def estudios_ecv(texto):
    # Uso la columna original de la ECV: la columna 'estudios' procesada infra-representa
    # los estudios básicos (20% frente a ~40% en ECV y CIS).
    t = _norm(texto)
    if "segunda etapa" in t or "postsecundaria" in t or "16 a 34" in t:
        return "Secundaria/FP"
    if t.startswith("educacion superior"):
        return "Universitarios"
    if "primaria" in t or "primera etapa" in t:
        return "Básicos"
    return "NC"
POB_SITLAB = {"Trabaja": "Trabaja", "Jubilado/a": "Jubilado", "En paro": "En paro",
              "Estudiante": "Estudiante", "Trabajo domestico/otros": "Hogar/otros"}


def cargar_poblacion():
    p = pd.read_csv(POBLACION, low_memory=False)
    out = pd.DataFrame({"id": p["id"]})
    out["sexo"] = p["sexo"]
    out["edad"] = p["edad"]
    out["grupo_edad"] = grupo_edad(p["edad"])
    out["ccaa"] = p["ccaa"].map(canon_ccaa)
    out["estudios"] = p["estudios_ecv"].map(estudios_ecv)
    out["sitlab"] = p["situacion_laboral"].map(POB_SITLAB).fillna("NC")
    out["ideologia"] = p["ideologia_1_10_cis"].map(bin_ideologia)
    out["religion"] = p["religion_cis"].map(grupo_religion)
    out["nacionalidad"] = p["nacionalidad"]
    # dimensiones extra para desglosar resultados (no se usan como predictores)
    out["renta"] = p["quintil_renta_hogar_ecv"].map({"Q1": "Baja (Q1-Q2)", "Q2": "Baja (Q1-Q2)", "Q3": "Media (Q3)",
                                                     "Q4": "Alta (Q4-Q5)", "Q5": "Alta (Q4-Q5)"})
    out["vivienda"] = p["vivienda_ecv"].map(lambda v: "Propiedad" if "propiedad" in str(v).lower()
                                            else "Alquiler" if "alquiler" in str(v).lower() else ("Cesión u otra" if "cesion" in str(v).lower() else None))
    out["vive_solo"] = p["vive_solo"].map({"Si": "Vive solo/a", "No": "Vive acompañado/a"})
    out["usa_ia"] = p["usa_ia"].map({"Si": "Usa IA", "No": "No usa IA"})
    out["municipio"] = p["urbanizacion_ecv"].map({"Zona muy poblada": "Ciudad grande", "Zona media": "Ciudad media", "Zona poco poblada": "Rural"})
    out["peso"] = pd.to_numeric(p["peso_poblacional"], errors="coerce").fillna(0)
    return out
