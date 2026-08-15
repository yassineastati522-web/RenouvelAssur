# Sauvegarde et restauration Neon/PostgreSQL

Cette procédure évite de considérer le déploiement Render ou l’historique Git comme une sauvegarde des données. Les fichiers produits contiennent des données personnelles : ils doivent être chiffrés, accessibles uniquement aux personnes autorisées et ne doivent jamais être ajoutés au dépôt Git.

## Fréquence retenue

- sauvegarde logique quotidienne de la base de production ;
- conservation selon la politique validée par l’agence ;
- test de restauration au moins une fois par trimestre et avant une migration importante ;
- vérification régulière des fonctions de restauration réellement incluses dans l’abonnement Neon actif.

## Sauvegarde quotidienne automatisée

Le dépôt contient un job Render dans `render.yaml` et son programme dans
`ops/backup/`. Il s’exécute chaque jour à **02:00 UTC** et réalise les opérations
suivantes :

1. création d’un `pg_dump` PostgreSQL au format personnalisé ;
2. contrôle de l’archive avec `pg_restore --list` ;
3. chiffrement local AES-256 avec GnuPG ;
4. second contrôle après déchiffrement en mémoire ;
5. calcul d’une empreinte SHA-256 ;
6. envoi de l’archive chiffrée et de son empreinte vers un stockage compatible
   S3 ;
7. suppression automatique des fichiers temporaires lorsque le job se termine.

Le job ne crée pas le compartiment de stockage et ne supprime aucune ancienne
sauvegarde. Le compartiment doit être créé séparément avec accès public bloqué,
versionnement activé et une règle de conservation validée par l’agence/CNDP.

### Secrets à renseigner dans le job Render `renouvelassur-backup`

| Variable | Valeur attendue |
|---|---|
| `BACKUP_DATABASE_URL` | URL **directe et non poolée** de Neon avec `sslmode=require` |
| `BACKUP_ENCRYPTION_PASSPHRASE` | phrase secrète longue et aléatoire, conservée aussi dans le gestionnaire de mots de passe de l’agence |
| `S3_BUCKET_NAME` | nom du compartiment privé |
| `AWS_ACCESS_KEY_ID` | identifiant technique limité à l’écriture et à la lecture des sauvegardes |
| `AWS_SECRET_ACCESS_KEY` | secret du compte technique |
| `AWS_REGION` | région du stockage |
| `S3_ENDPOINT_URL` | vide pour AWS S3, URL du fournisseur pour un stockage compatible S3 |

Les variables marquées `sync: false` dans le Blueprint doivent être ajoutées
manuellement au nouveau job depuis Render. Elles ne doivent jamais être copiées
dans GitHub. Après configuration, lancer **Trigger Run**, vérifier que le job se
termine avec succès, puis contrôler la présence des deux objets `.dump.gpg` et
`.sha256` dans le compartiment.

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

La commande manuelle reste une solution de secours. En fonctionnement normal,
le job Render décrit ci-dessus doit produire la sauvegarde quotidienne.

## Tester réellement une restauration

1. Créer dans Neon une branche ou une base isolée dédiée au test. Ne jamais restaurer directement par-dessus la production.
2. Copier sa chaîne de connexion SSL dans `RESTORE_DATABASE_URL`.
3. Télécharger l’archive et son empreinte, vérifier l’empreinte puis déchiffrer
   le dump avec la phrase secrète conservée hors de Render.
4. Restaurer le dump puis exécuter les contrôles Django.

```powershell
$encryptedBackupFile = "C:\sauvegardes\renouvelassur-AAAAmmJJTHHMMSSZ.dump.gpg"
$checksumFile = "$encryptedBackupFile.sha256"
$decryptedBackupFile = "$encryptedBackupFile.dump"
$expectedHash = (Get-Content $checksumFile).Split(" ")[0]
$actualHash = (Get-FileHash -Algorithm SHA256 $encryptedBackupFile).Hash.ToLower()
if ($actualHash -ne $expectedHash.ToLower()) { throw "Empreinte invalide" }
gpg --output $decryptedBackupFile --decrypt $encryptedBackupFile
pg_restore --list $decryptedBackupFile | Select-Object -First 20

$env:RESTORE_DATABASE_URL = "postgresql://.../restore_test?sslmode=require"
pg_restore --clean --if-exists --no-owner --no-privileges --dbname $env:RESTORE_DATABASE_URL $decryptedBackupFile
$env:DATABASE_URL = $env:RESTORE_DATABASE_URL
python manage.py check
python manage.py migrate --check
python manage.py shell -c "from renewals.models import Client, Contract, ImportBatch; print({'clients': Client.objects.count(), 'contrats': Contract.objects.count(), 'imports': ImportBatch.objects.count()})"
```

Comparer ces totaux avec ceux enregistrés au moment de la sauvegarde, ouvrir plusieurs fiches dans une instance de test puis supprimer la base ou la branche de restauration. Consigner la date, l’opérateur, le fichier testé, le résultat et les éventuels écarts, sans copier de données client dans le compte-rendu.

## En cas d’incident

Couper les imports et modifications, conserver les journaux, déterminer le dernier point sain, restaurer d’abord dans un environnement isolé, valider les données puis planifier la remise en production. Changer les identifiants de base s’ils ont pu être exposés.
