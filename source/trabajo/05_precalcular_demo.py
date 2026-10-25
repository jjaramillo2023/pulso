"""Calcula y guarda en caché las preguntas de la demo (responden al instante y sin depender del LLM en directo).

Uso: cd trabajo && ../.venv/bin/python 05_precalcular_demo.py [--rehacer]
"""
import sys
import time

from motor import CACHE, Motor

DEMO = [
    # evidencia (verde): preguntas que el CIS ya hizo
    "¿Te preocupa el cambio climático?",
    "¿Usarías una IA en la consulta del médico?",
    "¿Comprarías una vivienda este año?",
    "¿Tienes miedo a quedarte solo?",
    "¿Estás satisfecho con la sanidad pública?",
    "¿Cómo ves la economía de España?",
    "¿Te da miedo una guerra mundial?",
    "¿Cómo ha ido la economía de tu hogar estos meses?",
    "¿Crees que el precio de la vivienda va a seguir subiendo?",
    "¿Te da miedo no poder pagar tu alquiler o hipoteca?",
    "¿Crees que dentro de diez años habrá más soledad?",
    "¿Te da miedo no tener a alguien a quien amar?",
    "¿Crees que la inteligencia artificial va a avanzar mucho en los próximos diez años?",
    "¿Crees que en diez años habrá más robots sustituyendo a trabajadores?",
    "¿Crees que habrá más teletrabajo en el futuro?",
    "¿Crees que habrá más desastres naturales en los próximos años?",
    "¿Te preocupan los incendios forestales?",
    "¿Hace falta un pacto de Estado contra el cambio climático?",
    "¿Cómo funciona el sistema sanitario español?",
    "¿Te da miedo contraer un cáncer?",
    "¿Crees que habrá otra pandemia como la COVID?",
    "¿Tienes un plan de pensiones?",
    "¿Cuánto sabes de temas bancarios y financieros?",
    "¿Cómo valoras tu situación económica personal?",
    # analogía (ámbar): parecidas a una pregunta del CIS
    "¿Te sientes solo a menudo?",
    "¿Confiarías en una IA para cuidar a un familiar mayor?",
    "¿Cambiarías tu coche por uno eléctrico?",
    "¿Usas el móvil para ir al banco?",
    # simulación (rojo): sin equivalente
    "¿Qué atrae más a los jóvenes: zapatos rojos o azules?",
    "¿Prohibirías los pisos turísticos en el centro de tu ciudad?",
    "¿Qué te haría cambiar de banco: cero comisiones, atención humana 24/7 o una app con IA?",
]
# campañas y test A/B: (texto que se muestra en el chat, tipo, mensajes)
CAMPANAS = [
    ("«Ahorra 200 € al año en tu factura» vs «Reduce tu huella de carbono»", "ab",
     ["Ahorra 200 € al año en tu factura", "Reduce tu huella de carbono"]),
    ("Campaña: Tu banco con atención humana 24 horas, sin comisiones", "campana",
     ["Tu banco con atención humana 24 horas, sin comisiones"]),
    ("Campaña: Bono de alquiler de 250 € al mes para menores de 35 años", "campana",
     ["Bono de alquiler de 250 € al mes para menores de 35 años"]),
    ("Campaña: Llama a tus mayores: la soledad no deseada también es cosa tuya", "campana",
     ["Llama a tus mayores: la soledad no deseada también es cosa tuya"]),
    ("Campaña: Ayudas de 3.000 € para instalar placas solares en casa", "campana",
     ["Ayudas de 3.000 € para instalar placas solares en casa"]),
    ("«Pásate al coche eléctrico y ahorra en gasolina» vs «Pásate al coche eléctrico y respira un aire más limpio»", "ab",
     ["Pásate al coche eléctrico y ahorra en gasolina", "Pásate al coche eléctrico y respira un aire más limpio"]),
]


def main():
    if "--rehacer" in sys.argv:
        for ruta in CACHE.glob("*.json"):
            ruta.unlink()
    m = Motor()
    for q in DEMO:
        t = time.time()
        r = m.responder(q)
        lider = max(range(len(r["opciones"])), key=lambda j: r["agregados"]["total"][j])
        print(f"{time.time() - t:5.0f}s  {r['modo']:10s} {r['agregados']['total'][lider]:5.1f}% «{r['opciones'][lider]}»  · {q}", flush=True)
    for texto, tipo, mensajes in CAMPANAS:
        t = time.time()
        r = m.responder(texto, informar=lambda *a: None, tipo=tipo, mensajes=mensajes)
        lider = max(range(len(r["opciones"])), key=lambda j: r["agregados"]["total"][j])
        print(f"{time.time() - t:5.0f}s  {tipo:10s} {r['agregados']['total'][lider]:5.1f}% «{r['opciones'][lider]}»  · {texto}", flush=True)
    for q in [d for d in DEMO if not d.startswith("¿Qué")]:  # comparación con un LLM sin datos (solo preguntas con evidencia)
        try:
            c = m.comparar(q)
            print(f"comparar  pulso ±{c['error_pulso']} · LLM sin datos ±{c['error_llm_solo']}  · {q}", flush=True)
        except ValueError:
            pass


if __name__ == "__main__":
    main()
