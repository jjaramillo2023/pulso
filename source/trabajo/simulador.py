"""Simulador para preguntas nuevas: arquetipos de la población sintética responden con un LLM local.

Cada arquetipo es una persona sintética real (con su peso) cuya descripción incluye su
demografía y sus actitudes estimadas con respuestas reales del CIS (03_perfiles_actitudes.py).
"""
import json
import urllib.request
from functools import lru_cache

import numpy as np
import pandas as pd
from armonizar import RAIZ, cargar_poblacion

PERFILES = RAIZ / "resultados" / "perfiles"
MODELO_LLM = "llama3.1:8b"
N_ACTITUDES = 8
LETRAS = "ABCDEFGH"

SISTEMA = (
    "Simulas cómo respondería una persona concreta que vive en España a una encuesta. "
    "Ponte en su lugar: su edad, su situación y sus actitudes reales medidas en encuestas del CIS. "
    "No respondas lo que sería 'correcto', sino lo que esta persona probablemente contestaría. "
    "Responde solo con la letra de la opción."
)
URL_OLLAMA = "http://localhost:11434/api/chat"
TEMPERATURA = RAIZ / "resultados" / "calibracion_simulador" / "temperatura.json"


@lru_cache(maxsize=1)
def datos():
    pob = cargar_poblacion()
    actitudes = pd.read_parquet(PERFILES / "actitudes_poblacion.parquet")
    banco = {q["id"]: q for q in json.loads((PERFILES / "banco.json").read_text(encoding="utf-8"))}
    pob = pob.merge(actitudes, on="id")
    return pob, banco


def elegir_arquetipos(n=80, semilla=7, filtro=None):
    """Muestra estratificada (sexo × edad × estudios) ponderada por peso poblacional.

    Cada arquetipo representa la parte de la población de su estrato: su peso final es
    peso_estrato / arquetipos_en_estrato.
    """
    pob, _ = datos()
    base = pob if filtro is None else pob[filtro(pob)]
    base = base[base["peso"] > 0]
    estratos = base.groupby(["sexo", "grupo_edad", "estudios"])
    peso_estrato = estratos["peso"].sum()
    cupo = np.maximum(1, np.round(peso_estrato / peso_estrato.sum() * n)).astype(int)
    rng = np.random.default_rng(semilla)
    elegidos = []
    for clave, grupo in estratos:
        k = min(int(cupo.loc[clave]), len(grupo))
        idx = rng.choice(grupo.index, size=k, replace=False, p=grupo["peso"] / grupo["peso"].sum())
        sel = base.loc[idx].copy()
        sel["peso_arquetipo"] = peso_estrato.loc[clave] / k
        elegidos.append(sel)
    return pd.concat(elegidos)


def nivel(z):
    """Posición de la persona frente a la media española (en desviaciones típicas)."""
    if z >= 1.0:
        return "mucho más alta que la media española"
    if z >= 0.4:
        return "más alta que la media"
    if z > -0.4:
        return "en la media"
    if z > -1.0:
        return "más baja que la media"
    return "mucho más baja que la media española"


@lru_cache(maxsize=1)
def estadisticos():
    """Media y desviación de cada actitud en la población (para describir a cada persona frente a la media)."""
    pob, banco = datos()
    return {i: (float(pob[i].mean()), float(pob[i].std()) + 1e-9) for i in banco}


def describir(persona, excluir=(), con_actitudes=True, relevantes=()):
    _, banco = datos()
    ideol = persona["ideologia"]
    lineas = [f"{persona['sexo']}, {int(persona['edad'])} años, vive en {persona['ccaa']}, "
              f"nacionalidad {'española' if persona['nacionalidad'] == 'Espanola' else 'extranjera'}."]
    situacion = [f"Estudios: {persona['estudios']}." if persona["estudios"] != "NC" else "",
                 f"Situación laboral: {persona['sitlab']}." if persona["sitlab"] != "NC" else ""]
    if any(situacion):
        lineas.append(" ".join(s for s in situacion if s))
    if ideol != "no consta":
        lineas.append(f"Ideología (1 izquierda – 10 derecha): {ideol}. Religión: {persona['religion']}.")
    if con_actitudes:
        est = estadisticos()
        ids = [i for i in banco if i not in excluir]
        z = {i: (persona[i] - est[i][0]) / est[i][1] for i in ids}
        # Primero las actitudes relacionadas con la pregunta; después, las más distintivas de esta persona.
        top = [i for i in relevantes if i in z][:4]
        top += [i for i in sorted(ids, key=lambda i: -abs(z[i])) if i not in top][:N_ACTITUDES - len(top)]
        lineas.append("Sus actitudes, estimadas con encuestas reales del CIS a personas de su perfil:")
        for i in top:
            lineas.append(f"- {banco[i]['frase']}: {nivel(z[i])}")
    return "\n".join(lineas)


def preguntar(descripcion, pregunta, opciones):
    """Log-probabilidad que el LLM asigna a cada opción (una sola letra, leída de sus logprobs).

    Empiezo yo la respuesta del asistente ("Opción elegida:") para que no se niegue ni divague.
    """
    lista = "\n".join(f"{LETRAS[j]}) {o}" for j, o in enumerate(opciones))
    contenido = f"PERSONA:\n{descripcion}\n\nPREGUNTA: {pregunta}\nOPCIONES:\n{lista}\n\nResponde solo con la letra."
    cuerpo = {"model": MODELO_LLM, "stream": False, "logprobs": True, "top_logprobs": 20,
              "messages": [{"role": "system", "content": SISTEMA}, {"role": "user", "content": contenido},
                           {"role": "assistant", "content": "Opción elegida:"}],
              "options": {"temperature": 0, "num_predict": 1, "num_ctx": 2048}}
    peticion = urllib.request.Request(URL_OLLAMA, data=json.dumps(cuerpo).encode(),
                                      headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(peticion, timeout=120) as r:
        top = json.load(r)["logprobs"][0]["top_logprobs"]
    masa = np.zeros(len(opciones))
    for t in top:
        letra = t["token"].strip()
        if len(letra) == 1 and letra in LETRAS[:len(opciones)]:
            masa[LETRAS.index(letra)] += np.exp(t["logprob"])
    masa = np.maximum(masa, 1e-4)  # opción no vista entre los 20 tokens más probables
    return np.log(masa / masa.sum())


def temperatura():
    """Factor que suaviza la seguridad excesiva del LLM (ajustado en la calibración)."""
    try:
        return float(json.loads(TEMPERATURA.read_text())["temperatura"])
    except (OSError, ValueError, KeyError):
        return 1.0


def a_probabilidades(logp, t=1.0):
    z = np.asarray(logp) / t
    z = np.exp(z - z.max(axis=-1, keepdims=True))
    return z / z.sum(axis=-1, keepdims=True)


def simular_logp(pregunta, opciones, arquetipos, excluir=(), con_actitudes=True, progreso=None, relevantes=()):
    """Log-probabilidades en bruto (una fila por arquetipo)."""
    filas = []
    for k, (_, persona) in enumerate(arquetipos.iterrows()):
        filas.append(preguntar(describir(persona, excluir, con_actitudes, relevantes), pregunta, opciones))
        if progreso:
            progreso(k + 1, len(arquetipos))
    return pd.DataFrame(filas, columns=opciones, index=arquetipos.index)


def simular(pregunta, opciones, arquetipos, excluir=(), con_actitudes=True, progreso=None, t=None, relevantes=()):
    """Probabilidad de cada opción por arquetipo, con la temperatura calibrada."""
    logp = simular_logp(pregunta, opciones, arquetipos, excluir, con_actitudes, progreso, relevantes)
    return pd.DataFrame(a_probabilidades(logp.to_numpy(), t or temperatura()),
                        columns=opciones, index=arquetipos.index)


IDEOLOGIA_NUM = {"1-2": 1.5, "3-4": 3.5, "5-6": 5.5, "7-8": 7.5, "9-10": 9.5}
ESTUDIOS_NUM = {"Básicos": 0, "Secundaria/FP": 1, "Universitarios": 2}


def rasgos(df, actitudes=()):
    """Vector numérico de cada persona para buscar a sus arquetipos más parecidos."""
    est = estadisticos()
    cols = [df["edad"].to_numpy() / 15, (df["sexo"] == "Mujer").to_numpy() * 1.0,
            df["estudios"].map(ESTUDIOS_NUM).fillna(1).to_numpy(),
            df["ideologia"].map(IDEOLOGIA_NUM).fillna(5.5).to_numpy() / 3]
    cols += [((df[a] - est[a][0]) / est[a][1]).to_numpy() for a in actitudes]
    return np.column_stack(cols)


def expandir(respuestas, arquetipos, pob, actitudes=(), k=8):
    """Cada persona de la población hereda la media ponderada de sus k arquetipos más parecidos
    (demografía + actitudes relacionadas con la pregunta)."""
    A, X = rasgos(arquetipos, actitudes), rasgos(pob, actitudes)
    dist = np.sqrt(((X[:, None, :] - A[None, :, :]) ** 2).sum(axis=2))
    vecinos = np.argsort(dist, axis=1)[:, :k]
    w = 1 / (np.take_along_axis(dist, vecinos, axis=1) + .3)
    R = respuestas.to_numpy()
    probs = (R[vecinos] * w[:, :, None]).sum(axis=1) / w.sum(axis=1, keepdims=True)
    return pd.DataFrame(probs, columns=respuestas.columns, index=pob.index)


def agregar(respuestas, arquetipos, grupo=None):
    p = respuestas.mul(arquetipos["peso_arquetipo"], axis=0)
    tabla = p.groupby(arquetipos[grupo]).sum() if grupo else p.sum().to_frame("Total").T
    return tabla.div(tabla.sum(axis=1), axis=0) * 100
