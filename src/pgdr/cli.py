"""PGDR CLI — interactive terminal runner."""
from __future__ import annotations

from datetime import datetime, timezone

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from pgdr import __version__
from pgdr.enums import (
    DrivingStatus, ResolutionStatus, SessionState, TechnicalLevel, Urgency,
    VehicleLocation, VehicleState,
)
from pgdr.errors import ConfigurationError
from pgdr.models import (
    Answer, Consent, InitialComplaint, PreGarageDiagnosticRequest,
    UserContext, VehicleIdentityContext,
)
from pgdr.session_controller import SessionController

console = Console()


def _header(text: str) -> None:
    console.print(Panel(text, style="bold blue"))


def _warning(text: str) -> None:
    console.print(Panel(text, style="bold red"))


def _success(text: str) -> None:
    console.print(Panel(text, style="bold green"))


def _config_failure(exc: ConfigurationError) -> None:
    """P0 fail-closed boundary. A ConfigurationError means the safety
    envelope could not be validated — PGDR must refuse to run. This
    prints an explicit TECHNICAL failure, deliberately NOT styled or
    worded like a safety instruction (no "do not drive", no triage
    language) because that would be fabricating a safety conclusion from
    a configuration error rather than reporting the actual problem."""
    console.print(Panel(
        "PGDR CONFIGURATION INVALID — refusing to start.\n\n"
        f"{exc}\n\n"
        "This is a software configuration problem, not a vehicle safety "
        "assessment. No diagnostic session was started.",
        title="PGDR UNAVAILABLE",
        style="bold white on red",
    ))


@click.group()
@click.version_option(version=__version__, prog_name="pgdr")
def main() -> None:
    """Pre-Garage Diagnostic Runner (PGDR) v2"""


@main.command()
@click.option("--request-id", default=lambda: f"PGDR-REQ-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}")
@click.option("--locale", default="fr-FR")
@click.option("--vir-id", required=True, help="Vehicle Identity Resolver resolution ID")
@click.option("--vir-status", default="provisionally_resolved", type=click.Choice([e.value for e in ResolutionStatus]))
@click.option("--complaint", required=True, help="Free-text initial complaint")
@click.option("--location", default="home", type=click.Choice([e.value for e in VehicleLocation]))
@click.option("--vehicle-state", default="engine_off", type=click.Choice([e.value for e in VehicleState]))
@click.option("--urgency", default="unknown", type=click.Choice([e.value for e in Urgency]))
@click.option("--driving-status", default="parked", type=click.Choice([e.value for e in DrivingStatus]))
@click.option("--technical-level", default="low", type=click.Choice([e.value for e in TechnicalLevel]))
@click.option("--media-consent/--no-media-consent", default=False)
@click.option("--storage-consent/--no-storage-consent", default=False)
@click.option("--json-output", is_flag=True, help="Also print the final result as JSON")
@click.option("--non-interactive", is_flag=True, help="Skip questions (answers 'je ne sais pas' to everything)")
def run(request_id, locale, vir_id, vir_status, complaint, location, vehicle_state,
        urgency, driving_status, technical_level, media_consent, storage_consent,
        json_output, non_interactive) -> None:
    """Start a diagnostic session from the command line."""
    _header(f"Pre-Garage Diagnostic Runner v{__version__}")

    request = PreGarageDiagnosticRequest(
        request_id=request_id,
        locale=locale,
        vehicle_identity_context=VehicleIdentityContext(
            resolution_id=vir_id,
            resolution_status=ResolutionStatus(vir_status),
        ),
        initial_complaint=InitialComplaint(
            free_text=complaint,
            current_vehicle_location=VehicleLocation(location),
            vehicle_current_state=VehicleState(vehicle_state),
            perceived_urgency=Urgency(urgency),
        ),
        user_context=UserContext(
            driving_status=DrivingStatus(driving_status),
            technical_level=TechnicalLevel(technical_level),
        ),
        consent=Consent(
            media_analysis_allowed=media_consent,
            report_storage_allowed=storage_consent,
        ),
    )

    try:
        controller = SessionController()
    except ConfigurationError as exc:
        _config_failure(exc)
        raise SystemExit(1) from None
    session = controller.start(request)

    if session.state == SessionState.ESCALATED:
        _warning("SIGNAL DE SÉCURITÉ DÉTECTÉ")
        console.print(f"[bold red]Niveau :[/bold red] {session.safety_triage.level.value}")
        console.print(f"[bold red]Instruction :[/bold red] {session.safety_triage.user_instruction}")
        if session.safety_triage.roadside_assistance_recommended:
            console.print("[yellow]-> Assistance dépannage recommandée[/yellow]")
        if session.safety_triage.emergency_services_required:
            console.print("[red]-> APPELEZ LES SECOURS[/red]")
        if json_output:
            click.echo(session.result.model_dump_json(indent=2))
        return

    while session.pending_questions:
        q = session.pending_questions[0]
        console.print(f"\n[bold cyan]Question :[/bold cyan] {q.prompt}")
        if q.selection_reason:
            console.print(f"[dim]Pourquoi : {q.selection_reason}[/dim]")

        if non_interactive:
            answer = Answer(question_id=q.question_id, value=_default_value(q))
        else:
            answer = _prompt_answer(q)

        session = controller.submit_answer(session, answer)

    _success("Session terminée — rapports générés")
    _print_result(session)
    if json_output:
        click.echo("\n--- JSON ---")
        click.echo(session.result.model_dump_json(indent=2))


