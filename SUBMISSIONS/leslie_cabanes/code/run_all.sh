#!/bin/sh
# Produit les cinq livrables. Prerequis : voir README.md
set -e
cd "$(dirname "$0")"
. .venv/bin/activate
PYTHONPATH=formzones python formzones/map.py            # 1. cartographie des zones
for ex in form_01 form_02 form_03 form_04 form_05; do   # 2. les cinq exercices
  PYTHONPATH=formzones:kyc python kyc/pipeline.py "$ex"
done
