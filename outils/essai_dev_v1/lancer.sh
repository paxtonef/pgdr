#!/usr/bin/env bash
# ESSAI DE DÉVELOPPEMENT LOCAL du parcours V1 — jamais en production.
# Lit la notice depuis son manifeste SOURCE, hors du dépôt (rien n'est copié dans le dépôt).
# Le bandeau « Essai de développement — Applicabilité de cette notice au véhicule non confirmée »
# est affiché en permanence. L'identité VIR est SIMULÉE (PGDR_V1_DEV_VEHICLE) : pas de VIR réel ici.
# Usage : PGDR_V1_DEV_VEHICLE='{"manufacturer": "…", "model": "…", "generation": "…"}' \
#           outils/essai_dev_v1/lancer.sh /chemin/hors/depot/manifest.yaml [port]
# Facultatif (hors dépôt) : PGDR_V1_EXPLANATIONS (brouillon affiché en essai, marqué),
# PGDR_V1_GROUPS et PGDR_V1_FINDINGS (utilisés seulement s'ils sont VALIDÉS).
# PGDR_V1_TRANSLATIONS : traductions françaises préparées, affichées à côté du texte exact (brouillon : essai seulement, marqué).
set -euo pipefail
here="$(cd "$(dirname "$0")/../.." && pwd)"
manifest="${1:?chemin du manifest.yaml de la notice requis}"
port="${2:-8010}"
case "$(cd "$(dirname "$manifest")" && pwd)/" in "$here"/*) echo "Refus : la notice doit rester hors du dépôt." >&2; exit 1;; esac
export PGDR_V1_MANIFEST="$manifest"
export PGDR_V1_DEV_TRIAL=1
: "${PGDR_V1_DEV_VEHICLE:?identité VIR simulée requise (JSON manufacturer/model/generation)}"
export PGDR_V1_DEV_VEHICLE
unset PGDR_PHOTO_WIRING_FACTORY
echo "Essai de développement : http://127.0.0.1:${port}/v1/essai-dev"
exec "$here/.venv/bin/python" -m uvicorn pgdr.web_app:app --host 127.0.0.1 --port "$port" --workers 1
