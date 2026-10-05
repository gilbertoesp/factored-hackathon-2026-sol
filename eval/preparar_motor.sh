#!/usr/bin/env bash
# Deja en .motor/ (ignorado por git) el motor de reglas real y los casos D08, sin mezclar historias de git:
#   .motor/engine/rules/{engine.ts,policy.ts,rules.json}   <- origin/feat/rules-engine (Flor)
#   .motor/casos_r09_r20.json                              <- origin/feat/hackathon-data-pipeline_v1 (Manuel)
#   .motor/ml/{intents,baseline_keywords}.py, .motor/ml/banking77_prueba.jsonl  <- ídem (clasificador por palabras clave y su set)
# Requiere node y red para `npm i zod tsx`. Uso: bash eval/preparar_motor.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git fetch -q origin feat/rules-engine feat/hackathon-data-pipeline_v1
mkdir -p .motor/engine/rules
for f in engine.ts policy.ts rules.json; do git show "origin/feat/rules-engine:backend/src/rules/$f" > ".motor/engine/rules/$f"; done
git show "origin/feat/hackathon-data-pipeline_v1:data_pipeline/casos_prueba/casos_r09_r20.json" > .motor/casos_r09_r20.json
mkdir -p .motor/ml
for f in intents.py baseline_keywords.py; do git show "origin/feat/hackathon-data-pipeline_v1:ml/$f" > ".motor/ml/$f"; done
git show "origin/feat/hackathon-data-pipeline_v1:ml/sets/banking77_prueba.jsonl" > .motor/ml/banking77_prueba.jsonl
(cd .motor/engine && [ -f package.json ] || npm init -y >/dev/null; npm i --no-audit --no-fund zod@3 tsx >/dev/null)
echo "rules-engine @ $(git rev-parse --short origin/feat/rules-engine); casos D08 @ $(git rev-parse --short origin/feat/hackathon-data-pipeline_v1)" | tee .motor/VERSIONES
