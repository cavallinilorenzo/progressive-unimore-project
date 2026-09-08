"""Le view di Progressive.

Class-based view ovunque, come il progetto d'esempio del corso (#22). Qui c'è
solo la dashboard: le sezioni arrivano una alla volta con i ticket della
mappa #53.
"""

from django.utils import timezone
from django.views.generic import TemplateView


class DashboardView(TemplateView):
    """`/` — il guscio della dashboard.

    In fase 1 la pagina non calcola niente: le sei analisi che la riempiono
    sono fase 2 (`docs/spec/04-analisi.md`). Esiste ora perché `/` è una delle
    cinque voci dell'header, e una voce che porta a un 404 non è un guscio.

    Volutamente **senza `LoginRequiredMixin`**: l'autenticazione non è ancora
    cablata (ticket #68), e una redirect verso un `/accounts/login/` che non
    esiste renderebbe il progetto non avviabile. Il mixin entra col ticket che
    porta il login, insieme ai dati che rendono la pagina personale.
    """

    template_name = "training/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["oggi"] = timezone.localdate()
        return context
