from django import forms

from .models import CallInteraction, Client, Contract


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

    def clean_file(self):
        value = self.cleaned_data["file"]
        if not value.name.lower().endswith((".xlsx", ".xls")):
            raise forms.ValidationError("Le fichier doit être au format Excel (.xlsx ou .xls).")
        if value.size > 15 * 1024 * 1024:
            raise forms.ValidationError("Le fichier ne doit pas dépasser 15 Mo.")
        return value


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
        self.fields["call_result"].choices = [
            (CallInteraction.Result.ANSWERED, "Client appelé"),
            (CallInteraction.Result.VOICEMAIL, "Boîte vocale"),
            (CallInteraction.Result.UNREACHABLE, "Non joignable"),
        ]

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


class ContractStatusForm(forms.ModelForm):
    class Meta:
        model = Contract
        fields = ["renewal_status"]
