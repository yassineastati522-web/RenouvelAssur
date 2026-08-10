# Sauvegarde et restauration Neon/PostgreSQL

Cette procédure évite de considérer le déploiement Render ou l’historique Git comme une sauvegarde des données. Les fichiers produits contiennent des données personnelles : ils doivent être chiffrés, accessibles uniquement aux personnes autorisées et ne doivent jamais être ajoutés au dépôt Git.

## Fréquence retenue

- sauvegarde logique quotidienne de la base de production ;
- conservation selon la politique validée par l’agence ;
- test de restauration au moins une fois par trimestre et avant une migration importante ;
- vérification régulière des fonctions de restauration réellement incluses dans l’abonnement Neon actif.

## Préparer le poste d’administration

Installer les outils PostgreSQL de la même version majeure que le serveur ou d’une version plus récente. Définir `DATABASE_URL` uniquement dans la session de terminal utilisée et ne jamais l’écrire dans un script, un document ou l’historique Git.

```powershell
$env:DATABASE_URL = "postgresql://.../neondb?sslmode=require"
$backupDirectory = Join-Path $PWD "backups"
New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
$backupFile = Join-Path $backupDirectory ("renouvelassur-{0}.dump" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
pg_dump --format=custom --no-owner --no-privileges --file $backupFile $env:DATABASE_URL
pg_restore --list $backupFile | Select-Object -First 20
```

Après le contrôle, chiffrer le fichier avec l’outil approuvé par l’agence, le transférer vers le stockage de sauvegarde prévu puis supprimer la copie locale temporaire de manière maîtrisée. Ne pas utiliser le disque éphémère du service Render comme destination.

## Tester réellement une restauration

1. Créer dans Neon une branche ou une base isolée dédiée au test. Ne jamais restaurer directement par-dessus la production.
2. Copier sa chaîne de connexion SSL dans `RESTORE_DATABASE_URL`.
3. Restaurer le dump puis exécuter les contrôles Django.

```powershell
$env:RESTORE_DATABASE_URL = "postgresql://.../restore_test?sslmode=require"
pg_restore --clean --if-exists --no-owner --no-privileges --dbname $env:RESTORE_DATABASE_URL $backupFile
$env:DATABASE_URL = $env:RESTORE_DATABASE_URL
python manage.py check
python manage.py migrate --check
python manage.py shell -c "from renewals.models import Client, Contract, ImportBatch; print({'clients': Client.objects.count(), 'contrats': Contract.objects.count(), 'imports': ImportBatch.objects.count()})"
```

Comparer ces totaux avec ceux enregistrés au moment de la sauvegarde, ouvrir plusieurs fiches dans une instance de test puis supprimer la base ou la branche de restauration. Consigner la date, l’opérateur, le fichier testé, le résultat et les éventuels écarts, sans copier de données client dans le compte-rendu.

## En cas d’incident

Couper les imports et modifications, conserver les journaux, déterminer le dernier point sain, restaurer d’abord dans un environnement isolé, valider les données puis planifier la remise en production. Changer les identifiants de base s’ils ont pu être exposés.
