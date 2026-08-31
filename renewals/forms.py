from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django_otp import devices_for_user
from django_otp.forms import otp_verification_failed
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import CallInteraction, Client, QUICK_CALL_RESULTS
from .services import validate_import_file


class AgencyAuthenticationForm(AuthenticationForm):
    """Ajoute un second facteur seulement aux administrateurs déjà équipés."""

    otp_token = forms.CharField(
        label="Code de sécurité",
        required=False,
        widget=forms.TextInput(attrs={
            "autocomplete": "one-time-code",
            "inputmode": "numeric",
        }),
    )

    def clean(self):
        cleaned = super().clean()
        user = self.get_user()
        if (
            settings.ADMIN_MFA_REQUIRED
            and user is not None
            and user.is_agency_admin
            and TOTPDevice.objects.filter(user=user, confirmed=True).exists()
        ):
            self._verify_admin_token(user, cleaned.get("otp_token", ""))
        return cleaned

    def _verify_admin_token(self, user, token):
        if not token:
            raise forms.ValidationError(
                "Le code de sécurité administrateur est obligatoire.",
                code="otp_required",
            )
        token = token.strip().replace(" ", "")
        with transaction.atomic():
            devices = list(devices_for_user(
                user,
                confirmed=True,
                for_verify=True,
            ))
            expected_type = (
                TOTPDevice
                if token.isdigit() and len(token) in {6, 8}
                else StaticDevice
            )
            for device in devices:
                if isinstance(device, expected_type) and device.verify_token(token):
                    user.otp_device = device
                    return
        otp_verification_failed.send(sender=self.__class__, user=user)
        raise forms.ValidationError(
            "Le code de sécurité est incorrect ou temporairement bloqué.",
            code="otp_invalid",
        )


class MFAActivationForm(forms.Form):
    otp_token = forms.CharField(
        label="Code à 6 chiffres",
        min_length=6,
        max_length=8,
        widget=forms.TextInput(attrs={
            "autocomplete": "one-time-code",
            "inputmode": "numeric",
            "placeholder": "000000",
        }),
    )


class ImportForm(forms.Form):
    file = forms.FileField(
        label="Fichier d’échéances ou bordereau Excel",
        help_text="Formats acceptés : .xlsx et les fichiers .xls fournis par l’assureur.",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel",
            }
        ),
    )

    def __init__(self, *args, import_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.import_type = import_type
        if import_type == "upcoming":
            self.fields["file"].label = "Fichier des échéances à venir"
            self.fields["file"].help_text = (
                "Fichier .xls ou .xlsx contenant cat, numero_police, "
                "date_debut et date_fin."
            )
        elif import_type == "bordereau":
            self.fields["file"].label = "Bordereau de production"
            self.fields["file"].help_text = (
                "Fichier .xlsx ou .xls contenant POLICE, Nature Evenement, "
                "PRIME_TOTAL et NUM_QUITTANCE."
            )
        elif import_type == "provisional":
            self.fields["file"].label = "Fichier de suivi des provisoires"
            self.fields["file"].help_text = (
                "Fichier .csv, .xlsx ou .xls contenant Police, "
                "N° Attestation, Date d’écheance et Provisoires délivrées."
            )
            self.fields["file"].widget.attrs["accept"] = (
                ".csv,.xlsx,.xls,text/csv,"
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
                "application/vnd.ms-excel"
            )

    def clean_file(self):
        value = self.cleaned_data["file"]
        try:
            validate_import_file(value, expected_type=self.import_type)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return value


class ProvisionalPlanForm(forms.Form):
    provisional_selected_count = forms.TypedChoiceField(
        label="Nombre de provisoires choisi par le client",
        coerce=int,
        choices=(),
    )

    def __init__(self, *args, contract, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = contract
        minimum = max(contract.provisional_delivered_count, 1)
        maximum = max(contract.provisional_allowed_count, minimum)
        self.fields["provisional_selected_count"].choices = [
            (
                count,
                f"{count} provisoire{'s' if count > 1 else ''}",
            )
            for count in range(minimum, maximum + 1)
        ]
        self.initial["provisional_selected_count"] = (
            contract.provisional_target_count
        )


class ExpiredDateFilterForm(forms.Form):
    date_from = forms.DateField(
        label="Date d’échéance du",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        label="Au",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean(self):
        cleaned = super().clean()
        date_from = cleaned.get("date_from")
        date_to = cleaned.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise forms.ValidationError(
                "La date de début doit être antérieure ou égale à la date de fin."
            )
        return cleaned


class ChecklistDateFilterForm(forms.Form):
    due_date = forms.DateField(
        label="Échéances à partir du",
        required=False,
        input_formats=["%d/%m/%Y", "%Y-%m-%d"],
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={
                "type": "date",
                "lang": "fr-MA",
                "title": "Format : jj/mm/aaaa",
            },
        ),
    )


class InteractionForm(forms.ModelForm):
    next_follow_up = forms.DateTimeField(
        label="Prochaine relance",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M"],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["call_result"].label = "Résultat de l’appel"
        self.fields["call_result"].choices = QUICK_CALL_RESULTS

    class Meta:
        model = CallInteraction
        fields = ["channel", "call_result", "renewal_status", "comment", "next_follow_up"]
        widgets = {
            "call_result": forms.RadioSelect(attrs={"class": "call-result-options"}),
            "comment": forms.Textarea(attrs={"rows": 3, "placeholder": "Notes utiles sur l’échange…"}),
        }


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["name", "phone", "external_id", "email"]
