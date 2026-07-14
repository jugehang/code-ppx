"""
规则库引擎

加载和管理PopPK规则库，提供规则检索、匹配和注入能力。
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class RuleEngine:
    """PopPK规则库引擎"""

    def __init__(self, rules_path: str):
        self.rules_path = Path(rules_path)
        self.rules_data: Dict = {}
        self.namespaces: Dict[str, List[Dict]] = {}
        self._load()

    def _load(self):
        """加载规则库JSON"""
        try:
            with open(self.rules_path, 'r', encoding='utf-8') as f:
                self.rules_data = json.load(f)
            lib = self.rules_data.get("rule_library", {})
            self.namespaces = lib.get("namespaces", {})
            total = sum(len(rules) for rules in self.namespaces.values())
            meta = lib.get("metadata", {})
            logger.info(f"规则库加载成功: {len(self.namespaces)} 个命名空间, {total} 条规则 (v{meta.get('version', '?')})")
        except Exception as e:
            logger.error(f"规则库加载失败: {e}")
            self.namespaces = {}

    def get_namespace(self, name: str) -> List[Dict]:
        """获取指定命名空间的所有规则"""
        return self.namespaces.get(name, [])

    def search(self, keywords: List[str], namespaces: Optional[List[str]] = None) -> List[Dict]:
        """根据关键词搜索规则"""
        results = []
        search_namespaces = namespaces or list(self.namespaces.keys())

        for ns_name in search_namespaces:
            for rule in self.namespaces.get(ns_name, []):
                rule_keywords = rule.get("keywords", [])
                if any(kw.lower() in [rk.lower() for rk in rule_keywords] for kw in keywords):
                    results.append(rule)

        return results

    def get_rule(self, rule_id: str) -> Optional[Dict]:
        """根据Rule ID获取单条规则"""
        for rules in self.namespaces.values():
            for rule in rules:
                if rule.get("rule_id") == rule_id:
                    return rule
        return None

    def format_for_prompt(self, namespaces: Optional[List[str]] = None, max_rules: int = 50) -> str:
        """格式化规则库供AI Prompt使用"""
        lines = ["=== PopPK Rule Library ===\n"]
        target_namespaces = namespaces or list(self.namespaces.keys())
        count = 0

        for ns_name in target_namespaces:
            rules = self.namespaces.get(ns_name, [])
            if not rules:
                continue
            lines.append(f"\n--- {ns_name} ---")
            for rule in rules:
                if count >= max_rules:
                    lines.append(f"... ({sum(len(self.namespaces[n]) for n in target_namespaces) - count} more rules omitted)")
                    break
                rid = rule.get("rule_id", "?")
                desc = rule.get("rule_description", "")
                lines.append(f"[{rid}] {desc}")
                count += 1

        return "\n".join(lines)

    def format_namespace(self, name: str) -> str:
        """格式化单个命名空间"""
        rules = self.namespaces.get(name, [])
        if not rules:
            return f"命名空间 {name} 不存在或为空"

        lines = [f"--- {name} ---"]
        for rule in rules:
            rid = rule.get("rule_id", "?")
            cat = rule.get("category", "")
            sub = rule.get("subcategory", "")
            desc = rule.get("rule_description", "")
            lines.append(f"[{rid}] ({cat} > {sub})")
            lines.append(f"  {desc}")
            lines.append("")

        return "\n".join(lines)

    def get_metadata(self) -> Dict:
        """获取规则库元数据"""
        return self.rules_data.get("rule_library", {}).get("metadata", {})
