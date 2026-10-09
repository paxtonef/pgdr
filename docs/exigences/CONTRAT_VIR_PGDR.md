# Contrat de transfert VIR → PGDR

**Statut : Proposition, non validée.** Aucune décision du propriétaire n'est
enregistrée dans ce document. Rien ici n'est implémenté.

Sans contenu constructeur : aucun identifiant, titre ni citation de notice réelle,
aucun VIN ni numéro d'immatriculation.

## 1. État actuel (constat, branche `v1-premier-constat`)

| Élément | Où | Constat |
|---|---|---|
| Point d'entrée V1 | `src/pgdr/v1_parcours.py` `vir_handoff()` → `_open_parcours()` | `POST /api/v1/vir-handoff`, corps `VehicleIdentityContext`. |
| Point d'entrée Photo-First | `src/pgdr/web_app.py` `receive_identity_handoff()` | `POST /api/photo/identity-handoff`, même corps. |
| Authentification | `web_app.py` `_require_handoff_credential()` | Jeton partagé `PGDR_IDENTITY_HANDOFF_TOKEN`, en-tête `X-PGDR-Identity-Handoff-Token`, comparaison à temps constant ; absent → 503, faux → 403. |
| Format reçu | `src/pgdr/models.py` `VehicleIdentityContext` | Obligatoires : `resolution_id`, `resolution_status`. Optionnels : `confidence`, `vehicle_identity` (dictionnaire libre), `unresolved_fields`, `contradictions`. |
| États | `src/pgdr/enums.py` `ResolutionStatus` | `resolved`, `provisionally_resolved`, `ambiguous`, `insufficient_data`, `contradictory`. |
| Lecture des champs | `src/pgdr/domain/dashboard_knowledge.py` `VehicleApplicabilityContext.from_pgdr_vehicle_identity_dict()` | Lit marque, modèle, génération, année de production, dates de production, motorisation, boîte, transmission, finition (`trim`), variante (`variant`). Champ absent → vide, jamais déduit. |
| Applicabilité (Photo-First) | `src/pgdr/application/vehicle_applicability.py` | Clés `manufacturer`, `model`, `generation` ; absente, non résolue ou contradictoire → `VEHICLE_IDENTITY_INSUFFICIENT`. |
| Applicabilité (V1) | `ManifestNoticeRepository.matches()` | Égalité marque + modèle + génération seulement ; puis `applicability_established` de la revue de la notice. |
| Identité simulée | `v1_parcours.py` `dev_trial_entry()`, `outils/essai_dev_v1/lancer.sh` | `GET /v1/essai-dev` fabrique un `VehicleIdentityContext` `resolved` (`DEV-TRIAL-SIMULATED-VIR`) depuis `PGDR_V1_DEV_VEHICLE`, seulement si `PGDR_V1_DEV_TRIAL=1`, avec bandeau permanent. |
| Exemples réels | `tests/fixtures/vir_handoff_contexts.json` | Sorties capturées du vrai VIR via le vrai `handoff_mapper.map_resolution()` de PI : état `provisionally_resolved`, `trim`/`variant`/code moteur/VIN non résolus. |

Constats à corriger (proposés, non implémentés) :

1. V1 refuse tout état autre que `resolved`. Les exemples réels de VIR sont
   `provisionally_resolved` : le vrai VIR ouvrirait donc aujourd'hui le message
   « identité non établie ».
2. V1 ne lit pas `unresolved_fields` ni `contradictions` : un état `resolved`
   avec une génération contestée passe jusqu'à la comparaison.
3. Photo-First ne lit pas `resolution_status` : un état `ambiguous` avec les
   trois clés présentes est accepté.
4. Photo-First conserve l'identité complète reçue, y compris `identifiers`
   (plaque, VIN), dans `_photo_intakes`, sans limite ni expiration jusqu'au
   redémarrage. V1 ne garde que marque, modèle, génération (`Parcours.vehicle`,
   1000 parcours au plus).
5. Aucun des deux chemins n'utilise version, millésime ni édition.
6. Après ouverture, V1 transmet à SafetyEngine un contexte reconstruit
   (`V1-PARCOURS`, `resolved`, marque/modèle/génération). SafetyEngine ne lit
   pas l'identité ; l'affichage montre marque, modèle, génération.

## 2. Champs du transfert

### 2.1 Enveloppe

| Champ | Obligatoire | Sens |
|---|---|---|
| `contract_version` | oui | Version de ce contrat (ex. `"1"`). Inconnue → refus. |
| `resolution_id` | oui | Référence opaque VIR ; ne doit contenir aucun identifiant du véhicule. |
| `resolution_status` | oui | Voir §3. |
| `issued_at` | oui | Horodatage d'émission par VIR. |
| `confidence` | non | Information ; jamais un seuil d'autorisation dans PGDR. |
| `vehicle_identity` | oui sauf échec | Voir §2.2. |
| `unresolved_fields` | oui (liste, éventuellement vide) | Chemins de champs non établis par VIR. |
| `contradictions` | oui (liste, éventuellement vide) | Chemins de champs contradictoires. |

### 2.2 Identité (clés utiles à la recherche de notice)

| Clé | Sens | Reçue aujourd'hui | Rôle pour la notice |
|---|---|---|---|
| `manufacturer` | constructeur | oui | requise |
| `model` | modèle | oui | requise |
| `generation` | génération | oui (absente en saisie manuelle VIR) | requise |
| `production.year` | année de production | oui | millésime : requis si la notice en dépend |
| `production.start_date` / `end_date` | période | prévue, vide dans les exemples | aide à l'édition |
| `model_year` | millésime commercial, distinct de l'année de production | **non** | à décider |
| `trim` | finition | prévue, non résolue dans les exemples | version : requise si la notice en dépend |
| `variant` | version / variante | prévue, non résolue dans les exemples | idem |
| `cluster_type` (`type_combine`, décision D6) | type de combiné | **non** | sélection de variante d'images |
| `first_registration_date` | date de 1re mise en circulation (date seule) | **non** | aide à l'édition ; à décider |
| `fuel`, `engine`, `transmission`, `drivetrain`, `body` | caractéristiques techniques | oui | équipements « selon équipement » |

