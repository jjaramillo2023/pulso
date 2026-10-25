"""Servidor local de pulso: API del motor + frontend.

Uso: cd trabajo && ../.venv/bin/python -m uvicorn servidor:app --port 8765
Abre http://127.0.0.1:8765
"""
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from armonizar import RAIZ
from motor import Motor

FRONTEND = RAIZ / "frontend"
app = FastAPI(title="pulso")


@app.middleware("http")
async def sin_cache(request, call_next):
    """El navegador siempre pide la última versión de la web (evita ver un app.js antiguo)."""
    respuesta = await call_next(request)
    if not request.url.path.startswith("/api/"):
        respuesta.headers["Cache-Control"] = "no-cache, must-revalidate"
    return respuesta
_motor = None
_bloqueo = threading.Lock()  # el LLM local atiende una pregunta cada vez
TRABAJOS = {}


def motor():
    global _motor
    if _motor is None:
        _motor = Motor()
    return _motor


class Pregunta(BaseModel):
    pregunta: str = Field(min_length=4, max_length=400)
    opciones: list[str] | None = Field(default=None, max_length=6)
    tipo: str = Field(default="pregunta", pattern="^(pregunta|campana|ab)$")
    mensajes: list[str] | None = Field(default=None, max_length=2)


def _ejecutar(job, datos):
    def informar(fase, hechos, total):
        TRABAJOS[job].update(fase=fase, hechos=hechos, total=total)

    try:
        with _bloqueo:
            opciones = [o.strip() for o in (datos.opciones or []) if o.strip()] or None
            if getattr(datos, "comparar", False):
                resultado = motor().comparar(datos.pregunta.strip(), informar)
            else:
                resultado = motor().responder(datos.pregunta.strip(), opciones, informar, datos.tipo, datos.mensajes)
        TRABAJOS[job].update(fase="listo", resultado=resultado)
    except Exception as error:  # el frontend muestra el error y vuelve al mapa
        TRABAJOS[job].update(fase="error", error=str(error))


@app.on_event("startup")
def precargar():
    threading.Thread(target=motor, daemon=True).start()


@app.post("/api/preguntar")
def preguntar(datos: Pregunta):
    job = uuid.uuid4().hex[:12]
    TRABAJOS[job] = {"fase": "en_cola", "hechos": 0, "total": 1, "inicio": time.time()}
    threading.Thread(target=_ejecutar, args=(job, datos), daemon=True).start()
    return {"job": job}


class Comparacion(BaseModel):
    pregunta: str = Field(min_length=4, max_length=400)
    comparar: bool = True
    opciones: list[str] | None = None


@app.post("/api/comparar")
def comparar(datos: Comparacion):
    """Compara para una pregunta con evidencia: LLM sin datos vs pulso vs CIS real."""
    job = uuid.uuid4().hex[:12]
    TRABAJOS[job] = {"fase": "en_cola", "hechos": 0, "total": 1, "inicio": time.time()}
    threading.Thread(target=_ejecutar, args=(job, datos), daemon=True).start()
    return {"job": job}


@app.get("/api/progreso/{job}")
def progreso(job: str):
    if job not in TRABAJOS:
        raise HTTPException(404, "Consulta no encontrada")
    estado = dict(TRABAJOS[job])
    estado["segundos"] = round(time.time() - estado.pop("inicio"), 1)
    if estado["fase"] in ("listo", "error"):
        TRABAJOS.pop(job, None)
    return estado


@app.get("/api/historial")
def historial():
    return motor().historial()


