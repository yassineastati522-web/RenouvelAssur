# RenouvelAssur

MVP de suivi des renouvellements de contrats pour une agence d’assurance. L’application est en français, responsive et fonctionne avec SQLite en local ou PostgreSQL en production.

## Fonctionnalités

- authentification sécurisée, mots de passe d’au moins 12 caractères, rotation obligatoire des comptes existants, rôles Administrateur / Agent, conservation des échecs de connexion, blocage de 15 minutes après huit échecs et déconnexion automatique à minuit ;
- double authentification TOTP obligatoire pour les administrateurs en production, avec huit codes de secours à usage unique ;
- journal d’audit des connexions, imports, changements sensibles et suppressions, sans nom, téléphone, police ni commentaire client dans ses métadonnées ;
- révocation manuelle des sessions, réinitialisation MFA et export CSV protégé du journal depuis l’administration ;
- alertes de sécurité et surveillance Sentry facultative avec suppression du corps des requêtes, cookies, paramètres, identité et en-têtes sensibles ;
- tableau de bord : échéances, relances, renouvellements et primes ;
- import des échéances à venir, des bordereaux Excel et du suivi CSV/Excel des provisoires avec détection automatique du format, de la feuille et de la ligne d’en-têtes ;
- reconnaissance des colonnes du bordereau assureur, validation, mise à jour idempotente et rapport d’erreurs ;
- liste des contrats avec périodes relatives −15, −7, +7 et +15 jours, et statuts renouvelé / non renouvelé ;
- fiche contrat avec trois résultats d’appel : Client appelé, Boîte vocale et Non joignable ;
- checklist des clients à appeler avec échéance minimale, filtres À appeler / Traités / Indisponibles, identification des provisoires et enregistrement rapide du résultat ;
- statut de renouvellement géré séparément du résultat d’appel ;
- historique complet, non destructif et paginé des interactions ;
- fiches clients, téléphone modifiable et portefeuille associé ;
- contrats expirés sans renouvellement et résiliations ; un nouveau contrat portant la même immatriculation marque automatiquement l’ancien comme renouvelé ;
- suggestion « Injoignable » après trois tentatives infructueuses sur des jours distincts ;
- administration des utilisateurs et attributions via `/admin/`.

## Installation locale

Prérequis : Python 3.12 ou 3.13.

```powershell
cd outputs\assurance_renewal
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.lock
python manage.py migrate
python manage.py seed_demo --admin-password "mot-de-passe-local" --agent-password "mot-de-passe-local"
python manage.py runserver
```

Ouvrir `http://127.0.0.1:8000/`.

La commande `seed_demo` est réservée au développement (`DJANGO_DEBUG=1`), exige des mots de passe explicites et refuse de s’exécuter en production.

## Import des fichiers

La page d’importation et les rapports sont accessibles aux administrateurs et aux agents authentifiés. Chaque import conserve l’utilisateur qui l’a effectué.

Les fichiers `.xlsx` et les fichiers `.xls` fournis par l’assureur sont acceptés. La case « Suivi des provisoires » accepte aussi le CSV exporté par l’assureur. Le système inspecte les premières lignes afin de trouver automatiquement le tableau principal et son type.

Trois formats métier sont reconnus :

- le fichier des échéances à venir (`cat`, `numero_police`, `assure`, `date_debut`, `date_fin`, `marque`, `immatriculation`, etc.) alimente la liste des appels ;
- le bordereau de production (`POLICE`, `Nature Evenement`, `PRIME_TOTAL`, `NUM_QUITTANCE`, etc.) complète les contrats avec les primes et les événements.
- le suivi des provisoires (`Police`, `N° Attestation`, `Date d’écheance`, `Provisoires délivrées`, `Date Effet`, `Date fin/ Echéance`, etc.) calcule le quota autorisé et alimente la prochaine action de la checklist.

