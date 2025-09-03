from __future__ import annotations
from django import forms
from ..models import Meta


class MetaForm(forms.ModelForm):
    class Meta:
        model = Meta
        fields = ("descricao", "valor_alvo", "data_alvo", "prioridade", "status", "observacoes")
        widgets = {
            "descricao": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex.: Viagem ao Japão"}),
            "valor_alvo": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
            "data_alvo": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "prioridade": forms.NumberInput(attrs={"class": "form-control", "min": "0", "max": "9"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "observacoes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }
