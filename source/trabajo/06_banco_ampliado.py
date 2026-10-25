"""Banco ampliado: todas las preguntas de opinión válidas de los microdatos CIS descargados.

Fase 1 (LLM, se puede reanudar): decide si cada variable es una pregunta de opinión y la reescribe
         como pregunta natural, con su tema.
Fase 2: entrena un modelo por pregunta con las respuestas reales y lo aplica a las 25.000 personas.

Salidas en resultados/banco_ampliado/: revision_llm.json, banco.json, probs/<id>.parquet
Uso: cd trabajo && ../.venv/bin/python 06_banco_ampliado.py
"""
import json
import re
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat

from armonizar import MICRO, RAIZ, cargar_cis, cargar_poblacion
from modelo import crear_codificador, entrenar, predecir_poblacion

SALIDA = RAIZ / "resultados" / "banco_ampliado"
REVISION = SALIDA / "revision_llm.json"
TITULOS = {"3528": "Barómetro de octubre 2025", "3535": "Encuesta sobre tendencias sociales (V)", "3536": "Barómetro de diciembre 2025",
           "3554": "Estudio sobre temores en la sociedad actual", "3560": "Estudio de inclusión financiera",
           "3575": "Índice de Confianza del Consumidor, julio 2026", "3569": "Índice de Confianza del Consumidor, junio 2026", "3577": "Barómetro de septiembre 2026",
           "8825": "Barómetro Sanitario 2025"}
FECHAS = {"3528": "oct 2025", "3535": "dic 2025", "3536": "dic 2025", "3554": "feb 2026", "3560": "may 2026",
          "3575": "jul 2026", "3569": "jun 2026", "3577": "sep 2026", "8825": "2025"}
TEMAS = ["Vivienda", "Soledad", "Tecnología e IA", "Medio ambiente", "Salud", "Consumo", "Sociedad"]
EXCL_VAR = (r"^(IA_|PESO|CCAA|PROV|MUN|TAMUNI|SEXO|EDAD|ESTUDIOS|NIVELEST|RELIG|ESCIDEOL|SITLAB|ESTADOCIVIL|ESTCIVIL|"
            r"CLASE|INGRES|ENTREV|CUES|ORDEN|P19$|P20$|CAPITAL|NACION|HAB|COMUNIDAD|DIA|MES|HORA|DURAC|TIPO|ESCU|OCUP|"
            r"SITCONVIVEN|CNO|CNAE|ESTUDIANTE|ASAL|RECUVOTO|INTENCION|VOTO|SIMPA|CERCAN|PARTIDO|ESCALA_IDEOL|P0|ADQUINAC|"
            r"PAISNAC|FIJO|OLEADA|MOVIL|CONO|VALORA|ESCALA_VAL|CONFIA)")
EXCL_TEXTO = r"gaza|franco|israel|hamas|netanyahu|trump|putin|psoe|\bpp\b|vox|sumar|podemos|feij|s[aá]nchez|abascal|ministr|partido|vot[oa]|elecci|l[ií]der|presidente del gobierno"
NO_RESP = r"N\.S\.|N\.C\.|No sabe|No contesta|N\.P\.|No procede"


_LIBROS = {}


