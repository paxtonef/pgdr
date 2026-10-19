# Provenance de l'identité et applicabilité de la notice (V1)

**Statut : implémenté** (branche `v1-fiat-provenance`, depuis `v1-3b-reception` @ `1c5a5cc`). Sans contenu
constructeur : aucun identifiant, titre ni texte de notice réelle, aucun VIN, aucune plaque, aucune donnée de
certificat d'immatriculation.

Ce document complète `CONTRAT_VIR_PGDR.md` (proposition non validée) sur deux points : la provenance de chaque
champ et la décision d'applicabilité. Il ne valide pas le reste de cette proposition.

## 1. Contrat d'entrée : `VehicleIdentityContext`

| Champ | Sens |
|---|---|
| `vehicle_identity` | Valeurs **admissibles selon les règles existantes** (bloc 3A). Jamais une valeur qui repose sur la seule confirmation du conducteur. Tous les consommateurs existants (Photo-First, session, SafetyEngine, R-5, tri) lisent ce qu'ils lisaient avant. |
| `unresolved_fields`, `contradictions` | Inchangés. Un champ confirmé seulement y figure comme non résolu, comme avant. |
| `field_provenance` (nouveau) | Par champ : `status`, `value`, `sources`. Le statut est **celui de VIR** (`vir.domain.driver_confirmation.epistemic_status`) ; PGDR ne le calcule jamais. |
| `vehicle_ref` (nouveau) | Référence opaque du véhicule dans le produit (l'actif CPL), jamais un VIN ni une plaque. Ne sert qu'à trouver une attestation limitée à ce véhicule. |

Statuts de `field_provenance` :

| Statut | Sens | Libellé affiché |
|---|---|---|
| `established` | décodage ou source qualifiée (règles de VIR) | établi (décodage ou source qualifiée) |
| `user_confirmed` | confirmé par le conducteur ; méthode `user_confirmation`, source `driver_confirmation` | confirmé par le conducteur, sans vérification indépendante |
| `user_declared` | saisi par le conducteur, non vérifié | déclaré par le conducteur, non vérifié |
| `provider_not_established` | fourni par une source sans l'établir | fourni par une source, non établi |
| `unknown` | aucune valeur | inconnu |
| `contradictory` | champ listé dans les contradictions de VIR | contradictoire |
| (aucune entrée) | producteur antérieur, résolution sans preuve de provenance | provenance non transmise |

Garanties vérifiées à la réception (`pgdr.models`) :

- un `user_confirmed` porte une valeur et la confirmation du conducteur parmi ses sources ;
- un `established` dont toutes les sources sont des confirmations est refusé ;
- un `unknown` ne porte aucune valeur ;
- une valeur `user_confirmed` présente dans `vehicle_identity` fait refuser le transfert entier.

Un contexte sans `field_provenance` se lit comme avant et ne gagne aucune qualification. Le score de
confiance est transmis tel que VIR le donne, jamais relevé. `exact_factory_configuration_known` n'est ni
transmis ni redéfini.

## 2. Applicabilité : quatre questions distinctes (`pgdr.v1_applicabilite`)

Clés comparées : celles sur lesquelles la notice est résolue, `manufacturer`, `model` et `generation`
(`APPLICABILITY_IDENTITY_FIELDS`). Aucune autre clé n'est ajoutée. Le marché de la notice, non vérifié,
n'est pas un critère.

1. **Valeur disponible et provenance.** Pour chaque clé : la valeur et le statut de VIR. Une valeur
   confirmée vient seulement de `field_provenance`.
2. **Critère suffisamment justifié.** Une attestation nomme, pour chaque critère, où il a été lu sur la
   notice et sur le véhicule.
   - Côté notice : seul le texte imprimé (`printed_notice`) justifie un critère. Le nom du fichier, l'adresse
     de téléchargement et les métadonnées du PDF ne le justifient pas.
   - Côté véhicule : le certificat d'immatriculation, l'étiquette ou plaque du constructeur, ou une valeur
     établie par VIR. Une confirmation du conducteur seule ne suffit pas. Le certificat ne porte pas
     nécessairement de rubrique « génération ».
3. **Correspondance véhicule/notice.** Égalité exacte ; seules la casse et les espaces de bord sont ignorés.
   Aucune correspondance approchée, aucun alias, rien de déduit (ni du modèle, ni de l'année, ni d'une
   « série », ni d'un nom de fichier).
4. **Décision.** La notice est applicable dans l'un de ces trois cas, et seulement dans ceux-là :
   - une attestation valide couvre **ce véhicule** (`vehicle_ref`) et **cette version** de la notice
     (`document_id` et empreinte du contenu), avec des critères égaux à la fois à ceux de la notice et aux
     valeurs transmises ;
   - l'applicabilité est établie par la revue de la notice (`applicability_vehicle_under_review`, bloc 3A),
     **à condition qu'aucune clé ne repose sur la seule confirmation du conducteur** ;
   - l'essai de développement (`PGDR_V1_DEV_TRIAL=1`), avec bandeau permanent, jamais en production.

### Ordre des refus et motifs

Chaque refus porte `status`, `message` (inchangé depuis le bloc 3A), `reasons` (motifs précis), `to_verify`,
`next_action` et `identity` (les clés comparées, avec leur provenance).

| Cas | Statut | Motif |
|---|---|---|
| Notice absente ou refusée | `notice_unavailable` | — |
| Statut VIR autre que `resolved` / `provisionally_resolved` | `vehicle_identity_insufficient` | aucune identité choisie par défaut |
| Clé contradictoire | `vehicle_identity_insufficient` | « … est contradictoire entre les sources de VIR : rien n'est tranché » ; rien n'ouvre, ni attestation ni essai |
| Clé inconnue | `vehicle_identity_insufficient` | « La génération du véhicule n'est pas connue … » |
| Valeur différente de la notice | `vehicle_not_supported` | les deux valeurs, « comparaison exacte, sans correspondance approchée ni alias » |
| Période déclarée, production non établie ou hors période | `vehicle_identity_insufficient` / `vehicle_not_supported` | inchangé (bloc 3A) |
| Clé confirmée seulement, sans attestation | `applicability_not_confirmed` | « … repose sur la seule confirmation du conducteur : cela ne suffit pas … » |
| Aucune attestation pour ce véhicule, ou attestation pour une autre version ou une autre notice | `applicability_not_confirmed` | motif précis ; une attestation d'un autre véhicule n'est jamais décrite |

La prochaine action indiquée ne demande jamais de refaire les contenus déjà validés de la notice.

## 3. Attestation d'applicabilité (`PGDR_V1_APPLICABILITE`)

Le fichier est hors dépôt, préparé par le propriétaire de la notice ; PGDR ne l'écrit jamais. Son format est
décrit dans le module `pgdr.v1_applicabilite`.

- **Champs exigés :** `status: VALIDE`, `attested_by`, `verified_on` (date passée ou du jour), `document_id`,
  `catalogue_content_sha256`, `vehicle_ref`, et un critère par clé (valeur, `notice_source`,
  `vehicle_source`).
- **Rejet :** une attestation incomplète, non justifiée ou portant un critère inconnu est écartée avec son
  motif, sans empêcher les autres.
- **Portée :** une attestation n'est jamais reportée sur une autre version de la notice, même par un
  rattachement.
- **Vérification :** `python -m pgdr.v1_applicabilite verifier <attestations.yaml> <manifest.yaml>` indique,
  pour chaque attestation, si elle est recevable pour cette version. La commande n'écrit rien.

## 4. Rattachement des validations (`PGDR_V1_RATTACHEMENT`, `pgdr.v1_rattachement`)

L'empreinte du contenu couvre tout le manifeste sauf la revue, y compris les métadonnées d'applicabilité.
Modifier ces métadonnées change donc l'empreinte sous la revue et sous les fichiers validés, alors qu'aucun
contenu validé n'a changé.

**Le rattachement est une décision nouvelle du propriétaire qui couvre seulement les éléments différents.**

- **Validations conservées :** les anciennes validations restent telles quelles, liées à l'ancienne
  empreinte. Aucune signature n'est réécrite, aucune nouvelle empreinte n'est placée sous une ancienne
  attestation.
- **Preuve :** PGDR remet les anciennes valeurs des champs listés dans le manifeste actuel et doit retrouver
  l'ancienne empreinte. Cela prouve que la liste des différences est exacte et que tous les autres champs, y
  compris tous les contenus validés, sont inchangés.
- **Seules des métadonnées d'applicabilité peuvent différer :** `applicability_vehicle_under_review` et
  `applicability_period_*`. Toute autre différence est une modification de contenu ; elle invalide la
  validation concernée et aucun rattachement n'est possible.
- **Champs refusés :** un champ listé mais inchangé, ou modifié mais non listé.
- **Effet :** la revue et les fichiers validés liés à l'ancienne empreinte restent recevables pour la
  nouvelle.
- **Commandes** (elles n'écrivent rien) : `python -m pgdr.v1_rattachement proposer <ancien> <actuel>` produit
  une **proposition**, jamais validée ; `python -m pgdr.v1_rattachement verifier <rattachement> <manifeste>`
  donne le verdict.

Une attestation d'applicabilité séparée ne modifie pas le manifeste. Elle ne demande donc ni rattachement,
ni nouvelle revue, ni revalidation des contenus.

## 5. Limites

- Un essai sur données fictives prouve le raccordement technique, pas l'applicabilité réelle d'une notice.
- `vehicle_ref` désigne l'actif du produit : un nouveau dossier ouvert sur un nouvel actif demande sa propre
  attestation.
- Aucun fournisseur actuel ne donne de génération (constat VIR). Sans confirmation du conducteur et sans
  attestation, un parcours réel reste refusé avec son motif.