La page d’importation présente une case dédiée à chaque format et refuse un fichier lorsqu’il est déposé dans la mauvaise case.

La taille est limitée à 10 Mo par défaut. L’extension ne suffit pas : la signature réelle du classeur est contrôlée, les archives Excel anormalement volumineuses sont refusées et une cellule texte ne peut pas dépasser la limite configurée.

Colonnes minimales : `Police`, `Client` ou `Assuré`, et `Date Échéance` ou `Date Fin`. Les en-têtes du bordereau fourni sont reconnus, notamment :

- `POLICE`, `Nature Evenement`, `CLIENT`, `NUMERO_CIN` ;
- `DATE_EFFET`, `DATE_ECHEANCE`, `DATE_EMISSION` ;
- `PRIME_TOTAL`, `PRIME_NET`, `NET_A_PAYE` ;
- `TELEPHONE`, `NUM_QUITTANCE`, `IMMATDEF`, `IMMAPRO`.

Les dates `JJ/MM/AAAA` et `AAAA-MM-JJ` sont acceptées. Les montants peuvent utiliser une virgule décimale. `IMMATDEF` est prioritaire sur `IMMAPRO`, avec repli automatique lorsque l’immatriculation définitive est vide. Les lignes de total du bordereau sont ignorées.

La combinaison `Police + Quittance` identifie un contrat. Pour le fichier d’échéances, `cat` et `numero_police` sont réunis automatiquement. Lorsque la même police et la même échéance sont retrouvées à un jour près, les deux sources sont fusionnées sans doublon. Les cellules vides ne remplacent jamais des informations déjà connues.

Pour le suivi provisoire, un contrat d’environ 3 mois autorise au maximum 1 provisoire, un contrat d’environ 6 mois en autorise 2 et un contrat annuel en autorise 3. Le client peut en choisir moins depuis sa fiche contrat, sans pouvoir descendre sous le nombre déjà délivré. Tant que le nombre choisi n’est pas atteint, la checklist affiche « Prochaine provisoire à remettre ». À la dernière provisoire retenue, elle affiche « Attestation définitive à remettre ». La date fournie dans le suivi reste la référence de la prochaine action.

Après chaque import, les contrats portant la même immatriculation sont comparés. Lorsqu’un contrat plus récent commence à la fin de l’ancien et possède une échéance ultérieure, l’ancien est relié au nouveau et n’apparaît plus parmi les contrats non renouvelés.

Un second fichier Excel ne contenant que `Téléphone` et un identifiant (`Police`, `CIN` ou `Client`) peut mettre à jour les contacts existants.

## Tests

```powershell
python manage.py test
python manage.py check --deploy
python -m pip_audit -r requirements.lock
```

GitHub Actions exécute automatiquement l’audit des dépendances, les analyses statiques Bandit et Semgrep, les contrôles Django, la vérification des migrations et les tests avec Python 3.13 sur chaque pull request et chaque envoi vers `main`.

## Dépendances

`requirements.txt` est la liste courte des dépendances directes. `requirements.lock` verrouille toutes les dépendances transitives et leurs empreintes SHA-256 ; Render installe ce verrou sans mettre `pip` à jour pendant chaque déploiement.

Pour mettre le verrou à jour volontairement :

```powershell
python -m pip install pip-tools==7.6.0
python -m piptools compile --generate-hashes --strip-extras --output-file requirements.lock requirements.txt
```

## PostgreSQL et production

Copier `.env.example` vers `.env`, charger les variables dans l’environnement et définir `POSTGRES_*`. En production, `DJANGO_SECRET_KEY` est obligatoire, `DJANGO_DEBUG=0` active HTTPS, HSTS, la protection anti-bruteforce, la politique CSP et l’interdiction de mise en cache des pages authentifiées. PostgreSQL refuse alors les modes SSL faibles et utilise au minimum `sslmode=require`. Une sauvegarde régulière de Neon reste nécessaire. Le fichier `.env` n’est jamais versionné.

