# Clôture fonctionnelle PGDR V1

Document du 2026-10-20. Branche PGDR `v1-cloture` ; branche PI `pi-cloture-pgdr`. Aucun push, aucune fusion,
aucun déploiement, aucune migration réelle, aucun appel fournisseur ni modèle. Notices fictives pour les essais
reproductibles ; dossier Fiat lu sans modification.

**Périmètre :** le parcours décrit ci-dessous, depuis PI. PGDR ne cherche, ne télécharge et ne sélectionne
aucune notice : il reçoit celle que le montage lui fournit (`PGDR_V1_MANIFEST`). Le contrôle de correspondance
(identité reçue de VIR contre le manifeste) est inchangé : il refuse une notice qui ne correspond pas et n'en
cherche pas d'autre.

## 1. Versions compatibles

| Composant | Révision | Remarque |
|---|---|---|
| PGDR | `55f76ae` (`v1-cloture` : `9b83845` code de la clôture, puis `55f76ae` textes retenus du parcours sans notice ; depuis `v1-fiat-provenance` @ `79db828`, depuis `v1-3b-reception` @ `1c5a5cc`) | ce document est mis à jour par le commit suivant (documentation seule) |
| PI | `70a15b3` (`pi-cloture-pgdr` : `367c065`, puis `70a15b3` ; depuis `pi-fiat-provenance` @ `63fe09b`, depuis `pi-3b-conservation-purge` @ `a676809`) | `deploy/COMPOSITION.env` : `PGDR_COMMIT=55f76ae…` |
| VIR | `a4c0172` | non modifié (clos : `docs/CLOTURE_VIR_V1.md` du dépôt VIR) |
| CPL | `bc09253` | non modifié |

Aucune branche descendante de `79db828` ou de `63fe09b` n'existait au départ ; aucune correction n'était à reprendre.

## 2. Les six critères

Étiquettes : **[cité]** preuve existante couvrant le code livré ; **[exécuté]** pendant cette passe.

### Critère 1 — Photo avec consentement explicite, sans conservation : satisfait

- [cité] Bloc 2 « parcours photo » et bloc 3A/3B (PI `PI_PARCOURS_PHOTO_V1_COMPTE_RENDU_v0.md`,
  `PI_BLOC_3B_COMPTE_RENDU_v0.md`) : consentement du parcours, accord séparé nommant le destinataire du tri,
  photo réencodée par la page (pixels seuls), métadonnées retirées par PI puis par PGDR ; sans tri, la photo ne
  quitte pas l'appareil. Tests PGDR `tests/test_v1_propositions.py` (aucun VIN, plaque ni donnée de carte grise
  dans la demande de tri : `Recorder`), PI `tests/test_notice_parcours.py::test_c_…`.
- [exécuté] PI `tests/test_cloture_pgdr_v1.py::test_the_photo_is_kept_nowhere_after_proposals_or_a_sorting_failure` :
  après des propositions puis après une panne du tri, aucun fichier dans `PI05_MEDIA_STORAGE_DIR`, aucune ligne
  `pi_auth.media_ownership` de plus, aucune trace de la photo ni de la plaque dans un vidage complet de la base
  (donc dans aucune sauvegarde), dans un nouveau fichier temporaire ou dans les journaux. PI et PGDR ne
  manipulent la photo qu'en mémoire (aucun fichier temporaire dans `pgdr.v1_propositions`,
  `product_integration.pgdr.notice_parcours` ni dans le relais).
- [exécuté] Navigateur, lancement de production : `tests/test_cloture_navigateur.py::test_a_c_f_e_j_…`, consentement
  refusé puis donné, photo jamais envoyée (aucune requête ne la porte).

### Critère 2 — Deux à trois images proposées, ou le catalogue complet : satisfait

- [cité] `pgdr.v1_propositions` (contrat strict, 1 à 3 identifiants du catalogue, sans score) ; repli expliqué
  sur le catalogue si le tri est absent, en panne, invalide ou sans proposition (tests PGDR
  `test_v1_propositions.py`, PI `test_e_…`).
