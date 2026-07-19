from datetime import timedelta
from decimal import Decimal
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .forms import ClientForm, ImportForm, InteractionForm
from .models import CallInteraction, Client, Contract, ImportBatch, Termination
from .services import import_contracts


QUICK_CALL_RESULTS = [
    (CallInteraction.Result.ANSWERED, "Client appelé"),
    (CallInteraction.Result.VOICEMAIL, "Boîte vocale"),
    (CallInteraction.Result.UNREACHABLE, "Non joignable"),
]


def scoped_contracts(user):
    qs = Contract.objects.select_related("client", "assigned_agent").prefetch_related("interactions")
    return qs if user.is_agency_admin else qs.filter(Q(assigned_agent=user) | Q(assigned_agent__isnull=True))


def exclude_terminated_contracts(qs):
    return qs.exclude(
        Q(renewal_status=Contract.RenewalStatus.TERMINATED)
        | Q(manually_terminated=True)
        | Q(termination__isnull=False)
    )


def apply_search(qs, request):
    query = request.GET.get("q", "").strip()
    if query:
        qs = qs.filter(Q(client__name__icontains=query) | Q(client__phone__icontains=query) |
            Q(policy_number__icontains=query) | Q(registration__icontains=query) |
            Q(receipt__icontains=query) | Q(agent_code__icontains=query))
    if request.GET.get("status"): qs = qs.filter(renewal_status=request.GET["status"])
    if request.GET.get("agent"): qs = qs.filter(agent_code__icontains=request.GET["agent"])
    return qs


def paginate(request, qs, per_page=25):
    return Paginator(qs, per_page).get_page(request.GET.get("page"))


@login_required
def dashboard(request):
    today = timezone.localdate(); qs = scoped_contracts(request.user)
    soon = exclude_terminated_contracts(
        qs.filter(end_date__range=(today, today + timedelta(days=30)))
    ).exclude(renewal_status=Contract.RenewalStatus.RENEWED)
    expired = exclude_terminated_contracts(
        qs.filter(end_date__lt=today)
    ).exclude(renewal_status=Contract.RenewalStatus.RENEWED)
    due_today = CallInteraction.objects.filter(contract__in=qs, next_follow_up__date__lte=today).values("contract").distinct().count()
    renewed = qs.filter(renewal_status=Contract.RenewalStatus.RENEWED)
    decided = qs.filter(renewal_status__in=[Contract.RenewalStatus.RENEWED, Contract.RenewalStatus.REFUSED, Contract.RenewalStatus.COMPETITOR])
    rate = round(renewed.count() * 100 / decided.count(), 1) if decided.exists() else 0
    stats = {
        "soon": soon.count(), "due_today": due_today,
        "answered": CallInteraction.objects.filter(contract__in=qs, call_result=CallInteraction.Result.ANSWERED).values("contract").distinct().count(),
        "unreachable": qs.filter(renewal_status=Contract.RenewalStatus.UNREACHABLE).count(), "renewed": renewed.count(),
        "not_renewed": expired.count(), "terminated": qs.filter(renewal_status=Contract.RenewalStatus.TERMINATED).count(),
        "at_risk": soon.aggregate(v=Sum("total_premium"))["v"] or Decimal("0"),
        "renewed_premium": renewed.aggregate(v=Sum("total_premium"))["v"] or Decimal("0"), "rate": rate,
    }
    return render(request, "renewals/dashboard.html", {"stats": stats, "upcoming": soon[:8], "followups": qs.filter(interactions__next_follow_up__date__lte=today).distinct()[:6]})


@login_required
def contract_list(request):
    today = timezone.localdate()
    try: days = min(max(int(request.GET.get("days", 30)), 1), 365)
    except ValueError: days = 30
    qs = exclude_terminated_contracts(
        scoped_contracts(request.user).filter(end_date__range=(today, today + timedelta(days=days)))
    ).exclude(renewal_status=Contract.RenewalStatus.RENEWED)
    qs = apply_search(qs, request)
    return render(request, "renewals/contract_list.html", {"contracts": paginate(request, qs), "days": days, "statuses": Contract.RenewalStatus.choices, "title": "Contrats à renouveler"})


@login_required
def expired_list(request):
    qs = exclude_terminated_contracts(
        scoped_contracts(request.user).filter(end_date__lt=timezone.localdate(), renewed_contract__isnull=True)
    ).exclude(renewal_status=Contract.RenewalStatus.RENEWED)
    return render(request, "renewals/contract_list.html", {"contracts": paginate(request, apply_search(qs, request)), "statuses": Contract.RenewalStatus.choices, "title": "Clients non renouvelés", "expired": True})


@login_required
def terminated_list(request):
    accessible_contracts = scoped_contracts(request.user)
    qs = Termination.objects.select_related("contract__client").filter(
        contract__in=accessible_contracts,
    ).annotate(
        client_terminated_count=Count(
            "contract__client__contracts__termination",
            filter=Q(contract__client__contracts__in=accessible_contracts),
            distinct=True,
        ),
    ).order_by("-date", "-pk")
    return render(request, "renewals/terminated_list.html", {"terminations": paginate(request, qs)})


