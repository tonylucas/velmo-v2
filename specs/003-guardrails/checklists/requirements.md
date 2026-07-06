# Specification Quality Checklist: Garde-fous d'entrée et de sortie (003-guardrails)

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-01
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Tous les items passent. Les 5 scénarios couvrent les tests d'acceptance du brief : blocage
  entrée (haine/violence/sexuel + escalade), blocage sortie (PII/secrets/hors-périmètre),
  résistance aux injections, faux positifs sous le seuil, journalisation + escalade.
- Conformément aux guidelines "no HOW in spec", le choix des méthodes de détection (regex,
  classifieur, modération LLM, vérification de périmètre) est explicitement renvoyé à
  `/speckit-plan` et au tableau des garde-fous du dossier de conception. La spec ne fixe que
  l'emplacement (entrée/sortie), l'action (refus/journalisation/escalade) et les seuils.
- Le seuil de faux positifs n'est pas chiffré ici : il est défini et versionné au chantier 3
  (`mlops/report.md`), conformément au Principe IV de la constitution. SC-004 exige seulement
  qu'un seuil existe et soit respecté — mesurable une fois le seuil fixé.
- Points volontairement laissés en hypothèses affinables (candidats à `/speckit-clarify`) :
  politique fail-open/fail-closed par catégorie, traitement d'une PII fournie spontanément en
  entrée, régénération vs refus générique quand la sortie est bloquée.
- Prêt pour `/speckit-clarify` (recommandé vu les hypothèses ouvertes) ou `/speckit-plan`.
