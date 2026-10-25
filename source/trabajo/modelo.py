"""Modelo de respuesta: entrena con microdatos CIS y predice para cada persona sintética."""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder

from armonizar import PREDICTORES

ESTRATO = ["sexo", "grupo_edad", "estudios"]
LATENTES = ["ideologia", "religion"]


def crear_codificador(*tablas):
    return OneHotEncoder(handle_unknown="ignore").fit(pd.concat([t[PREDICTORES] for t in tablas]))


def entrenar(df, codificador, objetivo="respuesta", C=0.5):
    modelo = LogisticRegression(C=C, max_iter=2000)
    modelo.fit(codificador.transform(df[PREDICTORES]), df[objetivo], sample_weight=df["peso"])
    return modelo


def predecir_poblacion(modelo, codificador, pob, encuesta):
    """Probabilidades por persona sintética (filas = pob.index, columnas = clases).

    Las personas extranjeras no tienen ideología ni religión (el CIS solo entrevista a
    españoles). Para ellas promedio la predicción sobre la distribución real de
    ideología × religión de los encuestados CIS de su mismo sexo, edad y estudios.
    """
    clases = list(modelo.classes_)
    probs = pd.DataFrame(modelo.predict_proba(codificador.transform(pob[PREDICTORES])),
                         index=pob.index, columns=clases)

    extranjeros = pob[pob["nacionalidad"] != "Espanola"]
    if extranjeros.empty:
        return probs

    pares = (encuesta.groupby(ESTRATO + LATENTES)["peso"].sum()
             .div(encuesta.groupby(ESTRATO)["peso"].sum()).rename("w").reset_index())
    expandido = (extranjeros.drop(columns=LATENTES).reset_index()
                 .merge(pares, on=ESTRATO, how="left"))
    # Estratos sin encuestados: uso la distribución nacional.
    sin_pares = expandido["w"].isna()
    if sin_pares.any():
        nacional = (encuesta.groupby(LATENTES)["peso"].sum() / encuesta["peso"].sum()).rename("w").reset_index()
        relleno = (expandido.loc[sin_pares].drop(columns=LATENTES + ["w"])
                   .merge(nacional, how="cross"))
        expandido = pd.concat([expandido.loc[~sin_pares], relleno], ignore_index=True)

    p = modelo.predict_proba(codificador.transform(expandido[PREDICTORES])) * expandido[["w"]].to_numpy()
    media = pd.DataFrame(p, columns=clases).groupby(expandido["index"].to_numpy()).sum()
    media = media.div(media.sum(axis=1), axis=0)
    probs.loc[media.index] = media.to_numpy()
    return probs
