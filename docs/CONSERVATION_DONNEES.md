# Politique de conservation des données

Ce document est une base opérationnelle à faire valider par le responsable de l’agence et, pour les obligations marocaines, par la CNDP ou un juriste compétent. Aucune suppression automatique des contrats ou des clients n’est activée tant que les durées légales et les besoins d’assurance ne sont pas confirmés.

| Données | Utilité | Durée proposée | Mise en œuvre actuelle |
|---|---|---:|---|
| Journal d’audit technique | sécurité, preuve d’action et investigation | 730 jours | configurable par `AUDIT_LOG_RETENTION_DAYS`; purge explicite avec `prune_audit_events --confirm` |
| Tentatives de connexion Axes | protection anti-bruteforce | durée minimale nécessaire au verrouillage et aux investigations | à revoir périodiquement dans l’administration |
| Historique des appels | organisation des relances et suivi du contrat | à valider avec l’agence/CNDP | aucune purge automatique |
| Rapports d’import | traçabilité de l’alimentation des données | à valider ; éviter une conservation inutile des erreurs anciennes | aucune purge automatique |
| Contrats, résiliations et provisoires | gestion du portefeuille et obligations d’assurance | durée légale/métier à confirmer | aucune purge automatique |
| Clients sans contrat utile | aucun usage opérationnel restant | suppression ou anonymisation après validation | action administrative contrôlée |
| Sauvegardes | reprise après incident | définir plusieurs points récents et une échéance maximale | procédure séparée de sauvegarde/restauration |

## Principes obligatoires

- Ne conserver que les données nécessaires à la gestion des contrats et des appels.
- Ne pas saisir de données sensibles ou de commentaires excessifs dans les champs libres.
- Limiter l’accès aux administrateurs et agents ayant un besoin opérationnel.
- Journaliser les actions sensibles sans recopier les noms, téléphones, polices ou commentaires dans le journal technique.
- Documenter toute suppression importante et vérifier auparavant l’existence d’une sauvegarde restaurable.
- Réviser cette politique lors d’un changement d’hébergeur, d’abonnement Neon, de finalité ou de clientèle.

## Exécution de la purge du journal d’audit

Simulation avec la durée configurée :

```powershell
python manage.py prune_audit_events
```

Suppression confirmée :

```powershell
python manage.py prune_audit_events --confirm
```

Une durée ponctuelle peut être précisée avec `--days`, sans pouvoir descendre sous 30 jours. La commande ne supprime ni contrats, ni clients, ni appels, ni imports.
