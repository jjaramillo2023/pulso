"""¿Cuánto acierta el simulador con preguntas que no conoce?

Cada pregunta real del banco CIS se trata como si fuera nueva (su propia actitud se excluye
del perfil) y se compara la simulación con lo que respondió la gente de verdad.
Dos condiciones: solo demografía vs demografía + actitudes CIS.

Fase 1 (lenta, se puede reanudar): guarda las log-probabilidades del LLM por arquetipo.
Fase 2 (rápida): elige la temperatura que suaviza al LLM con validación cruzada
(para cada pregunta, la temperatura se ajusta solo con las demás) y calcula errores.

Uso: cd trabajo && ../.venv/bin/python 04_calibrar_simulador.py
"""
import json
import time

import numpy as np
import pandas as pd

import importlib

from armonizar import RAIZ
from banco_preguntas import PREGUNTAS
from simulador import a_probabilidades, agregar, elegir_arquetipos, simular_logp

perfiles = importlib.import_module("03_perfiles_actitudes")
SALIDA = RAIZ / "resultados" / "calibracion_simulador"
CRUDO = SALIDA / "logprobs"
NSNC = "NS/NC"
N_ARQUETIPOS = 100
# Preguntas con respuesta casi unánime: no sirven para medir si el simulador distingue.
EXCLUIDAS = {"incendios_preocupacion"}
CONDICIONES = {"solo_demografia": False, "demografia_y_actitudes": True, "actitudes_relevantes": True}
PERFILES = RAIZ / "resultados" / "perfiles"


def relevantes_para(q):
    """Actitudes CIS más parecidas a la pregunta (sin ella misma), como hace el motor con una pregunta nueva."""
    ids = [b["id"] for b in json.loads((PERFILES / "banco.json").read_text(encoding="utf-8"))]
    emb = np.load(PERFILES / "embeddings_banco.npz")["emb"]
    sims = emb @ emb[ids.index(q["id"])]
    orden = [ids[i] for i in np.argsort(-sims) if ids[i] != q["id"] and sims[i] >= 0.5]
    return orden[:4]
TEMPERATURAS = [0.3, 0.5, 0.7, 1, 1.5, 2, 3, 5]
ETIQUETAS_ESCALA = {"bajo": "Bajo (0 a 3 en una escala de 0 a 10)",
                    "medio": "Medio (4 a 6 en una escala de 0 a 10)",
                    "alto": "Alto (7 a 10 en una escala de 0 a 10)"}


def orden_opciones(q):
    """Opciones en el orden natural del cuestionario (no alfabético)."""
    return ["bajo", "medio", "alto"] if isinstance(q["grupos"], str) else list(q["grupos"])


def etiqueta(q, opcion):
    return ETIQUETAS_ESCALA[opcion] if isinstance(q["grupos"], str) else opcion


def real_por_grupo(q, grupo=None):
    df = perfiles.encuesta(q["estudio"]).copy()
    df["respuesta"] = perfiles.agrupar(df[q["variable"]], q["grupos"])
    df = df[df["respuesta"] != NSNC]
    dummies = pd.get_dummies(df["respuesta"]).astype(float).mul(df["peso"], axis=0)
    tabla = dummies.groupby(df[grupo]).sum() if grupo else dummies.sum().to_frame("Total").T
    tabla = tabla.reindex(columns=orden_opciones(q), fill_value=0)
    return tabla.div(tabla.sum(axis=1), axis=0) * 100


def recoger(arquetipos):
    CRUDO.mkdir(parents=True, exist_ok=True)
    for q in PREGUNTAS:
        if q["id"] in EXCLUIDAS:
            continue
        opciones = orden_opciones(q)
        for nombre, con_act in CONDICIONES.items():
            ruta = CRUDO / f"{q['id']}__{nombre}.parquet"
            if ruta.exists():
                continue
            t0 = time.time()
            rel = relevantes_para(q) if nombre == "actitudes_relevantes" else ()
            logp = simular_logp(q["texto"], [etiqueta(q, o) for o in opciones], arquetipos,
                                excluir={q["id"]}, con_actitudes=con_act, relevantes=rel)
            logp.columns = opciones
            logp.to_parquet(ruta)
            print(f"{q['id']:26s} {nombre:24s} {time.time() - t0:5.0f}s", flush=True)


