from django import forms
from .models import SaldoInvestimento


class SaldoInvestimentoForm(forms.ModelForm):
    class Meta:
        model = SaldoInvestimento
        fields = ["data", "valor"]
        widgets = {
            "data": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "valor": forms.NumberInput(attrs={"step": "0.01", "class": "form-control"}),
        }
