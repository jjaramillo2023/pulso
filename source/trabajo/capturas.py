"""Capturas de pantalla del frontend (inicio, carga y las 4 vistas) con Chromium sin interfaz.

Uso: con el servidor en marcha, cd trabajo && ../.venv/bin/python capturas.py "¿Pregunta?" [ancho alto]
"""
import sys
import time

from playwright.sync_api import sync_playwright

from armonizar import RAIZ

URL = "http://127.0.0.1:8765/"
SALIDA = RAIZ / "resultados" / "capturas"


def main():
    pregunta = sys.argv[1] if len(sys.argv) > 1 else "¿Te preocupa el cambio climático?"
    ancho, alto = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (1440, 900)
    sufijo = f"_{ancho}" if ancho != 1440 else ""
    SALIDA.mkdir(parents=True, exist_ok=True)
    errores = []
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pag = nav.new_page(viewport={"width": ancho, "height": alto}, device_scale_factor=2)
        pag.on("pageerror", lambda e: errores.append(str(e)))
        pag.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
        pag.goto(URL)
        pag.wait_for_timeout(3500)
        pag.screenshot(path=SALIDA / f"01_inicio{sufijo}.png")
        pag.fill("#q", pregunta)
        pag.keyboard.press("Enter")
        pag.wait_for_timeout(1500)
        pag.screenshot(path=SALIDA / f"02_carga_nube{sufijo}.png")
        # espera a que empiece la votación (el contador aparece)
        t0 = time.time()
        while pag.evaluate("getComputedStyle(document.querySelector('#count')).opacity") == "0" and time.time() - t0 < 600:
            pag.wait_for_timeout(300)
        pag.wait_for_timeout(1700)
        pag.screenshot(path=SALIDA / f"03_carga_votando{sufijo}.png")
        pag.wait_for_function("!document.querySelector('#send').disabled", timeout=600000)
        pag.wait_for_timeout(1500)
        for i, (vista, nombre) in enumerate([("hemi", "total"), ("map", "comunidades"), ("sex", "sexo"), ("age", "edad")]):
            pag.click(f'#views [data-v="{vista}"]')
            pag.wait_for_timeout(2200)
            pag.screenshot(path=SALIDA / f"0{4 + i}_vista_{nombre}{sufijo}.png")
        # ficha de una persona al pasar el cursor por un punto
        caja = pag.locator("#cw").bounding_box()
        for dx in range(0, 200, 6):
            pag.mouse.move(caja["x"] + caja["width"] / 2 + dx - 100, caja["y"] + caja["height"] * .55)
            pag.wait_for_timeout(40)
            if pag.evaluate("document.querySelector('#tip').classList.contains('on')"):
                break
        pag.wait_for_timeout(300)
        pag.screenshot(path=SALIDA / f"08_ficha_persona{sufijo}.png")
        nav.close()
    print("errores JS:", errores or "ninguno")
    print("capturas en", SALIDA)


if __name__ == "__main__":
    main()