def evaluar(q, logp, arquetipos, t):
    real = real_por_grupo(q)
    probs = pd.DataFrame(a_probabilidades(logp.to_numpy(), t), columns=logp.columns, index=logp.index)
    polo = [p for p in q["polo"] if p in probs.columns]
    total = agregar(probs, arquetipos).iloc[0]
    real_edad = real_por_grupo(q, "grupo_edad")[polo].sum(axis=1)
    sim_edad = agregar(probs, arquetipos, "grupo_edad")[polo].sum(axis=1).reindex(real_edad.index)
    real_sexo = real_por_grupo(q, "sexo")[polo].sum(axis=1)
    sim_sexo = agregar(probs, arquetipos, "sexo")[polo].sum(axis=1).reindex(real_sexo.index)
    return {
        "simulado": total.round(1).to_dict(), "real": real.iloc[0].round(1).to_dict(),
        "error_total_pts": float((total - real.iloc[0]).abs().mean()),
        "error_polo_pts": float(total[polo].sum() - real.iloc[0][polo].sum()),
        "error_edad_pts": float((sim_edad - real_edad).abs().mean()),
        "correlacion_edad": float(np.corrcoef(sim_edad, real_edad)[0, 1]) if sim_edad.std() > 0 else 0.0,
        "error_sexo_pts": float((sim_sexo - real_sexo).abs().mean()),
        "polo_edad_sim": sim_edad.round(1).to_dict(), "polo_edad_real": real_edad.round(1).to_dict(),
    }


def calibrar(arquetipos):
    preguntas = [q for q in PREGUNTAS if q["id"] not in EXCLUIDAS
                 and all((CRUDO / f"{q['id']}__{c}.parquet").exists() for c in CONDICIONES)]
    filas, detalle = [], {}
    for nombre in CONDICIONES:
        logps = {q["id"]: pd.read_parquet(CRUDO / f"{q['id']}__{nombre}.parquet") for q in preguntas}
        # Error de cada pregunta con cada temperatura.
        rejilla = {q["id"]: {t: evaluar(q, logps[q["id"]], arquetipos, t)["error_total_pts"] for t in TEMPERATURAS}
                   for q in preguntas}
        for q in preguntas:
            otras = [o["id"] for o in preguntas if o["id"] != q["id"]]
            t_cv = min(TEMPERATURAS, key=lambda t: np.mean([rejilla[o][t] for o in otras]))
            r = evaluar(q, logps[q["id"]], arquetipos, t_cv)
            uniforme = float((pd.Series(r["real"]) - 100 / len(r["real"])).abs().mean())
            filas.append({"condicion": nombre, "pregunta": q["id"], "tema": q["tema"], "temperatura": t_cv,
                          **{k: round(v, 2) for k, v in r.items() if isinstance(v, float)},
                          "error_uniforme_pts": round(uniforme, 2)})
            detalle.setdefault(q["id"], {})[nombre] = r
        global_t = min(TEMPERATURAS, key=lambda t: np.mean([rejilla[q["id"]][t] for q in preguntas]))
        if nombre == "actitudes_relevantes":
            (SALIDA / "temperatura.json").write_text(json.dumps({"temperatura": global_t}))
    tabla = pd.DataFrame(filas)
    tabla.to_csv(SALIDA / "calibracion_por_pregunta.csv", index=False)
    (SALIDA / "detalle.json").write_text(json.dumps(detalle, ensure_ascii=False, indent=1), encoding="utf-8")
    resumen = tabla.groupby("condicion")[["error_total_pts", "error_uniforme_pts", "error_edad_pts",
                                         "correlacion_edad", "error_sexo_pts"]].mean().round(2)
    resumen.to_csv(SALIDA / "resumen.csv")
    print("\n=== Error medio por condición (preguntas tratadas como nuevas)")
    print(resumen.to_string())
    print("\n=== Por pregunta (actitudes relevantes, la configuración del motor)")
    print(tabla[tabla.condicion == "actitudes_relevantes"][["pregunta", "temperatura", "error_total_pts",
          "error_uniforme_pts", "correlacion_edad", "error_edad_pts"]].to_string(index=False))


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    arquetipos = elegir_arquetipos(N_ARQUETIPOS)
    print(f"{len(arquetipos)} arquetipos", flush=True)
    recoger(arquetipos)
    calibrar(arquetipos)


if __name__ == "__main__":
    main()