- [exécuté] Playwright O1–O3 (faux tri d'essai) et P (tri absent ; tri en panne), §5.

### Critère 3 — Choix explicite, confirmation, sans présélection : satisfait

- [cité] Sélection par `entry_id`, confirmation explicite de la sélection affichée, retour au catalogue qui annule
  la confirmation (tests PGDR `test_v1_parcours*.py`, `test_v1_premier_constat.py::test_never_chosen_for_the_driver`).
- [exécuté] Navigateur : aucune tuile présélectionnée (propositions et catalogue), Playwright Q1 et réception de
  production.

### Critère 4 — Consignes du constructeur exactes avec pages, puis consignes de sécurité : satisfait

- [cité] Restitution exacte (une section par image, textes tels que stockés, page imprimée et page PDF) ; Premier
  Constat existant : SafetyEngine inchangé, R-5 (peut relever, jamais abaisser), présentation approuvée
  (blocs 3A, Premier Constat, actions validées ; tests PGDR `test_v1_premier_constat.py`,
  `test_v1_actions_validees.py`, `test_v1_exclusion_encadree.py`).
- [exécuté] Réception de production : passage exact et « Page de la notice … (page PDF …) », puis Premier
  Constat, résultat enregistré.

### Critère 5 — Sans notice ou notice non correspondante : écran fixe et consignes de sécurité : satisfait après correction

- **Défaut constaté :** jusqu'ici, un refus (`notice_unavailable`, `vehicle_not_supported`,
  `applicability_not_confirmed`, `vehicle_identity_insufficient`) laissait le conducteur sur le refus affiché dans
  le dossier, sans consignes de sécurité.
- **Correction (PGDR `9b83845`, PI `367c065`) :** le refus reste tel quel ; PGDR ouvre à côté un **parcours sans
  notice** : écran d'information à texte fixe (titre, information, suite du parcours), puis le choix de la
  couleur (boutons), puis l'écran de sécurité **validé** existant (`v1_fallback_screens.fr.yaml`, validation
  nommée du 2026-10-07) : rouge ou incertain → « Arrêtez-vous en sécurité » (règle existante), autre couleur →
  « Voyant non identifié ». Le dossier PI affiche « Voir les consignes de sécurité ». Aucun catalogue, aucune
  image, aucun texte de la notice qui ne correspond pas (toutes les routes de notice répondent 409), rien
  d'enregistré dans CPL.
- [exécuté] PGDR `tests/test_v1_cloture.py` (les quatre refus), navigateur PGDR
  `test_v1_without_corresponding_notice_…` ; PI `tests/test_cloture_pgdr_v1.py::test_refusal_leads_to_…` (trois
  refus de notice, droits du propriétaire), réception de production (identité non établie ; second lancement sans
  `PGDR_V1_MANIFEST`), Playwright Q2.
- **Textes retenus (PGDR `55f76ae`, formulations du propriétaire du 2026-10-20, hors fichier de libellés, sans
  mention de brouillon) :** titre « Notice indisponible pour ce véhicule » ; information « Aucune notice
  applicable à votre véhicule n'est disponible dans ce parcours. Nous ne pouvons donc pas afficher de consignes
  constructeur. » ; suite « Vous pouvez consulter les consignes générales de sécurité selon la couleur du
  voyant. ». Les mêmes textes servent à « aucune notice fournie » et à « notice non correspondante » : le message
  de refus n'est plus repris sur cet écran (il reste affiché, inchangé, dans le dossier PI).
- **Écran de sécurité sans notice :** seule la phrase de contexte « Nous n'avons pas pu faire correspondre votre
  voyant à une image de la notice. » est remplacée, à l'affichage et dans ce seul parcours, par « Aucune notice
  applicable n'est disponible pour le voyant observé. ». Titres, consignes, consigne d'arrêt et règle de
  déclenchement (rouge ou incertain → arrêt) sont ceux du fichier validé, qui n'est pas modifié ; le parcours
  avec notice garde la phrase d'origine.

### Critère 6 — Sans dialogue texte ni questionnaire mécanique : satisfait après correction

- **Défauts constatés :**
  1. Dans PGDR V1, l'étape de précision demandait, pour un groupe que seul un message distingue, de **recopier le
     message** dans un champ de texte (`/clarify`, réponse `message`).
  2. Le dossier PI proposait « Start a diagnostic » : l'ancien diagnostic PI-04 (plainte en **texte libre**,
     questions de `SessionController`/`DiagnosticLoop`, rapport de préparation garagiste), servi par le point
     d'entrée de production.
