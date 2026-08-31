# Checklist de mise en production

Cette liste sépare ce qui est assuré par le code des opérations qui nécessitent
un accès aux comptes de l’agence. Une opération externe n’est considérée comme
terminée qu’après contrôle dans le fournisseur concerné.

## Application et sécurité

- [x] HTTPS forcé, cookies sécurisés, HSTS et CSP configurés en production.
- [x] rôles Agent/Administrateur, limitation anti-bruteforce et journal d’audit.
- [x] déconnexion automatique à minuit selon `Africa/Casablanca`.
- [x] imports contrôlés, permissions par agent et exports protégés contre les
  formules Excel.
- [x] export des non-renouvelés limité à sept jours et désormais journalisé.
- [x] tests, contrôle des migrations, audit des dépendances, Bandit et Semgrep
  exécutés par GitHub Actions.
- [ ] confirmer `SENTRY_DSN` dans Render si l’agence retient Sentry comme
  prestataire de surveillance.

## Sauvegardes

- [x] programme de sauvegarde quotidienne chiffrée et vérifiée présent dans le
  dépôt.
- [x] Cron Job déclaré dans `render.yaml` à 02:00 UTC.
- [ ] créer le compartiment S3 privé dans un pays validé par l’agence/CNDP.
- [ ] renseigner les six secrets du job `renouvelassur-backup` dans Render.
- [ ] déclencher une première exécution et vérifier l’archive et son empreinte.
- [ ] effectuer et consigner une restauration complète dans une branche Neon
  isolée.
- [ ] valider la durée de conservation puis activer la règle de cycle de vie du
  compartiment.

## Domaine

- [x] l’application connaît le domaine principal `app.renouvelassur.org`.
- [x] redirection applicative de `renouvelassur.org` et `www` vers `app` prête.
- [ ] ajouter ces deux domaines au service Render et remplacer la page de
  parking par les enregistrements DNS fournis par Render.
- [ ] contrôler les trois certificats HTTPS après propagation DNS.

## Organisation et conformité

- [ ] faire valider les durées de conservation des contrats, appels, imports et
  sauvegardes avant d’activer leur suppression automatique.
- [ ] compléter le dossier CNDP et les informations sur les pays, sous-traitants
  et transferts de Render, Neon, Sentry et du stockage de sauvegarde.
- [ ] désigner les personnes responsables des incidents, sauvegardes et tests
  trimestriels de restauration.
- [ ] définir et valider l’objectif de perte maximale de données (RPO) et le
  délai de reprise (RTO).
