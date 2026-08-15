from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("renewals", "0019_alter_auditevent_action"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditevent",
            name="action",
            field=models.CharField(
                choices=[
                    ("login_succeeded", "Connexion réussie"),
                    ("login_failed", "Échec de connexion"),
                    ("logout", "Déconnexion"),
                    ("password_changed", "Mot de passe modifié"),
                    ("mfa_enabled", "Double authentification activée"),
                    ("mfa_failed", "Échec de double authentification"),
                    ("mfa_reset", "Double authentification réinitialisée"),
                    ("security_alert", "Alerte de sécurité"),
                    ("sessions_revoked", "Sessions révoquées"),
                    ("audit_exported", "Journal d’audit exporté"),
                    ("data_exported", "Données métier exportées"),
                    ("user_created", "Utilisateur créé"),
                    ("user_updated", "Utilisateur modifié"),
                    ("user_deleted", "Utilisateur supprimé"),
                    ("import_completed", "Import terminé"),
                    ("import_failed", "Import échoué"),
                    ("client_updated", "Client modifié"),
                    ("contract_updated", "Contrat modifié"),
                    ("contract_deleted", "Contrat supprimé"),
                    ("termination_recorded", "Résiliation enregistrée"),
                    ("provisional_plan_updated", "Plan provisoire modifié"),
                    ("call_recorded", "Appel enregistré"),
                    ("record_updated", "Enregistrement modifié"),
                    ("record_deleted", "Enregistrement supprimé"),
                ],
                db_index=True,
                max_length=40,
            ),
        ),
    ]
