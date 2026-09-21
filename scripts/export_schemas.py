from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.contracts import NaturalLanguageInput, TripRequest, PlanInput, ToolResult
from policy_import.models import ImportSpec, Snapshot, Binding, SearchRequest, SearchResponse
from policy_import.store import atomic_json

root = Path(__file__).resolve().parents[1]
for model in (NaturalLanguageInput, TripRequest, PlanInput, ToolResult, ImportSpec, Snapshot, Binding, SearchRequest, SearchResponse):
    atomic_json(root / "schemas" / f"{model.__name__}.json", model.model_json_schema())
print("9 JSON Schemas exported")