@login_required
def contract_detail(request, pk):
    contract = get_object_or_404(scoped_contracts(request.user), pk=pk)
    form = InteractionForm(request.POST or None, initial={"renewal_status": contract.renewal_status})
    if request.method == "POST" and form.is_valid():
        interaction = form.save(commit=False); interaction.contract = contract; interaction.employee = request.user; interaction.save()
        contract.renewal_status = interaction.renewal_status; contract.save(update_fields=["renewal_status", "updated_at"])
        messages.success(request, "Interaction enregistrée dans l’historique.")
        missed = {CallInteraction.Result.VOICEMAIL, CallInteraction.Result.UNREACHABLE, CallInteraction.Result.OFF}
        missed_days = contract.interactions.filter(call_result__in=missed).dates("occurred_at", "day").count()
        if missed_days >= 3 and contract.renewal_status != Contract.RenewalStatus.UNREACHABLE:
            messages.warning(request, "Trois tentatives sans réponse sur des jours distincts : le statut « Injoignable » est suggéré.")
        return redirect("contract_detail", pk=contract.pk)
    return render(request, "renewals/contract_detail.html", {"contract": contract, "form": form})


@login_required
def call_checklist(request):
    allowed_contracts = scoped_contracts(request.user)
    if request.method == "POST":
        contract = get_object_or_404(allowed_contracts, pk=request.POST.get("contract"))
        result = request.POST.get("call_result", "")
        allowed_results = {value for value, _label in QUICK_CALL_RESULTS}
        if result not in allowed_results:
            messages.error(request, "Choisissez un résultat d’appel valide.")
        else:
            CallInteraction.objects.create(
                contract=contract,
                employee=request.user,
                channel=CallInteraction.Channel.PHONE,
                call_result=result,
                renewal_status=contract.renewal_status,
                comment=request.POST.get("comment", "").strip(),
            )
            messages.success(request, f"Appel de {contract.client.name} enregistré dans la checklist.")
        return redirect("call_checklist")

    latest_call = CallInteraction.objects.filter(
        contract=OuterRef("pk"),
        channel=CallInteraction.Channel.PHONE,
    ).order_by("-occurred_at", "-pk")
    closed_statuses = [
        Contract.RenewalStatus.RENEWED,
        Contract.RenewalStatus.TERMINATED,
        Contract.RenewalStatus.REFUSED,
        Contract.RenewalStatus.COMPETITOR,
    ]
    contracts = exclude_terminated_contracts(
        allowed_contracts.exclude(renewal_status__in=closed_statuses)
    ).annotate(
        last_call_result=Subquery(latest_call.values("call_result")[:1]),
        last_call_at=Subquery(latest_call.values("occurred_at")[:1]),
        call_attempts=Count(
            "interactions",
            filter=Q(interactions__channel=CallInteraction.Channel.PHONE),
            distinct=True,
        ),
    ).order_by("end_date", "client__name", "pk")

    query = request.GET.get("q", "").strip()
    if query:
        contracts = contracts.filter(
            Q(client__name__icontains=query)
            | Q(client__phone__icontains=query)
            | Q(policy_number__icontains=query)
        )

    due_filter = request.GET.get("due_filter", "all")
    today = timezone.localdate()
    if due_filter == "gt7":
        contracts = contracts.filter(end_date__gt=today + timedelta(days=7))
    elif due_filter == "gt15":
        contracts = contracts.filter(end_date__gt=today + timedelta(days=15))
    else:
        due_filter = "all"

    total_count = contracts.count()
    pending_count = contracts.filter(last_call_at__isnull=True).count()
    call_status = request.GET.get("call_status", "all")
    if call_status == "pending":
        contracts = contracts.filter(last_call_at__isnull=True)
    elif call_status == "completed":
        contracts = contracts.filter(last_call_at__isnull=False)
    else:
        call_status = "all"

    page = paginate(request, contracts, per_page=30)
    result_labels = dict(QUICK_CALL_RESULTS)
    for contract in page:
        contract.last_call_label = result_labels.get(contract.last_call_result, "À appeler")

    return render(request, "renewals/call_checklist.html", {
        "contracts": page,
        "call_results": QUICK_CALL_RESULTS,
        "call_status": call_status,
        "due_filter": due_filter,
        "query": query,
        "total_count": total_count,
        "pending_count": pending_count,
        "completed_count": total_count - pending_count,
    })


@login_required
def client_list(request):
    qs = Client.objects.annotate(contract_count=Count("contracts")).order_by("name", "pk")
    if not request.user.is_agency_admin: qs = qs.filter(contracts__in=scoped_contracts(request.user)).distinct()
    query = request.GET.get("q", "").strip()
    if query: qs = qs.filter(Q(name__icontains=query) | Q(phone__icontains=query) | Q(external_id__icontains=query))
    return render(request, "renewals/client_list.html", {"clients": paginate(request, qs)})


@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    allowed = scoped_contracts(request.user).filter(client=client)
    if not allowed.exists() and not request.user.is_agency_admin: return HttpResponseForbidden()
    form = ClientForm(request.POST or None, instance=client)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "Coordonnées mises à jour."); return redirect("client_detail", pk=pk)
    interactions = CallInteraction.objects.filter(contract__in=allowed).select_related("contract", "employee")
    return render(request, "renewals/client_detail.html", {"client": client, "contracts": allowed, "interactions": interactions, "form": form})


@login_required
@user_passes_test(lambda u: u.is_agency_admin)
def import_view(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        try:
            batch = import_contracts(upload, request.user)
        except ValueError as exc:
            form.add_error("file", str(exc))
        else:
            messages.success(request, f"Import terminé : {batch.added_rows} ajout(s), {batch.updated_rows} mise(s) à jour, {batch.rejected_rows} rejet(s).")
            return redirect("import_report", pk=batch.pk)
    return render(request, "renewals/import.html", {"form": form, "imports": ImportBatch.objects.all().order_by("-imported_at")[:20]})


@login_required
@user_passes_test(lambda u: u.is_agency_admin)
def import_report(request, pk):
    return render(request, "renewals/import_report.html", {"batch": get_object_or_404(ImportBatch, pk=pk)})