@app.get("/api/validacion")
def validacion():
    """Resumen de todas las validaciones para el panel «¿Cómo lo sabemos?»."""
    import json
    import pandas as pd
    res = RAIZ / "resultados"
    banco = json.loads((res / "perfiles" / "banco.json").read_text(encoding="utf-8"))
    salida = {"evidencia": {"preguntas": len(banco),
                            "error_misma_ola_pp": round(sum(q["error_calibracion_pts"] for q in banco) / len(banco), 1),
                            "entrevistas": sum(q["n"] for q in {q["estudio"]: q for q in banco}.values())}}
    try:
        t = pd.read_csv(res / "prototipo_clima" / "resumen_validacion.csv")
        salida["temporal"] = t.to_dict(orient="records")
    except OSError:
        pass
    try:  # 11_validar_tiempo.py: todas las preguntas repetidas entre olas
        t = pd.read_csv(res / "validacion_temporal" / "resumen.csv")
        salida["temporal_banco"] = t.to_dict(orient="records")
    except OSError:
        pass
    try:
        c = pd.read_csv(res / "calibracion_simulador" / "calibracion_por_pregunta.csv").fillna(0)  # sin variación por edad → r = 0
        resumen = c.groupby("condicion")[["error_total_pts", "error_uniforme_pts", "correlacion_edad", "error_edad_pts"]].mean().round(2)
        salida["simulacion"] = {"resumen": resumen.reset_index().to_dict(orient="records"),
                                "preguntas": c[["condicion", "pregunta", "tema", "error_total_pts", "error_polo_pts", "correlacion_edad"]].to_dict(orient="records")}
        detalle = json.loads((res / "calibracion_simulador" / "detalle.json").read_text(encoding="utf-8"))
        textos = {q["id"]: q["texto"] for q in banco}
        polos = {q["id"]: q["polo"] for q in banco}
        puntos = []
        for qid, conds in detalle.items():
            for cond, r in conds.items():
                polo = [o for o in polos[qid] if o in r["real"]]
                puntos.append({"pregunta": textos.get(qid, qid), "condicion": cond,
                               "real": round(sum(r["real"][o] for o in polo), 1), "simulado": round(sum(r["simulado"][o] for o in polo), 1)})
        salida["simulacion"]["puntos"] = puntos
        modos = res / "calibracion_simulador" / "por_modo.csv"  # 10_validar_ambar_rojo.py
        if modos.exists():
            salida["simulacion"]["por_modo"] = pd.read_csv(modos).to_dict(orient="records")
    except (OSError, KeyError, ValueError):
        pass
    return salida


@app.get("/api/poblacion")
def poblacion(n: int = 1000, semilla: int = 2026):
    """Genera una población sintética del tamaño pedido y la devuelve como CSV descargable."""
    n = max(100, min(int(n), 200_000))
    return StreamingResponse(iter([poblacion_csv(n, semilla)]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="pulso_poblacion_{n}.csv"'})


def poblacion_csv(n, semilla=2026):
    """Remuestreo ponderado de las 25.000 personas base (con variación de edad), con sus actitudes CIS."""
    import io
    import numpy as np
    m = motor()
    pob = m.pob[m.pob["peso"] > 0]
    rng = np.random.default_rng(semilla)
    idx = rng.choice(pob.index, n, replace=True, p=pob["peso"] / pob["peso"].sum())
    out = pob.loc[idx].reset_index(drop=True)
    out["edad"] = np.clip(out["edad"] + rng.integers(-2, 3, n), 18, 100)
    out["id"] = [f"PULSO-{i + 1:07d}" for i in range(n)]  # cada copia es una persona nueva
    cols = ["id", "edad", "sexo", "ccaa", "nacionalidad", "estudios", "sitlab", "ideologia", "religion",
            "renta", "vivienda", "vive_solo", "usa_ia", "municipio"] + [q["id"] for q in m.banco]
    tabla = out[cols].rename(columns={q["id"]: f"actitud_{q['id']}" for q in m.banco})
    for c in tabla.columns:
        if c.startswith("actitud_"):
            tabla[c] = tabla[c].round(3)
    buf = io.StringIO()
    tabla.to_csv(buf, index=False)
    return buf.getvalue()


@app.get("/api/salud")
def salud():
    return {"listo": _motor is not None}


@app.get("/")
def inicio():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
