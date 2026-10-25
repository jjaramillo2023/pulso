"""Inventario de los microdatos CIS: tamaño, variables demográficas y preguntas por tema.

Uso: .venv/bin/python trabajo/01_inventario_cis.py
Salida: resultados/inventario_preguntas.csv y resumen por pantalla.
"""
import csv
import re
import unicodedata
from pathlib import Path

import pyreadstat

RAIZ = Path(__file__).resolve().parent.parent
MICRO = RAIZ / "datos_cis" / "microdatos"
SALIDA = RAIZ / "resultados" / "inventario_preguntas.csv"

# Variables que necesitamos para enlazar con la población sintética.
DEMOGRAFIA = {
    "ccaa": r"^CCAA$",
    "sexo": r"^SEXO$",
    "edad": r"^EDAD$",
    "estudios": r"^(ESTUDIOS|NIVELESTENTREV|ESTUDIOS_)",
    "ideologia": r"^(ESCIDEOL|ESCALA_IDEOL|IDEOL)",
    "religion": r"^(RELIGION|RELIGIOSIDAD)",
    "situacion_laboral": r"^(SITLAB|SITCONVIVE|SITUACION_LAB)",
    "tamano_municipio": r"^TAMUNI",
    "peso": r"^PESO",
}

TEMAS = {
    "vivienda": r"vivienda|alquiler|hipoteca|pisos? tur",
    "soledad": r"soledad|solo/a|aislad|aislamiento|acompa",
    "tecnologia_ia": r"inteligencia artificial|\bia\b|tecnolog|internet|digital|redes sociales|robot|algoritm",
    "medio_ambiente": r"medio ?ambiente|clim|contamina|energ|ecolog|incendio|sequ",
    "salud": r"salud|sanidad|sanitari|m[eé]dic|hospital|psicol|ansiedad|depresi",
    "consumo": r"consum|compra|precio|ahorr|gasto|banc|inflaci|ingresos|econ[oó]mic",
}


def sin_tildes(texto):
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def main():
    filas = []
    for carpeta in sorted(MICRO.iterdir()):
        sav = next(carpeta.glob("*.sav"), None)
        if not sav:
            continue
        _, meta = pyreadstat.read_sav(str(sav), metadataonly=True)
        etiquetas = dict(zip(meta.column_names, meta.column_labels))
        print(f"\n=== Estudio {carpeta.name}: {meta.number_rows} entrevistas, {len(etiquetas)} variables")

        encontradas = {}
        for nombre, patron in DEMOGRAFIA.items():
            vars_ok = [v for v in etiquetas if re.search(patron, v, re.I)]
            encontradas[nombre] = vars_ok[:3]
        print("  Demografía:", {k: v for k, v in encontradas.items()})

        for var, etiqueta in etiquetas.items():
            texto = sin_tildes(etiqueta or "")
            temas = [t for t, p in TEMAS.items() if re.search(p, texto)]
            if temas:
                filas.append({
                    "estudio": carpeta.name,
                    "variable": var,
                    "temas": "|".join(temas),
                    "etiqueta": (etiqueta or "")[:250],
                    "n_opciones": len(meta.variable_value_labels.get(var, {})),
                })

    SALIDA.parent.mkdir(exist_ok=True)
    with SALIDA.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)

    print("\n=== Preguntas por estudio y tema")
    conteo = {}
    for fila in filas:
        for t in fila["temas"].split("|"):
            conteo.setdefault(t, {}).setdefault(fila["estudio"], 0)
            conteo[t][fila["estudio"]] += 1
    for t, por_estudio in conteo.items():
        print(f"  {t}: {por_estudio}")
    print(f"\nGuardado: {SALIDA}")


if __name__ == "__main__":
    main()