En production, `DJANGO_ADMIN_MFA_REQUIRED=1` impose la double authentification aux administrateurs. À leur première connexion après déploiement, ils scannent un QR code avec une application TOTP et sauvegardent leurs codes de secours. Un administrateur peut ensuite révoquer les sessions ou réinitialiser la MFA d’un compte depuis la liste **Utilisateurs** de l’administration.

La surveillance d’erreurs est facultative. Pour l’activer, créer un projet Django dans Sentry puis ajouter `SENTRY_DSN` directement dans les variables secrètes de Render. Ne jamais écrire le DSN dans GitHub. `SENTRY_TRACES_SAMPLE_RATE=0` désactive par défaut le traçage de performance afin de minimiser les données envoyées.

Le Blueprint prépare également le Cron Job `renouvelassur-backup`. Ce job crée
chaque jour une sauvegarde PostgreSQL vérifiée, la chiffre avant transfert et
l’envoie vers un stockage S3 privé. Avant son premier lancement, renseigner dans
Render l’URL Neon directe, la phrase de chiffrement et les identifiants du
stockage indiqués dans `docs/SAUVEGARDE_RESTAURATION.md`. Le code source, Render
et l’historique Git ne remplacent pas cette sauvegarde indépendante.

Les procédures d’exploitation sont documentées dans :

- [`docs/SAUVEGARDE_RESTAURATION.md`](docs/SAUVEGARDE_RESTAURATION.md) pour créer, contrôler et restaurer une sauvegarde PostgreSQL/Neon ;
- [`docs/CONSERVATION_DONNEES.md`](docs/CONSERVATION_DONNEES.md) pour les durées de conservation à valider avec l’agence et son conseil CNDP.
- [`docs/PLAN_REPONSE_INCIDENTS.md`](docs/PLAN_REPONSE_INCIDENTS.md) pour détecter, contenir et traiter un incident sans effacer les preuves ;
- [`docs/DOSSIER_CNDP.md`](docs/DOSSIER_CNDP.md) pour réunir les informations techniques et contractuelles avant validation par la CNDP ou un juriste marocain.

Le journal d’audit est conservé 730 jours par défaut. Une simulation de purge est disponible avec `python manage.py prune_audit_events`; la suppression exige explicitement l’option `--confirm`.

## Déploiement sur Render avec Neon

Le fichier `render.yaml` et le script `build.sh` préparent automatiquement le service Django, les fichiers statiques et les migrations.

1. Dans Render, créer un **Blueprint** depuis le dépôt GitHub `yassineastati522-web/RenouvelAssur`.
2. Lorsque Render le demande, renseigner `DATABASE_URL` avec l’URL PostgreSQL fournie par Neon, comprenant `sslmode=require`.
3. Laisser Render générer `DJANGO_SECRET_KEY` et déployer la branche `main`.
4. Vérifier `https://<service>.onrender.com/health/`, puis se connecter avec le compte administrateur déjà présent dans Neon.
5. Le domaine `app.renouvelassur.org` et l’hôte exact `renouvelassur.onrender.com` sont déclarés dans `render.yaml`; adaptez ces deux listes si le nom du service change.
6. Ajouter aussi `renouvelassur.org` et `www.renouvelassur.org` comme domaines personnalisés du service, puis diriger leur DNS vers Render. L’application les redirige alors vers `https://app.renouvelassur.org` en conservant le chemin demandé.

Le plan gratuit est adapté à la validation uniquement, car il peut se mettre en veille. Utiliser une instance payante avant l’ouverture professionnelle.

## Structure

- `renewals/models.py` : données et relations métier ;
- `renewals/services.py` : lecture, validation et import Excel ;
- `renewals/views.py` : permissions, filtres et tableaux de bord ;
- `templates/` et `static/css/` : interface ;
- `renewals/tests.py` : tests des flux critiques.
