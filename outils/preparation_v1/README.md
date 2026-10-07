# PGDR scripts et YAML — correction 1.1

Cette version remplace le paquet de préparation précédent. Elle corrige les cinq points relevés. **Ce n’est pas encore une V1 web raccordée. Aucun import CPL, test PostgreSQL ou test navigateur n’est revendiqué.**

## Installation

Dans le dossier décompressé, avec Python 3.10 ou plus récent :

```bash
bash installer.sh
.venv/bin/python scripts/verifier_yaml.py
```

L’installateur installe les dépendances et lance les 110 tests du paquet. Il n’applique aucune migration, ne charge aucune notice, n’envoie aucune photo et ne modifie pas les dépôts.

Pour préparer des branches locales sur la base contenant E9 :

```bash
.venv/bin/python scripts/preparer_depots.py ../depots-v1
```

Le script refuse les modifications locales et bases divergentes, sans reset ni push. GGM reste à installer depuis l’archive canonique fournie.

## Textes de repli : une seule référence

`config/fallback_screens.en.yaml` reprend exactement les deux écrans anglais de la note. `colour_fallback()` lit ce fichier ; il ne maintient plus ses propres formulations françaises. Rouge ou incertain utilise l’écran d’arrêt ; les autres couleurs l’écran non résolu. Aucun statut de vérification ni handoff n’est impliqué. La traduction française `config/fallback_screens.fr.yaml` est VALIDÉE (Fred Cobral, 2026-10-07, empreinte de la source anglaise consignée) ; c'est elle que l'interface V1 affiche. Toute modification exige une nouvelle validation nommée.

Le YAML runtime consigne aussi la conservation des sélections par ID, le retour en ordre manuel, la reconfirmation explicite, la conservation de la couleur et les sections distinctes par image. **Ce sont les règles du futur parcours web, pas une interface déjà réalisée.**

## Notice : format v2 et correspondance CPL

Le gabarit `config/notice_a_remplir.yaml` utilise les noms de colonnes CPL pour les entrées. Il conserve couleur, état, message affiché, signal sonore, signification, consigne et références de voyants combinés. Les valeurs absentes de la source restent explicitement null ; aucune couleur ou consigne n’est inférée. L’ordre est celui de la liste d’entrées.

Lire `CPL_MAPPING.md` pour la correspondance champ par champ et `cpl/migration_assets_proposal.sql` pour l’extension additive proposée : une table de fichiers/revue par document et une table image/page/ordre par entrée. Cette proposition doit être intégrée aux modèles et à la chaîne Alembic CPL. **Elle n’est pas appliquée, et la transaction d’import et le contrôle de revue à la lecture restent à coder.**

Une entrée peut porter `linked_warnings` : les avertissements numérotés de la notice rattachés par renvoi imprimé (numéro, texte exact, page imprimée, page PDF) et les pictogrammes imprimés dans leur texte (position, texte avant/après, fichier, empreinte, pages, entrées représentées, justification). Le champ est facultatif (absent = aucun avertissement ; les manifestes v2 sans ce champ restent valides). `--export-cpl` les exporte intégralement sous `entry_warnings`, et deux tables proposées (non appliquées) les reçoivent.

Une entrée peut aussi porter `inline_pictograms` (pictogrammes imprimés dans `documented_meaning`, même structure), `notes` (liste de textes) et `field_sources` (passage source d’un champ documenté ailleurs que dans le passage de l’entrée). Ils sont exportés sous `entry_inline_pictograms`, `entry_notes` et `entry_field_sources`, avec trois tables proposées non appliquées. `where_provided` (booléen) et `documented_startup_check` (phrase exacte ou null) sont exportés sous `entry_presentation`, une ligne par entrée (absent = null, jamais converti en false), avec une table proposée non appliquée. Tout autre champ du manifeste est nommé dans `not_exported_fields` et signalé sur la sortie d’erreur : aucun champ n’est perdu en silence.

Chaque entrée doit avoir une image PNG/JPEG valide, une page PDF existante et une référence imprimée. La validation vérifie les fichiers et leurs empreintes, l’absence de chemins sortant du dossier, les IDs uniques et les références combinées dans la même notice. Elle ne démontre pas la justesse du texte constructeur : cette association est vérifiée par une personne.

## Enregistrer une validation humaine