- **Corrections :**
  1. PGDR : la question de message n'est plus posée ; le groupe est présenté comme ambigu, avec tous ses
     passages et leurs consignes (issue déjà existante de « Aucun message / Je ne sais pas ») ; `/clarify` refuse
     toute réponse qui n'est pas une entrée du groupe, « je ne sais pas » ou « aucun de ceux-ci ».
  2. PI : routes `POST /cases/{id}/diagnostics` et `…/answers` déplacées sur un routeur à part, jamais inclus par
     le point d'entrée de production (même avec `PI_DIALOGUE_HISTORIQUE=1`), inclus par une autre assemblée
     seulement si elle le demande. Frontend : lien et route `/cases/{id}/diagnostic` présents seulement si la
     construction le demande (`VITE_PI_DIALOGUE_HISTORIQUE=1`) ; le paquet de production n'en contient aucun texte.
     Code conservé, non supprimé.
- [exécuté] Espions qui font échouer le test : PGDR `test_v1_cloture.py::test_the_whole_parcours_never_reaches_a_dialogue_engine`
  (`SessionController`, `DiagnosticLoop`, `ComplaintParser`, contrôleur de `web_app`) sur tout le parcours
  (propositions, catalogue, précision, condition, retour, aucune ne correspond, couleur, sans notice) ; PI
  `test_the_v1_parcours_never_reaches_a_dialogue_engine` (mêmes classes, plus `start_vehicle_diagnostic`,
  `continue_vehicle_diagnostic` et Photo-First). Absence de saisie libre : `test_the_v1_page_has_no_free_input`,
  Playwright Q1, réception de production (contrôle à chaque écran). Routes : §3.

## 3. Le parcours sans dialogue

Aucun champ de texte, aucun agent conversationnel, aucun message produit par un modèle : PGDR ne contient aucun
client de modèle de langage ; le seul transport de tri est le faux transport d'essai.

| Écran (page /v1 de PGDR, servie par PI) | Contrôles |
|---|---|
| Votre véhicule | bouton « Continuer » |
| Avant de commencer | case « J'ai compris et je souhaite continuer », bouton « Continuer » |
| Photo (facultative) | sélecteur de photo, « Retirer la photo » ; avec un tri : case d'accord nommant le destinataire, « Proposer des images à partir de ma photo » ; « Voir les images de la notice » |
| Images proposées | tuiles (choix), « Valider ma sélection », « Aucune ne correspond : voir toutes les images de la notice » |
| Images de la notice | tuiles (choix), « Valider ma sélection », « Aucune ne correspond », « Je ne sais pas » |
| Confirmez votre sélection | « Je confirme : ces images correspondent à ce que je vois », « Revenir aux images de la notice » |
| Précisez ce que vous voyez | un bouton par variante (élément documenté par la notice et sa source), « Je ne sais pas », « Aucun de ceux-ci », retour |
| Restitution et Premier Constat | condition d'une consigne d'arrêt : « Oui », « Non », « Je ne sais pas » ; « Voir l'écran prévu pour un voyant rouge ou incertain » ; « Réessayer l'enregistrement » (produit) ; retour |
| Couleur du voyant | 8 boutons de couleur (dont « Je ne sais pas / incertain »), retour |
| Écran de sécurité | retour |
| Notice indisponible pour ce véhicule | 8 boutons de couleur ; l'écran de sécurité s'affiche dessous |

Les choix de précision et de condition sont des commandes fermées déjà prévues, tirées de la notice ; il n'y a
au plus qu'un choix par groupe ou par consigne, jamais une suite de questions. Côté dossier PI : « Open the
manufacturer notice », « Voir les consignes de sécurité », l'historique. Les formulaires de connexion et
d'identification VIR ne font pas partie du parcours PGDR.

**Routes atteignables depuis le parcours**
- PGDR (liste fermée, `test_the_parcours_exposes_a_closed_list_of_routes`) : `POST /api/v1/vir-handoff` (jeton
  serveur à serveur) ; `GET /v1` ; `GET /api/v1/parcours/{pid}`, `…/catalogue`, `…/propositions`,
  `…/asset/{sha}` ; `POST …/vir-seen|consent|propositions|selection|confirm|clarify|condition|no-match|colour|return` ;
  `GET /v1/essai-dev` (essai de développement seulement).
- PI, relais (liste fermée, `notice_parcours._ALLOWED`) : les mêmes requêtes de parcours, ni `vir-handoff` ni
  `essai-dev`, plus `POST /api/v1/parcours/{pid}/record`.
