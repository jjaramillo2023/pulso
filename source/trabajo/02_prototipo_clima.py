"""Prototipo: predecir la preocupación por el cambio climático en la población sintética.

1. Entrena con respuestas reales del CIS 3536 (dic 2025, P1).
2. Aplica el modelo a las 25.000 personas sintéticas (con sus pesos).
3. Valida contra el CIS 3577 (sep 2026, P13: misma pregunta y escala), que el modelo no ha visto:
   A) predicción directa (incluye el cambio real de opinión entre olas);
   B) re-anclada: solo conocemos el total nacional de sep 2026 y el modelo reparte por grupos.

Uso: cd trabajo && ../.venv/bin/python 02_prototipo_clima.py
"""
import numpy as np
import pandas as pd

from armonizar import RAIZ, cargar_cis, cargar_poblacion
from modelo import crear_codificador, entrenar, predecir_poblacion

SALIDA = RAIZ / "resultados" / "prototipo_clima"
CATEGORIAS = {1: "Mucho", 2: "Bastante", 3: "Regular", 4: "Poco", 5: "Nada", 8: "NS/NC", 9: "NS/NC"}
ORDEN = ["Mucho", "Bastante", "Regular", "Poco", "Nada", "NS/NC"]
DESGLOSES = [None, "sexo", "grupo_edad", "ccaa"]
N_BOOT = 50
SEMILLA = 20261019


def preparar(estudio, variable):
    df, _ = cargar_cis(estudio)
    df["respuesta"] = df[variable].map(CATEGORIAS)
    return df.dropna(subset=["respuesta", "ccaa"])


def agregar(pesos, probs, grupos=None):
    """Porcentaje ponderado por categoría, total o por grupo."""
    p = probs.mul(pesos, axis=0)
    tabla = p.groupby(grupos).sum() if grupos is not None else p.sum().to_frame("Total").T
    tabla = tabla.reindex(columns=ORDEN, fill_value=0)
    return tabla.div(tabla.sum(axis=1), axis=0) * 100


def real(df, grupo=None):
    indicadoras = pd.get_dummies(df["respuesta"]).astype(float)
    tabla = agregar(df["peso"], indicadoras, df[grupo] if grupo else None)
    n = df.groupby(grupo).size() if grupo else pd.Series({"Total": len(df)})
    return tabla, n


def reanclar(probs, pesos, total_real):
    """Ajusta el nivel nacional a un total conocido manteniendo las diferencias entre grupos."""
    ajustado = probs[ORDEN].copy()
    for _ in range(50):  # ajuste iterativo hasta cuadrar el total nacional
        pred_total = agregar(pesos, ajustado).iloc[0]
        factor = (total_real / pred_total.replace(0, np.nan)).fillna(1)
        ajustado = ajustado * factor[ORDEN]
        ajustado = ajustado.div(ajustado.sum(axis=1), axis=0)
    return ajustado


def mucho_bastante(tabla):
    return tabla["Mucho"] + tabla["Bastante"]


def comparar(pob, probs, prueba, grupo):
    pred = mucho_bastante(agregar(pob["peso"], probs, pob[grupo] if grupo else None))
    obs, n = real(prueba, grupo)
    obs = mucho_bastante(obs)
    comunes = pred.index.intersection(obs.index)
    ruido = 1.96 * np.sqrt(obs / 100 * (1 - obs / 100) / n) * 100
    return pd.DataFrame({
        "n_real": n.loc[comunes], "pred_%": pred.loc[comunes].round(1),
        "real_%": obs.loc[comunes].round(1),
        "error_pts": (pred.loc[comunes] - obs.loc[comunes]).round(1),
        "margen_encuesta_±": ruido.loc[comunes].round(1),
    })


def resumir(tabla):
    err = tabla["error_pts"].abs()
    return round(err.mean(), 1), round((err <= tabla["margen_encuesta_±"]).mean() * 100)


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    entreno = preparar(3536, "P1")
    prueba = preparar(3577, "P13")
    pob = cargar_poblacion()

    cod = crear_codificador(entreno, pob)
    modelo = entrenar(entreno, cod)
    probs = predecir_poblacion(modelo, cod, pob, entreno).reindex(columns=ORDEN, fill_value=0)

    total_sep, _ = real(prueba)
    probs_ancladas = reanclar(probs, pob["peso"], total_sep.iloc[0])

    individual = pd.concat([pob[["id", "sexo", "edad", "ccaa", "nacionalidad"]],
                            probs.round(4).add_prefix("p_")], axis=1)
    individual.to_csv(SALIDA / "respuestas_individuales.csv", index=False)

    rng = np.random.default_rng(SEMILLA)
    boot = []
    for _ in range(N_BOOT):
        muestra = entreno.sample(len(entreno), replace=True, random_state=int(rng.integers(1e9)))
        m = entrenar(muestra, cod)
        pb = predecir_poblacion(m, cod, pob, muestra).reindex(columns=ORDEN, fill_value=0)
        boot.append(mucho_bastante(agregar(pob["peso"], pb)).iloc[0])
    lo, hi = np.percentile(boot, [2.5, 97.5])

    print("=" * 72)
    print("PREOCUPACIÓN POR EL CAMBIO CLIMÁTICO · % 'mucho + bastante'")
    print("Entrenado con CIS 3536 (dic 2025) · validado con CIS 3577 (sep 2026, no visto)")
    print("=" * 72)

    dic, _ = real(entreno)
    print(f"\nCalibración (misma ola): población sintética {mucho_bastante(agregar(pob['peso'], probs)).iloc[0]:.1f}% "
          f"vs CIS dic 2025 real {mucho_bastante(dic).iloc[0]:.1f}%  · IC95% bootstrap {lo:.1f}–{hi:.1f}%")

    resumen = []
    for nombre, pr in [("A_directa", probs), ("B_reanclada", probs_ancladas)]:
        print(f"\n######## Validación {nombre}")
        for grupo in DESGLOSES:
            tabla = comparar(pob, pr, prueba, grupo)
            mae, dentro = resumir(tabla)
            etiqueta = grupo or "total"
            tabla.to_csv(SALIDA / f"validacion_{nombre}_{etiqueta}.csv")
            if grupo != "ccaa":
                print(f"\n--- {etiqueta}\n{tabla.to_string()}")
            print(f"{etiqueta}: error medio {mae} pts · {dentro}% de grupos dentro del margen de la encuesta")
            # Referencia sin modelo: asignar a cada grupo el total nacional real.
            sin_modelo = (tabla["real_%"] - mucho_bastante(total_sep).iloc[0]).abs().mean()
            resumen.append({"validacion": nombre, "desglose": etiqueta, "grupos": len(tabla),
                            "error_medio_pts": mae, "error_sin_modelo_pts": round(sin_modelo, 1),
                            "pct_dentro_margen": dentro})

    pd.DataFrame(resumen).to_csv(SALIDA / "resumen_validacion.csv", index=False)
    print("\n=== RESUMEN\n" + pd.DataFrame(resumen).to_string(index=False))
    print(f"\nGuardado en {SALIDA}")


if __name__ == "__main__":
    main()
