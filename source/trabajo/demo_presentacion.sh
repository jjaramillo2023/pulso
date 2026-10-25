#!/bin/zsh
# Arranca pulso en modo demo para grabar o presentar: las preguntas ya calculadas tardan como si el
# motor las calculara en directo (verde ~25 s, LLM ~2 min) y muestran el progreso real por fases.
# Uso: ./demo_presentacion.sh   ·   abrir http://127.0.0.1:8765
# Para cambiar los tiempos: PULSO_ESPERA_VERDE=15 PULSO_ESPERA_LLM=90 ./demo_presentacion.sh
cd "$(dirname "$0")"
pkill -f "uvicorn servidor:app" 2>/dev/null
export PULSO_ESPERA_VERDE=${PULSO_ESPERA_VERDE:-25} PULSO_ESPERA_LLM=${PULSO_ESPERA_LLM:-120}
echo "pulso en modo demo · verde ${PULSO_ESPERA_VERDE} s · LLM ${PULSO_ESPERA_LLM} s · http://127.0.0.1:8765"
../.venv/bin/python -m uvicorn servidor:app --port 8765
