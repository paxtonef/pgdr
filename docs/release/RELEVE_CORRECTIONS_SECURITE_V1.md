# Relevé des corrections de sécurité V1 (branche v1-premier-constat)

Autorisation : modification de SafetyEngine, R-5 et `safety_rules.yaml` limitée à trois corrections
(C1 conditions d'application dans R-5, C2 règle PGDR-SAF-012, C3 consignes constructeur vérifiées séparées
des classements de présentation) et aux champs nécessaires à leur raccordement. Aucun contenu de notice
réelle dans ce relevé ni dans les tests (notice fictive uniquement).

## Défauts reproduits avant correction (commit 6f0130f)

| Défaut | Constat sur la notice fictive |
|---|---|
| D1 | Un voyant rouge « frein de stationnement serré », variante établie, recevait `do_not_drive` par PGDR-SAF-012 (mot « brake » du titre commun). |
| D2 | Un arrêt dont la condition était inconnue donnait le même résultat interne qu'une situation ordinaire à surveiller. |
| D3 | La consigne d'arrêt vérifiée du manque de liquide n'atteignait R-5 qu'à travers un classement Premier Constat validé. |
| D4 | Une condition confirmée était convertie en remplaçant le champ `stop_vehicle_engine_off`, sans règle R-5 propre. |

Ces cas de reproduction sont devenus les tests du comportement corrigé (colonne « Test »).

## Modifications

| Fichier | Fonction / règle / champ | Correction | Test |
|---|---|---|---|
| `src/pgdr/models.py` | `ConditionStatus` (confirmed / excluded / unknown), `ConditionalStop`, `EntryFinding.conditional_stops` | C1 (données) | `test_v1_traitement_interne.py::TestConditionOfApplication` |
| `src/pgdr/models.py` | `SafetyTriage.safety_status`, `SafetyTriage.safety_uncertainties` (statut explicite d'incertitude, sans nouveau sens donné à un niveau existant) | C1 | `test_unknown_is_an_explicit_uncertainty_distinct_from_ordinary` |
| `src/pgdr/models.py` | `WarningIndicator.situation_fact`, `SafetyTriage.rule_exclusions` | C2 (raccordement, traçabilité) | `test_safety_engine_situation_facts.py`, `TestBrakeRule` |
| `src/pgdr/application/part1_first_finding.py` | `r5_rows` : ligne `R-5:conditional_stop_confirmed` (même traitement qu'un arrêt documenté) | C1 | `test_confirmed_applies_with_its_rule_condition_and_source`, `test_low_fluid_with_applicable_instruction_kept` |
| `src/pgdr/application/part1_first_finding.py` | `r5_uncertainties` (condition inconnue ; exclue sur interprétation non validée ; variante non départagée), `compose_triage` (statut d'incertitude, niveau non modifié), `UNRESOLVED_VARIANT`, `raised_instructions` | C1 | `test_no_answer_equals_unknown`, `test_excluded_on_unvalidated_interpretation_stays_uncertain`, `test_excluded_on_validated_preparation_does_not_raise_but_stays_consultable`, `test_undetermined_group_keeps_critical_possibility_without_confirming` |
| `src/pgdr/safety_engine.py` | `evaluate`, `_apply`, `_established_exclusions`, `_texts_of`, `_matches(indicators=…)` : clé de condition `exclude_established_situations` | C2 | `test_saf012_exclusion_requires_established_fact`, `test_other_red_brake_indicator_still_triggers`, `test_free_text_still_triggers` |
| `src/pgdr/config/safety_rules.yaml` | PGDR-SAF-012 : `exclude_established_situations: ["fonctionnement_normal"]` (fait structuré avec provenance, variante sélectionnée ; sans fait, règle inchangée) | C2 | `test_parking_brake_applied_established_no_do_not_drive`, `test_insufficient_information_no_silent_downgrade` |
| `src/pgdr/config_loader.py` | `validate_safety_rules` : validation de la nouvelle clé | C2 | `test_exclusion_key_validated` |
| `src/pgdr/v1_contenu.py` | `catalogue_stops`, `stop_key`, `stop_condition`, `Situation.conditions_validated` (approbation séparée « structured_consignes »), `red_offer` | C3 / C1 (raccordement) | `TestManufacturerInstructionAlone`, `test_exact_citation_does_not_validate_an_interpretation` |
| `src/pgdr/v1_parcours.py` | `attach_conditional_stops`, `situation_fact`, `premier_constat` (faits, arrêts, statut transmis au résultat), `_level_origin`, `/condition` (clés des arrêts du texte constructeur), affichage des arrêts confirmés en tête | C1 / C2 / C3 (raccordement) | `test_v1_browser_e2e.py::test_v1_restart_procedure_expected_action_and_take_into_account`, `TestConditionOfApplication`, `TestKept` |
| `tests/v1_fictive_notice.py` | `build_situations(consignes_validated_by=…)` | tests | — |

Non-régression direction (procédure d'arrêt temporaire, attente puis redémarrage) :
`TestRestartProcedure::test_procedure_never_an_emergency_nor_a_permission`,
`test_procedure_recorded_as_immediate_stop_is_reported_not_altered`.
Autres comportements conservés : `TestKept` (autre alerte et sélection multiple, « stop lights »,
repli pour voyant rouge non identifié).

## Règles de comportement

- Condition confirmée par le conducteur : ligne R-5 `conditional_stop_confirmed` (arrêt d'urgence, ne pas rouler).
- Condition exclue : aucune ligne ; si l'association condition/consigne vient d'une préparation validée, aucune
  incertitude, sinon incertitude « condition_exclue_interpretation_non_validee ». La consigne reste consultable.
- Condition inconnue ou sans réponse : incertitude « condition_inconnue », `safety_status = "uncertain"`, niveau
  inchangé, aucune autorisation de rouler (aucune valeur de ce type n'existe dans `DrivingAssessment`).
- PGDR-SAF-012 : écartée seulement pour un indicateur dont la situation est établie comme indication normale par un
  classement validé, variante sélectionnée par le conducteur, et seulement si le mot-clé ne vient pas du texte libre
  du conducteur. L'exclusion est inscrite dans `rule_exclusions`.

## Hors périmètre

Aucune modification hors des trois corrections et de leur raccordement.
