import sys

from app.ai.planner import generate_plan
from app.ai.provider import make_provider
from app.core.logging_setup import setup

setup("INFO")
prompt = sys.argv[1] if len(sys.argv) > 1 else "Crea una Jeep militare 4x4 verde con ruote grandi"

provider = make_provider()
print("provider:", provider.name)
plan, msg = generate_plan(prompt, provider)
print()
print("messaggio :", msg)
print("tentativi :", getattr(provider, "attempts", []))
print("template  :", plan.template, "| stile:", plan.style)
print("params    :", plan.params)
print("materiali :", [(m.name, m.base_color) for m in plan.materials])
print("note      :", plan.notes)