- PI, API de production (`test_the_production_entry_never_serves_the_legacy_dialogue`, liste exacte) : auth,
  `/me`, contacts, véhicules, dossiers, VIR (clarifications, confirmations), exécutions et artefacts, `/media`,
  `notice-parcours`, `notice-results`, page et relais /v1 ; **pas** de `/cases/{id}/diagnostics`.

**Ancien code de dialogue :**
- **Dans le dépôt :** il reste présent, sans suppression : PGDR `session_controller.py`,
  `application/diagnostic_loop.py`, `complaint_parser.py`, et les routes `/api/session/…` et `/api/photo/…` de
  `web_app.py` ; PI `orchestration`, `pgdr/session_adapter.py`, `pgdr/photo_intake.py`, et les composants
  `ComplaintForm`, `DiagnosticQuestionForm` et `GaragePreparationReportView`.
- **Exposition par une route :**
  - les routes PGDR de `web_app.py` restent servies par le processus PGDR sur la boucle locale, mais PI ne les
    relaie jamais (liste fermée) ;
  - les routes PI de diagnostic ne sont plus servies par le point d'entrée de production ;
  - Photo-First (`request_photo_first_intake`) n'est appelé par aucun code de PI.
- **Accessibilité depuis l'interface :** aucun lien ni route dans une construction de production.
- **Résultats déjà enregistrés :** les rapports de diagnostic passés de l'ancien dialogue restent stockés dans
  CPL et lisibles par l'écran de résultat ; ils ne sont ni modifiés ni recalculés.

## 4. Acquis Fiat et Peugeot 3008 réutilisés

| Acquis | Ce qu'il démontre | Limite |
|---|---|---|
| Fiat 500e : manifeste (empreinte `fcdf89c2…`), revue du 2026-10-07, cinq fichiers VALIDE (groupes, explications, situations, traductions, libellés), quatre attestations du 2026-10-08 | Le format de notice, la restitution exacte, les groupes, les situations et les traductions ont été établis et validés sur une vraie notice ; le parcours V1 a été construit sur elle. [exécuté] Relu avec le code de clôture, sans modification : même empreinte, cinq fichiers acceptés, aucun libellé rejeté, empreinte globale du dossier inchangée (`bb89cf3a…`). | Essai de développement (`outils/essai_dev_v1/lancer.sh`, identité VIR simulée, bandeau permanent), pas un essai de production. Applicabilité réelle non établie (`applicability_established: false`, aucune attestation réelle). |
| Fiat : écrans de repli traduits et validés (2026-10-07), formulations T2 et limite d'ambiguïté du propriétaire (2026-10-08) | Ce sont les textes de sécurité affichés par le parcours, sans notice compris. | — |
| Fiat : effet de la clôture | 5 des 7 groupes validés déclenchaient la question de message tapé. Ils sont désormais présentés comme ambigus, avec tous leurs passages et consignes, et rien n'est choisi pour le conducteur. | Le conducteur ne peut plus départager ces variantes par le message. Un choix fermé parmi les messages documentés serait une évolution à demander. |
| Peugeot 3008 : connaissance constructeur B2-K (PGDR `ec24422`, PI `b73c6c6` : graine « attestée par le propriétaire, non vérifiée ») et séparation fraîcheur/applicabilité (`fade292`) | La règle de véracité des sources, reprise par l'applicabilité V1. | Elle sert l'ancien chemin Photo-First, qui n'est pas le parcours V1. Aucune notice Peugeot réelle n'est chargée en V1. |
| Peugeot 3008 II : véhicule de la fixture VIR simulée, notices fictives `fn_*` à son identité | Les essais reproductibles de bout en bout dans le produit. | Notices fictives, jamais présentées comme réelles. |

Aucun catalogue, aucune validation, recherche d'applicabilité, classification ou traduction n'a été refait.

## 5. Essais de cette passe [exécuté]

