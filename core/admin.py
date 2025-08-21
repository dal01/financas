from django.contrib import admin
from core.models import Categoria
from .models import Estabelecimento, AliasEstabelecimento, InstituicaoFinanceira, Membro


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nome", "categoria_pai")
    list_filter = ("categoria_pai",)
    search_fields = ("nome",)



@admin.register(Estabelecimento)
class EstabelecimentoAdmin(admin.ModelAdmin):
    list_display = ('nome_fantasia',)
    ordering = ('nome_fantasia',)
    search_fields = ('nome_fantasia',)

@admin.register(AliasEstabelecimento)
class AliasEstabelecimentoAdmin(admin.ModelAdmin):
    list_display = ('nome_alias', 'get_estabelecimento', 'get_mestre')
    search_fields = ('nome_alias', 'estabelecimento__nome_fantasia')
    list_filter = ('mestre',)

    def get_estabelecimento(self, obj):
        return obj.estabelecimento.nome_fantasia
    get_estabelecimento.short_description = 'Estabelecimento'

    def get_mestre(self, obj):
        return obj.mestre.nome_alias if obj.mestre else '-'
    get_mestre.short_description = 'Alias Mestre'

    # Optional: limitar seleção para evitar ciclos nos alias mestre
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "mestre":
            # Exclui o próprio alias da lista para evitar que ele seja seu próprio mestre
            if request._obj_:
                kwargs["queryset"] = AliasEstabelecimento.objects.exclude(pk=request._obj_.pk)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        # Guardar objeto atual para uso no formfield_for_foreignkey
        request._obj_ = obj
        return super().get_form(request, obj, **kwargs)



@admin.register(InstituicaoFinanceira)
class InstituicaoFinanceiraAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo")
    search_fields = ["nome"]
    list_filter = ("tipo",)



@admin.register(Membro)
class MembroAdmin(admin.ModelAdmin):
    list_display = ("nome",)
    search_fields = ("nome",)
    ordering = ("nome",)