L'**édition** de la notice n'est pas un champ VIR : CPL la choisit à partir des
champs ci-dessus et conserve les éléments qui établissent l'applicabilité
(exigence `LANGUE_NOTICE_PARCOURS_FRANCOPHONE.md`).

### 2.3 Jamais transmis à PGDR

VIR ne transmet pas, et PGDR refuse (rejet du transfert entier, pas de filtrage
silencieux) tout transfert contenant :

- le VIN ;
- le numéro d'immatriculation, et le pays d'immatriculation associé ;
- tout contenu ou image du certificat d'immatriculation (carte grise), notamment
  les rubriques A (immatriculation), E (numéro d'identification du véhicule) et
  C (titulaire : nom, adresse) ;
- toute donnée du titulaire ou du conducteur.

En conséquence le bloc `identifiers` disparaît du transfert. `unresolved_fields`
ne mentionne pas non plus ces champs.

## 3. États de résolution et comportement de PGDR

« Clés requises » = marque, modèle, génération, plus les clés dont dépend
l'applicabilité de la notice candidate (millésime, version) selon CPL.

| État VIR | Valeurs | Aujourd'hui (V1) | Proposé |
|---|---|---|---|
| Résolu | `resolved` | Ouvre si marque/modèle/génération = notice et applicabilité établie. | Ouvre si toutes les clés requises sont présentes, ni non résolues, ni contradictoires, et si CPL établit l'applicabilité. |
| Partiel | `provisionally_resolved`, ou `resolved` avec clés requises dans `unresolved_fields` | Refus « identité non établie » (pour `provisionally_resolved`). | Traité comme résolu **seulement si** aucune clé requise n'est non résolue ou contradictoire ; sinon échec fermé « identité insuffisante » nommant les éléments manquants. |
| Ambigu | `ambiguous` | Refus. | Échec fermé. Jamais de choix entre candidats par PGDR ; jamais de question au conducteur sur l'identité. |
| Échec | `insufficient_data`, `contradictory`, champ obligatoire absent, version de contrat inconnue, champ interdit présent | Refus ou erreur de validation. | Échec fermé, message explicite, aucune notice affichée. |

## 4. Règles d'échec fermé

1. Aucune notice n'est présentée comme applicable sans identité suffisante et
   applicabilité établie par CPL.
2. Une notice « proche » (autre génération, autre millésime, autre édition)
   n'est jamais proposée à la place.
3. Le conducteur ne complète ni ne corrige l'identité dans PGDR.
4. Chaque refus est signalé explicitement, avec la raison (identité
   insuffisante, ambiguë, contradictoire, aucune notice applicable).
5. Le mode essai de développement (`PGDR_V1_DEV_TRIAL`, `PGDR_V1_DEV_VEHICLE`)
   reste le seul chemin d'identité simulée, jamais actif en production, et
   toujours signalé par un bandeau.

## 5. Authentification du transfert (options, aucune choisie)

| Option | Principe | Risques |
|---|---|---|
| A. Jeton partagé (actuel) | Secret commun en en-tête, comparaison à temps constant. | Fuite = usurpation totale ; rotation manuelle ; pas d'expiration ni de rejeu empêché. |
| B. Jeton partagé + réseau privé | A, plus écoute de PGDR uniquement sur le réseau interne du serveur commun. | Dépend de la configuration réseau ; ne protège pas d'un processus local compromis. |
| C. TLS mutuel | Certificats client/serveur. | Gestion des certificats et de leur renouvellement ; erreur de configuration = coupure. |
| D. Jeton signé à courte durée (HMAC ou signature asymétrique) | VIR signe le contenu, `issued_at`, un identifiant unique ; PGDR vérifie signature, fraîcheur, non-rejeu. | Horloges à synchroniser ; registre des identifiants déjà vus ; gestion des clés. |
| E. Appel interne (même processus ou socket local) | Pas de transfert HTTP. | Couplage fort entre VIR et PGDR ; dépend de la décision de localisation. |

## 6. Durée de vie en mémoire

Proposé :

- PGDR ne conserve que les clés utiles à la notice (§2.2), jamais l'enveloppe brute.
- Durée : celle du parcours, avec une expiration (par exemple 2 h d'inactivité,
  valeur à décider) et une borne du nombre de parcours, pour les deux chemins
  (V1 et Photo-First).
- Rien n'est écrit sur disque ni dans les journaux (pas de `resolution_id` ni
  d'identité dans les journaux d'erreur).
- Perte au redémarrage acceptée (sessions éphémères).

## 7. Lien avec l'applicabilité d'une notice

- VIR établit l'identité ; CPL choisit la notice applicable (priorité au français,
  exigence `LANGUE_NOTICE_PARCOURS_FRANCOPHONE.md`) et conserve langue, référence
  d'édition, source et preuves d'applicabilité ; PGDR vérifie et affiche.
- PGDR compare l'identité reçue aux clés d'applicabilité déclarées par la notice,
  pas seulement marque/modèle/génération.
- Si aucune notice française applicable n'existe, PGDR le dit ; une notice dans
  une autre langue n'est affichée qu'avec cette mention, jamais traduite en silence.

## 8. Hors champ

Implémentation, migration, import CPL, fournisseur externe, choix de
l'authentification, localisation de VIR : décisions du propriétaire.