1. Copier le gabarit près du PDF et des images extraites.
2. Remplir les champs exacts, y compris les empreintes obtenues avec `shasum -a 256`.
3. Une personne vérifie véhicule/édition, image, texte et pages.
4. Calculer l’empreinte de tout le contenu structuré :

```bash
.venv/bin/python scripts/notices.py /chemin/notice/manifest.yaml --fingerprint
```

5. Reporter cette empreinte dans `review.content_sha256`, l’identifiant et le nom du vérificateur, une date ISO avec fuseau (`2026-10-06T11:30:00+02:00`), puis `status: approved`.
6. Vérifier et exporter :

```bash
.venv/bin/python scripts/notices.py /chemin/notice/manifest.yaml
.venv/bin/python scripts/notices.py /chemin/notice/manifest.yaml --export-cpl
.venv/bin/python scripts/notices.py /chemin/notice/manifest.yaml --select ID_1 ID_2
```

Une modification du manifeste, de l’ordre, des textes, des avertissements liés, des pictogrammes, des notes, des sources, de l’applicabilité ou des empreintes rend la validation obsolète. Une modification des fichiers est refusée. Le contenu exporté n’est PAS chargé dans CPL. La revue est une attestation nommée ; l’authentification et l’audit du vérificateur restent à raccorder côté CPL. Il ne s’agit pas d’une signature cryptographique.

## Tri : essai nécessaire, désactivé par défaut

Sans modèle :

```bash
.venv/bin/python scripts/trier_images.py /chemin/notice/manifest.yaml /chemin/photo.jpg --config config/runtime.yaml
```

Pour un essai de tri, configurer le modèle, le destinataire nommé, puis des limites réellement connues : `max_images_per_request`, `max_request_bytes`, `max_batches`. Elles restent null par défaut pour ne pas inventer les limites d’un fournisseur. Le nombre d’images inclut la photo de référence. Sans ces limites, retour immédiat à l’ordre de la notice.

Si le catalogue tient dans une requête, le modèle reçoit toutes les images. Sinon, la stratégie expérimentale les répartit en lots consécutifs : chaque requête reçoit la photo et un lot. Les ordres complets de lots sont entrelacés par rang, puis la permutation du catalogue entier est contrôlée. **Ce n’est pas un classement global par similarité.** La sortie indique `batch_similarity_interleaved` et `global_similarity_rank: false`. Aucun lot n’est filtré. Le nombre d’appels et le coût peuvent augmenter ; un échec d’un seul lot entraîne le retour de tout le catalogue en ordre manuel.

Cette stratégie étend la requête unique de la première proposition. Elle doit être évaluée sur un catalogue réel avant adoption dans PGDR. Si elle n’apporte pas de bénéfice, garder l’ordre constructeur. `real_trial_completed: false` est une information de qualification ; ce script expérimental ne constitue pas un gate d’admission automatique.

La sortie accepte du JSON brut ou un seul bloc de code JSON, sans prose autour. Après retrait de cet emballage, le contrat reste strict : uniquement `ordered_entry_ids`, permutation complète, sans doublon, omission, ID étranger ou champ supplémentaire.

Pour LM Studio, activer explicitement puis passer `--provider lmstudio --consent-provider "LM Studio sur votre serveur"`. Pour OpenRouter, définir le fournisseur amont, le routage sans fallback et le nom de tous les destinataires, vérifier ce routage puis fixer `routing_verified: true`. La clé se trouve exclusivement dans `OPENROUTER_API_KEY`, jamais dans le YAML. Passer le même nom complet à `--consent-provider`. Les règles de conservation externes doivent être établies avant tout essai réel.

Le script ne copie ni ne conserve la photo ; il ne supprime pas le fichier utilisateur d’entrée. La suppression en fin de parcours web reste à implémenter. Aucun appel à un fournisseur réel et aucune transmission de photo réelle n’ont eu lieu pendant nos tests.

Xiaomi MiMo-V2.6-Pro reste inscrit au catalogue de souhaits, sans disponibilité ou support image attesté et sans activation.

## CBS et raccordements

Les trois fichiers `*_cbs_requirements.yaml` restent des déclarations source provisoires, pas des sorties O2 admises. CBS ne sélectionne pas le fournisseur et n’exécute pas le tri.

Restent : import atomique et stockage effectif CPL, lecture des actifs par PGDR, adaptation du passage VIR, retrait de la reconnaissance du candidat précédent, interface conforme à la note, consentement réel, suppression photo, suite complète et navigateur, inventaire réel de couverture. Pas de push sur main sans accord.