def enunciado(estudio, variable):
    """Título del bloque de la pregunta en el libro de códigos del CIS (da contexto a las baterías)."""
    if estudio not in _LIBROS:
        from pypdf import PdfReader
        pdf = next((MICRO / estudio).glob("codigo*.pdf"), None)
        _LIBROS[estudio] = "\n".join(pg.extract_text() for pg in PdfReader(str(pdf)).pages) if pdf else ""
    m = re.search(rf"\b{re.escape(variable)}\b(?:,\s*[A-Z][A-Z0-9_]*)*,?\s*\(\d+(?:-\d+)?\)(?:\s*a\s*\(\d+(?:-\d+)?\))?\s*(.+?)(?=\n\*|\n\d+\.-|\nEstudio n|\nPregunta Variable)",
                  _LIBROS[estudio], re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def candidatos():
    for d in sorted(MICRO.iterdir()):
        df, meta = pyreadstat.read_sav(str(d / f"{d.name}.sav"))
        for v, lab in zip(meta.column_names, meta.column_labels):
            if not lab or re.match(EXCL_VAR, v, re.I) or len(lab) < 14:
                continue
            vl = meta.variable_value_labels.get(v, {})
            sust = {int(k): str(l).replace("(NO LEER)", "").strip() for k, l in vl.items() if k < 96 and not re.search(NO_RESP, str(l))}
            if not 2 <= len(sust) <= 11 or re.search(EXCL_TEXTO, lab + " " + " ".join(sust.values()), re.I):
                continue
            if df[v].isin(list(sust)).mean() < 0.6:  # pregunta filtrada a una parte de la muestra
                continue
            yield d.name, v, lab, sust


def llm(prompt):
    cuerpo = {"model": "llama3.1:8b", "stream": False, "format": "json", "messages": [{"role": "user", "content": prompt}],
              "options": {"temperature": 0, "num_predict": 160}}
    req = urllib.request.Request("http://localhost:11434/api/chat", data=json.dumps(cuerpo).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(json.load(r)["message"]["content"])


def revisar():
    revision = json.loads(REVISION.read_text(encoding="utf-8")) if REVISION.exists() else {}
    for estudio, v, lab, sust in candidatos():
        clave = f"{estudio}_{v}"
        if clave in revision:
            continue
        opciones = " / ".join(sust.values())
        bloque = enunciado(estudio, v)
        contexto = f"Enunciado del bloque: «{bloque}»\nÍtem: «{lab}»" if bloque and bloque[:40].lower() != lab[:40].lower() else f"Pregunta: «{lab}»"
        prompt = (f"Encuesta del CIS: «{TITULOS[estudio]}».\n{contexto}\nRespuestas posibles: {opciones}\n\n"
                  "1) ¿Es una pregunta de opinión, actitud, valoración, experiencia o comportamiento que se pueda preguntar a la población "
                  "(no un dato administrativo, ni una opción suelta de una lista, ni demografía)?\n"
                  "2) Si lo es, reescríbela como una pregunta de encuesta natural y completa en español neutro, de usted (máximo 25 palabras). "
                  "Usa SOLO la información del enunciado y del ítem: no añadas temas ni cambies el sentido.\n"
                  f"3) Tema: uno de {', '.join(TEMAS)}.\n"
                  'Devuelve solo JSON: {"valida": true, "pregunta": "¿...?", "tema": "..."}')
        try:
            d = llm(prompt)
        except (OSError, ValueError):
            continue
        revision[clave] = {"estudio": estudio, "variable": v, "etiqueta": lab, "bloque": bloque, "opciones": sust,
                           "valida": bool(d.get("valida")), "pregunta": str(d.get("pregunta", "")).strip(),
                           "tema": d.get("tema") if d.get("tema") in TEMAS else "Sociedad"}
        REVISION.write_text(json.dumps(revision, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{clave:22s} {'✓' if revision[clave]['valida'] else '✗'} {revision[clave]['pregunta'][:90]}", flush=True)
    return revision


def entrenar_banco(revision):
    (SALIDA / "probs").mkdir(parents=True, exist_ok=True)
    pob = cargar_poblacion()
    cache, banco = {}, []
    for clave, r in revision.items():
        if not r["valida"] or not r["pregunta"].startswith("¿"):
            continue
        # filtro final: política, datos del entrevistado o del entrevistador que el LLM dio por válidos
        if re.search(r"^(VALMINIS|ECIVIL|RELALAB|SINCERIDAD|INTERES|COMPRENSION|DISPOSICION)", r["variable"]) or \
                re.search(EXCL_TEXTO + r"|estado civil|situación profesional|entrevist", r["pregunta"] + " " + r["etiqueta"], re.I):
            continue
        if r["estudio"] not in cache:
            cache[r["estudio"]] = cargar_cis(r["estudio"])[0]
        df = cache[r["estudio"]].copy()
        cods = {int(k): l for k, l in r["opciones"].items()}
        es_escala = len(cods) >= 10 and all(str(k) in l or l.split()[0].isdigit() for k, l in cods.items() if l)
        if es_escala:  # escalas 0-10 / 1-10 en tres tramos
            mapa = {k: ("Bajo (0-3)" if k <= 3 else "Medio (4-6)" if k <= 6 else "Alto (7-10)") for k in cods}
            orden = ["Bajo (0-3)", "Medio (4-6)", "Alto (7-10)"]
        else:
            mapa, orden = cods, list(dict.fromkeys(cods.values()))
        df["respuesta"] = df[r["variable"]].map(lambda x: mapa.get(int(x), "NS/NC") if pd.notna(x) else "NS/NC")
        df = df.dropna(subset=["ccaa"])
        if df["respuesta"].nunique() < 2:
            continue
        cod = crear_codificador(df, pob)
        probs = predecir_poblacion(entrenar(df, cod), cod, pob, df)
        probs.astype("float32").to_parquet(SALIDA / "probs" / f"{clave}.parquet")
        dummies = pd.get_dummies(df["respuesta"]).astype(float)
        real = dummies.mul(df["peso"], axis=0).sum() / df["peso"].sum() * 100
        sint = probs.mul(pob["peso"], axis=0).sum() / pob["peso"].sum() * 100
        error = float((sint - real.reindex(sint.index, fill_value=0)).abs().mean())
        banco.append({"id": clave, "estudio": int(r["estudio"]), "variable": r["variable"], "texto": r["pregunta"],
                      "etiqueta": r["etiqueta"], "tema": r["tema"], "fecha": FECHAS[r["estudio"]], "n": int(len(df)),
                      "opciones": [o for o in orden if o in probs.columns] + (["NS/NC"] if "NS/NC" in probs.columns else []),
                      "error_calibracion_pts": round(error, 2)})
        print(f"{clave:22s} n={len(df):5d} error {error:4.1f} · {r['pregunta'][:70]}", flush=True)
    (SALIDA / "banco.json").write_text(json.dumps(banco, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(banco)} preguntas en el banco ampliado")


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    entrenar_banco(revisar())


if __name__ == "__main__":
    main()
