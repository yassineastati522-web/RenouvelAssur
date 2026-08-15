# Plan de réponse aux incidents

Ce plan est volontairement opérationnel. Il doit être complété avec les noms et numéros réels avant l’ouverture aux utilisateurs.

## Responsabilités à renseigner

| Rôle | Titulaire | Contact | Remplaçant |
|---|---|---|---|
| Décision et coordination | À renseigner | À renseigner | À renseigner |
| Administration Render | À renseigner | À renseigner | À renseigner |
| Administration Neon | À renseigner | À renseigner | À renseigner |
| Relation CNDP / conseil juridique | À renseigner | À renseigner | À renseigner |
| Information des utilisateurs | À renseigner | À renseigner | À renseigner |

## 1. Détecter et qualifier

1. Noter l’heure, la personne qui a détecté l’événement et les symptômes.
2. Consulter les événements Sentry, les journaux Render, le journal d’audit et l’état Neon sans copier de données client dans un ticket ou une messagerie.
3. Classer provisoirement l’incident : indisponibilité, compte compromis, fuite suspectée, import erroné, suppression ou altération de données.
4. Estimer les comptes, données et périodes potentiellement concernés. Ne pas conclure trop tôt qu’aucune donnée n’a été exposée.

## 2. Contenir sans détruire les preuves

- Compte suspect : le désactiver dans l’administration, révoquer ses sessions et réinitialiser sa MFA.
- Secret suspect : le remplacer dans Render ou Neon, puis redéployer. Ne jamais copier sa valeur dans le journal d’incident.
- Import problématique : suspendre les nouveaux imports et conserver le rapport d’import; ne pas supprimer immédiatement les lignes utiles à l’analyse.
- Vulnérabilité applicative : limiter temporairement l’accès au service ou désactiver la fonction concernée, puis conserver le commit et les journaux associés.
- Base compromise : révoquer les identifiants PostgreSQL, créer de nouveaux identifiants et vérifier les accès avant la remise en service.

Les journaux utiles doivent être exportés vers un emplacement réservé aux personnes autorisées. Leur export contient des identifiants de comptes et doit être protégé comme une donnée personnelle.

## 3. Corriger et restaurer

1. Identifier la cause technique et la période exacte.
2. Corriger sur une branche, faire relire le changement et exécuter les tests avant déploiement.
3. En cas de restauration, suivre `SAUVEGARDE_RESTAURATION.md`, restaurer d’abord dans une base isolée et vérifier les comptes, contrats, résiliations, imports et audits.
4. Forcer le changement de mot de passe ou la réinitialisation MFA des comptes réellement exposés.
5. Vérifier `/health/`, la connexion, l’import d’un fichier de test et les pages principales.

Objectifs techniques proposés après activation et test du job quotidien : perte
de données maximale acceptable (RPO) : **24 heures** pour la sauvegarde
indépendante ; délai maximal de reprise (RTO) : **4 heures ouvrées**. Ces valeurs
doivent être validées par l’agence et révisées si l’activité exige une reprise
plus rapide.

## 4. Décider des notifications

Le responsable de traitement et son conseil doivent évaluer rapidement les obligations envers les personnes concernées, la CNDP, l’assureur, Render, Neon et les autres parties contractuelles. Documenter la décision, même lorsqu’aucune notification n’est retenue. Cette étape ne doit pas être remplacée par une décision technique.

## 5. Clôturer

- Produire une chronologie, la cause, les données touchées, les mesures prises et les actions restantes.
- Supprimer des espaces temporaires les exports créés pour l’enquête, selon une date de suppression consignée.
- Ajouter un test empêchant la régression et mettre à jour les procédures.
- Organiser un retour d’expérience court avec les responsables concernés.

## Fiche d’incident minimale

```text
Référence :
Début détecté / fin estimée :
Détecteur :
Qualification :
Services concernés :
Catégories de données potentiellement concernées :
Nombre approximatif de personnes :
Mesures de confinement :
Preuves conservées et emplacement :
Cause confirmée :
Correction / restauration :
Décision de notification et validateur :
Actions préventives, responsables et échéances :
```