| Suite | Résultat |
|---|---|
| PGDR complète (hors `packaging`, qui demande un accès réseau pour `hatchling`) | **1056 passed** (1046 au départ ; +9 `test_v1_cloture.py`, +1 navigateur) ; relancée après `55f76ae` : 1056 passed |
| PGDR navigateur (`test_v1_browser_e2e.py`) | 10 passed |
| PI complète, avec le montage de développement des nouveaux arbres | **405 passed, 0 skipped, 0 failed** (392 au départ ; +8 `test_cloture_pgdr_v1.py`, +5 navigateur) ; relancée après `70a15b3` : 405 passed |
| PI réception navigateur, lancement de production (HTTPS, frontend construit, deux lancements) | **5 passed** (`test_cloture_navigateur.py` : A, C, E, F, G ×2, H, I, J) |
| Frontend : `tsc -b --noEmit` / vitest / `vite build` | OK / **54 passed** / OK |
| Playwright O1–O4 et Q1–Q2 (faux tri d'essai, sans dialogue) | 6 passed ; relancés après `70a15b3` : 6 passed |
| Playwright P (tri absent ; tri en panne) | 1 passed ; 1 passed |
| Playwright A→M (ancien dialogue, construction d'essai `VITE_PI_DIALOGUE_HISTORIQUE=1`) | 14 passed : non-régression du code conservé, hors produit |

**Tests existants modifiés (comportement retiré volontairement) :**
- PGDR :
  - `test_v1_situations.py` : le test de la question de message devient « aucun message n'est demandé, le groupe
    reste ambigu, un message tapé est refusé » ; les assertions sur les variantes sont conservées.
  - `test_v1_mentions_statut.py` et `test_v1_browser_e2e.py` (deux tests) : passent par la restitution au lieu
    de la question de message.
  - `test_v1_3a_applicabilite.py` et `test_v1_provenance_applicabilite.py` : « aucun parcours ouvert » devient
    « aucun parcours avec notice ouvert ».
- PI : `test_notice_parcours.py` et `test_provenance_applicabilite.py`, même remplacement, et le parcours sans
  notice du propriétaire est vérifié.
- Aucune autre assertion n'a été retirée.
- Non relancé : spec N (VIR réel sur faux transports), car le raccordement VIR n'a pas changé (preuve du bloc 3B).

## 6. Limites acceptées pour cette clôture

- Le tri réel n'existe pas : le catalogue complet est le comportement V1 accepté en son absence.
- Le faux tri ne vérifie que les propositions et les transitions ; il est réservé aux essais (refusé par le
  lancement de production) et n'est jamais activé en production.
- L'ouverture d'une notice réelle en production n'est pas une condition de cette clôture ; la restitution exacte
  est vérifiée sur notice fictive, en complément des preuves Fiat.
- Une notice fictive n'est jamais présentée comme réelle. Sans notice correspondante, celle d'un autre véhicule
  n'est jamais montrée : écran fixe et consignes de sécurité.
- Le chantier d'analyse visuelle complète reste clos.
- Hors critère 5 : un échec d'identification VIR (identifiant invalide, pays non pris en charge, fournisseur
  indisponible) n'atteint pas PGDR ; il reste traité par l'identification VIR.

## 7. Configuration serveur

- `PGDR_V1_MANIFEST` : la notice fournie par le montage (absente : parcours sans notice).
- `PGDR_V1_GROUPS`, `PGDR_V1_EXPLANATIONS`, `PGDR_V1_SITUATIONS`, `PGDR_V1_TRANSLATIONS`, `PGDR_V1_LABELS`,
  `PGDR_V1_FINDINGS`, `PGDR_V1_APPLICABILITE`, `PGDR_V1_RATTACHEMENT` : facultatifs, fichiers validés hors dépôt.
- Jamais en production : `PGDR_V1_TRI`, `PGDR_V1_TRI_FAUX`, `PGDR_V1_ESSAI_TRI`, `PGDR_V1_DEV_TRIAL`,
  `PGDR_V1_DEV_VEHICLE` (refusés par `lancer_montage.sh` en mode production), ni `PI_DIALOGUE_HISTORIQUE` ou
  `VITE_PI_DIALOGUE_HISTORIQUE` (sans effet sur le point d'entrée de production).
- Le reste : guide PI `docs/GUIDE_MISE_EN_LIGNE.md`.

## 8. Critères échoués

Aucun. Les critères 5 et 6 ont été corrigés dans cette passe.

Les textes du parcours sans notice et le contexte de son écran de sécurité sont finalisés (`55f76ae`). Il n'est
ajouté aucun choix pour départager les groupes ambigus ; la route `/media` (dépôt de photo de l'ancien chemin,
inutilisé par le frontend) est laissée telle quelle.

L'installation et la réception finales sur le serveur sont distinctes de cette clôture.
