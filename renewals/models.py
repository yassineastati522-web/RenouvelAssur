from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrateur"
        AGENT = "agent", "Agent"
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.AGENT)

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
    def is_terminated(self): return self.manually_terminated or self.renewal_status == self.RenewalStatus.TERMINATED
    @property
    def priority(self):
        if self.renewal_status == self.RenewalStatus.RENEWED: return "done"
        if self.renewal_status in {self.RenewalStatus.TERMINATED, self.RenewalStatus.REFUSED, self.RenewalStatus.COMPETITOR}: return "closed"
        if self.days_remaining <= 7: return "urgent"
        if self.days_remaining <= 15: return "high"
        return "normal"
    @property
    def last_interaction(self): return self.interactions.order_by("-occurred_at").first()


class ImportBatch(models.Model):
    filename = models.CharField(max_length=255)
    imported_at = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    total_rows = models.PositiveIntegerField(default=0)
    added_rows = models.PositiveIntegerField(default=0)
    updated_rows = models.PositiveIntegerField(default=0)
    rejected_rows = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    def __str__(self): return f"{self.filename} ({self.imported_at:%d/%m/%Y})"


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


class Renewal(models.Model):
    old_contract = models.OneToOneField(Contract, related_name="renewal_record", on_delete=models.CASCADE)
    new_contract = models.ForeignKey(Contract, related_name="source_renewals", on_delete=models.CASCADE)
    confirmed_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    confirmed_at = models.DateTimeField(auto_now_add=True)


class Termination(models.Model):
    contract = models.OneToOneField(Contract, related_name="termination", on_delete=models.CASCADE)
    date = models.DateField(default=timezone.localdate)
    reason = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
