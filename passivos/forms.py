from django import forms
from .models import SaldoPassivo

class SaldoPassivoForm(forms.ModelForm):
    class Meta:
        model = SaldoPassivo
        fields = ["data", "valor_devido"]
        widgets = {
            "data": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "valor_devido": forms.NumberInput(attrs={"step": "0.01", "class": "form-control"}),
        }