def _default_value(q):
    if q.answer_type.value == "yes_no":
        return False
    if q.answer_type.value == "multiple_choice":
        return ["je ne sais pas"]
    return "je ne sais pas"


def _prompt_answer(q) -> Answer:
    at = q.answer_type.value
    if at == "yes_no":
        val = Confirm.ask("Votre réponse", default=False)
        return Answer(question_id=q.question_id, value=val)
    if at == "single_choice" and q.choices:
        choices = q.choices if "je ne sais pas" in q.choices else q.choices + ["je ne sais pas"]
        val = Prompt.ask("Choisissez", choices=choices, default="je ne sais pas")
        return Answer(question_id=q.question_id, value=val)
    if at == "multiple_choice" and q.choices:
        choices = q.choices if "je ne sais pas" in q.choices else q.choices + ["je ne sais pas"]
        raw = Prompt.ask(f"Choix parmi {choices} (séparés par virgule)", default="je ne sais pas")
        vals = [v.strip() for v in raw.split(",")] if raw != "je ne sais pas" else ["je ne sais pas"]
        return Answer(question_id=q.question_id, value=vals)
    if at == "numeric":
        raw = Prompt.ask("Valeur", default="0")
        try:
            num = int(raw)
        except ValueError:
            num = float(raw)
        return Answer(question_id=q.question_id, value=num)
    if at == "media_upload":
        val = Prompt.ask("Chemin du fichier (ou 'aucun')", default="aucun")
        return Answer(question_id=q.question_id, value=None if val == "aucun" else val)
    val = Prompt.ask("Votre réponse", default="je ne sais pas")
    return Answer(question_id=q.question_id, value=val)


def _print_result(session) -> None:
    result = session.result
    us = result.user_summary
    console.print("\n[bold green]--- Synthèse pour l'automobiliste ---[/bold green]")
    console.print(f"[bold]Urgence :[/bold] {us.urgency.get('label', '')}")
    console.print(f"[italic]{us.urgency.get('explanation', '')}[/italic]")
    console.print("\n[bold]Observations :[/bold]")
    for obs in us.main_observations:
        console.print(f"  - {obs}")
    console.print("\n[bold]Actions :[/bold]")
    for act in us.next_actions:
        console.print(f"  -> {act}")
    console.print(f"\n[dim]{' | '.join(us.disclaimer)}[/dim]")

    console.print("\n[bold blue]--- Garage Preparation Report ---[/bold blue]")
    report = result.garage_preparation_report
    table = Table(title="Véhicule")
    table.add_column("Champ", style="cyan")
    table.add_column("Valeur", style="magenta")
    for k, v in report.vehicle.items():
        table.add_row(str(k), str(v))
    console.print(table)

    console.print(f"\n[bold]Problème signalé (verbatim) :[/bold]\n  {report.customer_reported_problem}")

    if report.systems_to_examine:
        console.print("\n[bold]Systèmes à examiner :[/bold]")
        for sys_ in report.systems_to_examine:
            console.print(f"  - {sys_['system_family']} (confiance : {sys_['confidence']})")

    if report.suggested_professional_checks:
        console.print("\n[bold]Contrôles suggérés :[/bold]")
        for chk in report.suggested_professional_checks:
            console.print(f"  -> {chk}")

    if report.unresolved_questions:
        console.print("\n[bold]Questions ouvertes :[/bold]")
        for q in report.unresolved_questions:
            console.print(f"  ? {q}")

    if report.limitations:
        console.print("\n[bold yellow]Limitations :[/bold yellow]")
        for lim in report.limitations:
            console.print(f"  ! {lim}")


@main.command()
@click.option("--json-output", is_flag=True, help="Print machine-readable JSON instead of a panel")
def readiness(json_output: bool) -> None:
    """P1 — Reports whether this PGDR instance is READY to safely accept
    diagnostic work (distinct from liveness — see
    runner_execution_contract.yaml). Exits 0 if READY, 1 if NOT_READY."""
    from pgdr.readiness import check_readiness

    report = check_readiness()

    if json_output:
        import json as json_module
        click.echo(json_module.dumps(report.as_dict(), indent=2))
    else:
        lines = []
        for c in report.checks:
            marker = "✓" if c.status.value == "ok" else "✗"
            kind = "required" if c.required else "optional"
            line = f"{marker} {c.name} ({kind}): {c.status.value}"
            if c.detail:
                line += f" — {c.detail}"
            lines.append(line)
        if not report.ready:
            lines.append(f"\nreason: {report.reason.value}")
        style = "bold green" if report.ready else "bold white on red"
        title = "PGDR READY" if report.ready else "PGDR NOT READY"
        console.print(Panel("\n".join(lines), title=title, style=style))

    if not report.ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
