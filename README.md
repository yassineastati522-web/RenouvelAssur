# RenouvelAssur

MVP de suivi des renouvellements de contrats pour une agence d’assurance. L’application est en français, responsive et fonctionne avec SQLite en local ou PostgreSQL en production.

## Fonctionnalités

- authentification sécurisée et rôles Administrateur / Agent ;
- tableau de bord : échéances, relances, renouvellements, primes et taux ;
- import des échéances à venir et des bordereaux Excel avec détection automatique du format, de la feuille et de la ligne d’en-têtes ;
- reconnaissance des colonnes du bordereau assureur, validation, mise à jour idempotente et rapport d’erreurs ;
- liste des échéances à 7, 15, 30 ou 60 jours, recherche et filtres ;
- fiche contrat avec trois résultats d’appel : Client appelé, Boîte vocale et Non joignable ;
- checklist des clients à appeler avec recherche, filtre et enregistrement rapide du résultat ;
- statut de renouvellement géré séparément du résultat d’appel ;
- historique complet et non destructif des interactions ;
- fiches clients, téléphone modifiable et portefeuille associé ;
- contrats expirés sans renouvellement et résiliations ;
- suggestion « Injoignable » après trois tentatives infructueuses sur des jours distincts ;
- administration des utilisateurs et attributions via `/admin/`.

## Installation locale

Prérequis : Python 3.11 ou plus récent.

```powershell
cd outputs\assurance_renewal
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Ouvrir `http://127.0.0.1:8000/`.

Comptes de démonstration :

- administrateur : `admin` / `Admin123!`
- agent : `agent` / `Agent123!`

Changez ces mots de passe avant toute utilisation réelle.

## Import Excel

Les fichiers `.xlsx` et les fichiers `.xls` fournis par l’assureur sont acceptés. Le système inspecte les premières lignes des feuilles du classeur afin de trouver automatiquement le tableau principal et son type.

Deux formats métier sont reconnus :

- le fichier des échéances à venir (`cat`, `numero_police`, `assure`, `date_debut`, `date_fin`, `marque`, `immatriculation`, etc.) alimente la liste des appels ;
- le bordereau de production (`POLICE`, `Nature Evenement`, `PRIME_TOTAL`, `NUM_QUITTANCE`, etc.) complète les contrats avec les primes et les événements.

La page d’importation présente une case dédiée à chaque format et refuse un fichier lorsqu’il est déposé dans la mauvaise case.

Colonnes minimales : `Police`, `Client` ou `Assuré`, et `Date Échéance` ou `Date Fin`. Les en-têtes du bordereau fourni sont reconnus, notamment :

- `POLICE`, `Nature Evenement`, `CLIENT`, `NUMERO_CIN` ;
- `DATE_EFFET`, `DATE_ECHEANCE`, `DATE_EMISSION` ;
- `PRIME_TOTAL`, `PRIME_NET`, `NET_A_PAYE` ;
- `TELEPHONE`, `NUM_QUITTANCE`, `IMMATDEF`, `IMMAPRO`.

Les dates `JJ/MM/AAAA` et `AAAA-MM-JJ` sont acceptées. Les montants peuvent utiliser une virgule décimale. `IMMATDEF` est prioritaire sur `IMMAPRO`, avec repli automatique lorsque l’immatriculation définitive est vide. Les lignes de total du bordereau sont ignorées.

La combinaison `Police + Quittance` identifie un contrat. Pour le fichier d’échéances, `cat` et `numero_police` sont réunis automatiquement. Lorsque la même police et la même échéance sont retrouvées à un jour près, les deux sources sont fusionnées sans doublon. Les cellules vides ne remplacent jamais des informations déjà connues.

Un second fichier Excel ne contenant que `Téléphone` et un identifiant (`Police`, `CIN` ou `Client`) peut mettre à jour les contacts existants.

## Tests

```powershell
python manage.py test
python manage.py check --deploy
```

## PostgreSQL et production

Copier `.env.example` vers `.env`, charger les variables dans l’environnement et définir `POSTGRES_*`. En production, utiliser une clé `DJANGO_SECRET_KEY` longue, `DJANGO_DEBUG=0`, HTTPS, un serveur WSGI/ASGI et une sauvegarde régulière de la base. Le fichier `.env` n’est jamais versionné.

## Déploiement sur Render avec Neon

Le fichier `render.yaml` et le script `build.sh` préparent automatiquement le service Django, les fichiers statiques et les migrations.

1. Dans Render, créer un **Blueprint** depuis le dépôt GitHub `yassineastati522-web/RenouvelAssur`.
2. Lorsque Render le demande, renseigner `DATABASE_URL` avec l’URL PostgreSQL fournie par Neon, comprenant `sslmode=require`.
3. Laisser Render générer `DJANGO_SECRET_KEY` et déployer la branche `main`.
4. Vérifier `https://<service>.onrender.com/health/`, puis se connecter avec le compte administrateur déjà présent dans Neon.
5. Pour un domaine personnalisé, ajouter le domaine dans Render, puis compléter `DJANGO_ALLOWED_HOSTS` et `DJANGO_CSRF_TRUSTED_ORIGINS`.

Le plan gratuit est adapté à la validation uniquement, car il peut se mettre en veille. Utiliser une instance payante avant l’ouverture professionnelle.

## Structure

- `renewals/models.py` : données et relations métier ;
- `renewals/services.py` : lecture, validation et import Excel ;
- `renewals/views.py` : permissions, filtres et tableaux de bord ;
- `templates/` et `static/css/` : interface ;
- `renewals/tests.py` : tests des flux critiques.
