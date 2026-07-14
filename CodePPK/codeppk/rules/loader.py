"""Rule library loader.

Loads poppk_rules.json and supplementary markdown knowledge bases,
combining them into a unified context string for LLM prompts.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional


class RuleLibrary:
    """Loads and provides access to the PopPK rule library.

    The rule library consists of:
    - poppk_rules.json: Structured rules with namespaces (Regulatory, BioPhys,
      ModelingTechniques, DataStandards, ModelEvaluation, CovariateAnalysis,
      mAb_EarlyClinical, Reporting)
    - Supplementary markdown knowledge bases (e.g. NONMEM audit checklists)

    The loader resolves paths relative to PopPK_Agent/ or the project directory.
    """

    def __init__(self, rules_file: str = "poppk_rules.json",
                 base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else self._find_rules_dir()
        self.rules_file = rules_file
        self._rules_data: Optional[dict] = None
        self._knowledge_text: str = ""
        self._loaded = False

    @staticmethod
    def _find_rules_dir() -> Path:
        """Find the PopPK_Agent directory containing rules."""
        current = Path(__file__).resolve().parent
        for parent in [current, *current.parents]:
            candidate = parent / "PopPK_Agent" / "poppk_rules.json"
            if candidate.exists():
                return candidate.parent
        return Path.cwd()

    def load(self) -> "RuleLibrary":
        """Load all rule sources."""
        self._rules_data = self._load_json_rules()
        self._knowledge_text = self._load_knowledge_bases()
        self._loaded = True
        return self

    def _load_json_rules(self) -> dict:
        """Load the main JSON rule file."""
        sources = [s.strip() for s in self.rules_file.split(",") if s.strip()]
        for source in sources:
            if source.endswith(".json"):
                path = Path(source)
                if not path.is_absolute():
                    path = self.base_dir / source
                if path.exists():
                    return json.loads(path.read_text(encoding="utf-8"))
        # Fallback: try default name
        default = self.base_dir / "poppk_rules.json"
        if default.exists():
            return json.loads(default.read_text(encoding="utf-8"))
        return {}

    def _load_knowledge_bases(self) -> str:
        """Load supplementary markdown knowledge bases."""
        sources = [s.strip() for s in self.rules_file.split(",") if s.strip()]
        sections = []
        for source in sources:
            if source.endswith(".json"):
                continue
            path = Path(source)
            if not path.is_absolute():
                path = self.base_dir / source
            if path.exists() and path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore").strip()
                if text:
                    sections.append(f"### Rule Source: {path.name}\n\n{text[:80000]}")
        return "\n\n---\n\n".join(sections)

    @property
    def rules_data(self) -> dict:
        if not self._loaded:
            self.load()
        return self._rules_data or {}

    @property
    def namespaces(self) -> Dict[str, list]:
        """Get the rule namespaces dictionary."""
        return self.rules_data.get("rule_library", {}).get("namespaces", {})

    @property
    def metadata(self) -> dict:
        """Get rule library metadata."""
        return self.rules_data.get("rule_library", {}).get("metadata", {})

    def get_rules_by_namespace(self, namespace: str) -> List[dict]:
        """Get all rules in a specific namespace (without @ prefix)."""
        key = namespace if namespace.startswith("@") else f"@{namespace}"
        return self.namespaces.get(key, [])

    def get_rule(self, rule_id: str) -> Optional[dict]:
        """Find a specific rule by ID."""
        for rules in self.namespaces.values():
            for rule in rules:
                if rule.get("rule_id") == rule_id:
                    return rule
        return None

    def search_rules(self, keyword: str) -> List[dict]:
        """Search rules by keyword (case-insensitive)."""
        keyword_lower = keyword.lower()
        results = []
        for rules in self.namespaces.values():
            for rule in rules:
                searchable = " ".join([
                    rule.get("rule_description", ""),
                    rule.get("rule_id", ""),
                    " ".join(rule.get("keywords", [])),
                    rule.get("category", ""),
                    rule.get("subcategory", ""),
                ]).lower()
                if keyword_lower in searchable:
                    results.append(rule)
        return results

    def as_context(self, max_chars: int = 80000) -> str:
        """Get the full rule library as a context string for LLM prompts.

        Includes both the structured JSON rules and supplementary knowledge bases.
        """
        parts = []
        if self._rules_data:
            parts.append("### Structured Rule Library (poppk_rules.json)\n")
            parts.append(json.dumps(self._rules_data, indent=2, ensure_ascii=False))
        if self._knowledge_text:
            parts.append("\n\n---\n\n")
            parts.append(self._knowledge_text)
        full = "\n".join(parts)
        if len(full) > max_chars:
            full = full[:max_chars] + "\n\n[Rule library truncated for context limits]"
        return full

    def __str__(self) -> str:
        if not self._loaded:
            self.load()
        n_rules = sum(len(rules) for rules in self.namespaces.values())
        n_ns = len(self.namespaces)
        return f"RuleLibrary({n_ns} namespaces, {n_rules} rules)"
