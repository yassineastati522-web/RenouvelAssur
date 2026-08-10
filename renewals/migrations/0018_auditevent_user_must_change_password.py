from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def require_password_rotation(apps, schema_editor):
    User = apps.get_model("renewals", "User")
    User.objects.filter(is_active=True).update(must_change_password=True)


class Migration(migrations.Migration):
    dependencies = [
        ("renewals", "0017_repair_post_import_terminations"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="must_change_password",
            field=models.BooleanField(
                default=False,
                verbose_name="changement de mot de passe requis",
            ),
        ),
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("login_succeeded", "Connexion réussie"),
                            ("login_failed", "Échec de connexion"),
                            ("logout", "Déconnexion"),
                            ("password_changed", "Mot de passe modifié"),
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
                ("target_type", models.CharField(blank=True, max_length=80)),
                ("target_id", models.CharField(blank=True, max_length=64)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("occurred_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-occurred_at", "-pk"],
            },
        ),
        migrations.AddIndex(
            model_name="auditevent",
            index=models.Index(
                fields=["action", "occurred_at"],
                name="renewals_aud_action_06fc21_idx",
            ),
        ),
        migrations.RunPython(
            require_password_rotation,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
