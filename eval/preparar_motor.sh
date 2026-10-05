#!/usr/bin/env bash
# Deja en .motor/ (ignorado por git) el motor de reglas real y los casos D08, sin mezclar historias de git:
#   .motor/engine/rules/{engine.ts,policy.ts,rules.json}   <- origin/feat/rules-engine (Flor)
#   .motor/casos_r09_r20.json                              <- origin/feat/hackathon-data-pipeline_v1 (Manuel)
# Requiere node y red para `npm i zod tsx`. Uso: bash eval/preparar_motor.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git fetch -q origin feat/rules-engine feat/hackathon-data-pipeline_v1
mkdir -p .motor/engine/rules
for f in engine.ts policy.ts rules.json; do git show "origin/feat/rules-engine:backend/src/rules/$f" > ".motor/engine/rules/$f"; done
git show "origin/feat/hackathon-data-pipeline_v1:data_pipeline/casos_prueba/casos_r09_r20.json" > .motor/casos_r09_r20.json
(cd .motor/engine && [ -f package.json ] || npm init -y >/dev/null; npm i --no-audit --no-fund zod@3 tsx >/dev/null)
echo "rules-engine @ $(git rev-parse --short origin/feat/rules-engine); casos D08 @ $(git rev-parse --short origin/feat/hackathon-data-pipeline_v1)" | tee .motor/VERSIONES
