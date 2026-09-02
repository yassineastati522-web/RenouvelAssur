from django.contrib.auth.models import AbstractUser
from django.core import signing
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrateur"
        AGENT = "agent", "Agent"
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.AGENT)
    must_change_password = models.BooleanField(
        "changement de mot de passe requis",
        default=False,
    )

    @property
    def is_agency_admin(self):
        return self.is_superuser or self.role == self.Role.ADMIN


class Client(models.Model):
    name = models.CharField("assuré", max_length=255, db_index=True)
    phone = models.CharField("téléphone", max_length=40, blank=True, db_index=True)
    external_id = models.CharField("identifiant client", max_length=100, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
    def __str__(self): return self.name


class Contract(models.Model):
    class RenewalStatus(models.TextChoices):
        TO_CONTACT = "to_contact", "À contacter"
        TO_CONFIRM = "to_confirm", "À confirmer"
        WANTS = "wants", "Souhaite renouveler"
        QUOTE = "quote", "Devis demandé"
        CALLBACK = "callback", "Rappel demandé"
        RENEWED = "renewed", "Renouvelé"
        REFUSED = "refused", "Ne souhaite pas renouveler"
        COMPETITOR = "competitor", "Parti chez un concurrent"
        TERMINATED = "terminated", "Résilié"
        UNREACHABLE = "unreachable", "Injoignable"

    client = models.ForeignKey(Client, related_name="contracts", on_delete=models.PROTECT)
    assigned_agent = models.ForeignKey(User, related_name="contracts", null=True, blank=True, on_delete=models.SET_NULL)
    category = models.CharField("catégorie", max_length=100, blank=True)
    policy_number = models.CharField("police", max_length=100, db_index=True)
    agent_reference = models.CharField(max_length=100, blank=True)
    agent_code = models.CharField(max_length=100, blank=True, db_index=True)
    event = models.CharField("événement", max_length=200, blank=True, db_index=True)
    pack_code = models.CharField(max_length=100, blank=True)
    brand = models.CharField("marque", max_length=100, blank=True, db_index=True)
    registration = models.CharField("immatriculation", max_length=100, blank=True, db_index=True)
    net_premium = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    cash_premium = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    total_premium = models.DecimalField("prime TTC", max_digits=14, decimal_places=2, null=True, blank=True)
    net_payable = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    receipt = models.CharField("quittance", max_length=100, blank=True, db_index=True)
    effective_date = models.DateField("date d’effet", null=True, blank=True)
    end_date = models.DateField("date de fin", db_index=True)
    issue_date = models.DateField("date d’émission", null=True, blank=True)
    is_provisional = models.BooleanField("suivi provisoire actif", default=False, db_index=True)
    provisional_attestation = models.CharField(
        "attestation provisoire",
        max_length=100,
        blank=True,
    )
    provisional_due_date = models.DateField(
        "échéance provisoire",
        null=True,
        blank=True,
        db_index=True,
    )
    provisional_delivered_count = models.PositiveSmallIntegerField(
        "provisoires délivrées",
        default=0,
    )
    provisional_allowed_count = models.PositiveSmallIntegerField(
        "provisoires autorisées",
        default=0,
    )
    provisional_selected_count = models.PositiveSmallIntegerField(
        "provisoires choisies",
        default=0,
        help_text=(
            "0 signifie que le maximum autorisé est retenu tant que le client "
            "n’a pas fait un autre choix."
        ),
    )
    provisional_status = models.CharField(
        "état du suivi provisoire",
        max_length=100,
        blank=True,
    )
    provisional_calls_started_at = models.DateTimeField(
        "début des appels de la provisoire courante",
        null=True,
        blank=True,
        editable=False,
    )
    renewal_calls_started_at = models.DateTimeField(
        "début des appels de renouvellement après provisoire",
        null=True,
        blank=True,
        editable=False,
    )
    from_upcoming_file = models.BooleanField(
        "présent dans un fichier d’échéances",
        default=False,
    )
    renewal_status = models.CharField(max_length=20, choices=RenewalStatus.choices, default=RenewalStatus.TO_CONTACT, db_index=True)
    renewed_contract = models.OneToOneField("self", related_name="previous_contract", null=True, blank=True, on_delete=models.SET_NULL)
    manually_terminated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["end_date", "client__name"]
        constraints = [models.UniqueConstraint(fields=["policy_number", "receipt"], name="unique_policy_receipt")]

    def __str__(self): return f"{self.policy_number} — {self.client}"
    @property
    def days_remaining(self): return (self.end_date - timezone.localdate()).days
    @property
    def is_renewal_call(self):
        return bool(
            self.renewal_calls_started_at
            and self.renewal_calls_started_at <= timezone.now()
        )
    @property
    def contact_due_date(self):
        if self.is_provisional and self.provisional_due_date and not self.is_renewal_call:
            return self.provisional_due_date
        return self.end_date
    @property
    def contact_days_remaining(self):
        return (self.contact_due_date - timezone.localdate()).days
    @property
    def call_context_token(self):
        # Ne dépend pas de updated_at : un réimport identique reste valide.
        renewal_call = self.is_renewal_call
        return signing.Signer(salt="renewals.call-context").sign_object([
            self.pk,
            self.is_provisional,
            self.provisional_attestation,
            str(self.provisional_due_date or ""),
            self.provisional_delivered_count,
            str(self.provisional_calls_started_at or ""),
            renewal_call,
            str(self.renewal_calls_started_at) if renewal_call else "",
            str(self.end_date) if renewal_call else "",
        ])
    @property
    def provisional_remaining_count(self):
        return max(
            self.provisional_target_count - self.provisional_delivered_count,
            0,
        )
    @property
    def provisional_target_count(self):
        selected = (
            self.provisional_selected_count
            or self.provisional_allowed_count
        )
        return max(selected, self.provisional_delivered_count)
    @property
    def has_custom_provisional_plan(self):
        return bool(
            self.provisional_selected_count
            and self.provisional_selected_count
            != self.provisional_allowed_count
        )
    @property
    def provisional_action_label(self):
        if not self.is_provisional:
            return ""
        if self.provisional_remaining_count:
            return "Prochaine provisoire à remettre"
        return "Attestation définitive à remettre"
    @property
    def is_terminated(self):
        return bool(
            self.manually_terminated
            or self.renewal_status == self.RenewalStatus.TERMINATED
            or getattr(self, "termination", None) is not None
        )
    @property
    def display_amount(self):
        """Affiche la prime TTC active ou la prime négative de résiliation."""
        if not self.is_terminated:
            return self.total_premium
        termination = getattr(self, "termination", None)
        if termination is not None:
            return termination.display_premium
        if self.total_premium is not None and self.total_premium < 0:
            return self.total_premium
        return None
    @property
    def priority(self):
        if self.renewal_status == self.RenewalStatus.RENEWED: return "done"
        if self.renewal_status in {self.RenewalStatus.TERMINATED, self.RenewalStatus.REFUSED, self.RenewalStatus.COMPETITOR}: return "closed"
        if self.days_remaining <= 7: return "urgent"
        if self.days_remaining <= 15: return "high"
        return "normal"
    @property
    def last_interaction(self):
        prefetched = getattr(self, "_latest_interactions", None)
        if prefetched is not None:
            return prefetched[0] if prefetched else None
        return self.interactions.order_by("-occurred_at", "-pk").first()


class ImportBatch(models.Model):
    class ImportType(models.TextChoices):
        UPCOMING = "upcoming", "Échéances à venir"
        BORDEREAU = "bordereau", "Bordereau de production"
        PROVISIONAL = "provisional", "Suivi des provisoires"
        CONTACTS = "contacts", "Mise à jour des contacts"
        GENERAL = "general", "Fichier Excel standard"

    filename = models.CharField(max_length=255)
    import_type = models.CharField(
        "type d’import",
        max_length=20,
        choices=ImportType.choices,
        default=ImportType.GENERAL,
    )
    imported_at = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    total_rows = models.PositiveIntegerField(default=0)
    added_rows = models.PositiveIntegerField(default=0)
    updated_rows = models.PositiveIntegerField(default=0)
    rejected_rows = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    def __str__(self): return f"{self.filename} ({self.imported_at:%d/%m/%Y})"


class AuditEvent(models.Model):
    class Action(models.TextChoices):
        LOGIN_SUCCEEDED = "login_succeeded", "Connexion réussie"
        LOGIN_FAILED = "login_failed", "Échec de connexion"
        LOGOUT = "logout", "Déconnexion"
        PASSWORD_CHANGED = "password_changed", "Mot de passe modifié"
        MFA_ENABLED = "mfa_enabled", "Double authentification activée"
        MFA_FAILED = "mfa_failed", "Échec de double authentification"
        MFA_RESET = "mfa_reset", "Double authentification réinitialisée"
        SECURITY_ALERT = "security_alert", "Alerte de sécurité"
        SESSIONS_REVOKED = "sessions_revoked", "Sessions révoquées"
        AUDIT_EXPORTED = "audit_exported", "Journal d’audit exporté"
        DATA_EXPORTED = "data_exported", "Données métier exportées"
        USER_CREATED = "user_created", "Utilisateur créé"
        USER_UPDATED = "user_updated", "Utilisateur modifié"
        USER_DELETED = "user_deleted", "Utilisateur supprimé"
        IMPORT_COMPLETED = "import_completed", "Import terminé"
        IMPORT_FAILED = "import_failed", "Import échoué"
        CLIENT_UPDATED = "client_updated", "Client modifié"
        CONTRACT_UPDATED = "contract_updated", "Contrat modifié"
        CONTRACT_DELETED = "contract_deleted", "Contrat supprimé"
        TERMINATION_RECORDED = "termination_recorded", "Résiliation enregistrée"
        PROVISIONAL_PLAN_UPDATED = "provisional_plan_updated", "Plan provisoire modifié"
        CALL_RECORDED = "call_recorded", "Appel enregistré"
        RECORD_UPDATED = "record_updated", "Enregistrement modifié"
        RECORD_DELETED = "record_deleted", "Enregistrement supprimé"

    actor = models.ForeignKey(
        User,
        related_name="audit_events",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    action = models.CharField(max_length=40, choices=Action.choices, db_index=True)
    target_type = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-occurred_at", "-pk"]
        indexes = [
            models.Index(
                fields=["action", "occurred_at"],
                name="renewals_aud_action_06fc21_idx",
            ),
        ]

    def __str__(self):
        return f"{self.get_action_display()} — {self.occurred_at:%d/%m/%Y %H:%M}"


class CallInteraction(models.Model):
    class Channel(models.TextChoices):
        PHONE = "phone", "Téléphone"
        WHATSAPP = "whatsapp", "WhatsApp"
        SMS = "sms", "SMS"
        EMAIL = "email", "Email"
        VISIT = "visit", "Visite"
    class Result(models.TextChoices):
        NOT_CALLED = "not_called", "Pas encore appelé"
        ANSWERED = "answered", "Client appelé"
        VOICEMAIL = "voicemail", "Boîte vocale"
        UNREACHABLE = "unreachable", "Non joignable"
        OFF = "off", "Téléphone éteint"
        WRONG = "wrong", "Numéro incorrect"
        BUSY = "busy", "Occupé"
        CALLBACK = "callback", "Rappel demandé"

    contract = models.ForeignKey(Contract, related_name="interactions", on_delete=models.CASCADE)
    employee = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    channel = models.CharField(max_length=12, choices=Channel.choices, default=Channel.PHONE)
    call_result = models.CharField(max_length=20, choices=Result.choices)
    renewal_status = models.CharField(max_length=20, choices=Contract.RenewalStatus.choices)
    comment = models.TextField(blank=True)
    next_follow_up = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-occurred_at"]
    def __str__(self): return f"{self.contract} — {self.get_call_result_display()}"


QUICK_CALL_RESULTS = tuple(
    choice
    for choice in CallInteraction.Result.choices
    if choice[0] in {
        CallInteraction.Result.ANSWERED,
        CallInteraction.Result.VOICEMAIL,
        CallInteraction.Result.UNREACHABLE,
    }
)


class Renewal(models.Model):
    old_contract = models.OneToOneField(Contract, related_name="renewal_record", on_delete=models.CASCADE)
    new_contract = models.ForeignKey(Contract, related_name="source_renewals", on_delete=models.CASCADE)
    confirmed_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    confirmed_at = models.DateTimeField(auto_now_add=True)


class Termination(models.Model):
    contract = models.OneToOneField(Contract, related_name="termination", on_delete=models.CASCADE)
    date = models.DateField(default=timezone.localdate)
    reason = models.CharField(max_length=255, blank=True)
    legacy_net_payable = models.DecimalField(
        "ancienne valeur NET_A_PAYE (audit)",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
    )
    premium = models.DecimalField(
        "prime de résiliation",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    recorded_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(legacy_net_payable__isnull=True)
                    | models.Q(legacy_net_payable__lt=0)
                ),
                name="termination_legacy_net_negative_or_null",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(premium__isnull=True)
                    | models.Q(premium__lt=0)
                ),
                name="termination_premium_negative_or_null",
            ),
        ]

    @property
    def display_premium(self):
        """Retourne toujours la PRIME_TOTAL négative de la résiliation.

        Une ligne de résiliation isolée peut encore porter ce montant sur le
        contrat lui-même. La prime positive du contrat actif ne doit jamais
        être présentée comme la prime perdue de sa résiliation.
        """
        value = self.premium
        if value is None:
            value = self.contract.total_premium
            if value is None or value >= 0:
                return None
        if value == 0:
            return None
        return -abs(value)
