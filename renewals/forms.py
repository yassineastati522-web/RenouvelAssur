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
        allowed_extensions = (
            (".csv", ".xlsx", ".xls")
            if self.import_type == "provisional"
            else (".xlsx", ".xls")
        )
        if not value.name.lower().endswith(allowed_extensions):
            if self.import_type == "provisional":
                raise forms.ValidationError(
                    "Le suivi provisoire doit être au format .csv, .xlsx ou .xls."
                )
            raise forms.ValidationError(
                "Le fichier doit être au format Excel (.xlsx ou .xls)."
            )
        if value.size > 15 * 1024 * 1024:
            raise forms.ValidationError("Le fichier ne doit pas dépasser 15 Mo.")
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
        label="Date d’échéance",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
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
