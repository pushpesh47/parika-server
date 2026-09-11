"""
PARIKA Skill Parser

Parses SKILL.md files with YAML frontmatter and markdown body.
Supports optional scripts/, references/, assets/ directories.
"""

from __future__ import annotations

import hashlib
import re
import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parika.core.skill_system.skill import Skill, SkillMetadata, SkillSource, generate_skill_id


@dataclass(slots=True, kw_only=True)
class ParsedSkill:
    """Result of parsing a skill directory."""
    metadata: SkillMetadata
    body: str
    scripts: dict[str, str]
    references: dict[str, str]
    assets: dict[str, bytes]
    content_hash: str


class SkillParser:
    """
    Parses Agent Skills format SKILL.md files.

    Expected structure:
    skill_dir/
      SKILL.md (required - YAML frontmatter + markdown body)
      scripts/ (optional - executable scripts)
      references/ (optional - reference files)
      assets/ (optional - binary assets)
    """

    FRONTMATTER_PATTERN = re.compile(r'^---\n(.*?)\n---', re.DOTALL)

    def __init__(self) -> None:
        pass  # Use standard yaml module

    def parse_skill_directory(self, skill_path: Path, source: SkillSource) -> Skill:
        """
        Parse a complete skill directory.

        Args:
            skill_path: Path to skill directory containing SKILL.md
            source: SkillSource this skill belongs to

        Returns:
            Skill object with metadata and discovered resources
        """
        skill_md_path = skill_path / "SKILL.md"
        if not skill_md_path.exists():
            raise ValueError(f"SKILL.md not found in {skill_path}")

        # Parse SKILL.md
        parsed = self._parse_skill_file(skill_md_path)

        # Load scripts
        scripts = self._load_scripts(skill_path)

        # Load references
        references = self._load_references(skill_path)

        # Load assets
        assets = self._load_assets(skill_path)

        # Create skill (metadata only for discovery)
        skill = Skill.create_discovered(
            source_id=source.id,
            path=str(skill_path),
            metadata=parsed.metadata,
            content_hash=parsed.content_hash,
        )

        return skill

    def parse_skill_file(self, skill_md_path: Path, source: SkillSource) -> Skill:
        """
        Parse just the SKILL.md file (for discovery).

        Args:
            skill_md_path: Path to SKILL.md file
            source: SkillSource this skill belongs to

        Returns:
            Skill object with metadata only
        """
        parsed = self._parse_skill_file(skill_md_path)

        skill = Skill.create_discovered(
            source_id=source.id,
            path=str(skill_md_path.parent),
            metadata=parsed.metadata,
            content_hash=parsed.content_hash,
        )

        return skill

    def _parse_skill_file(self, skill_md_path: Path) -> ParsedSkill:
        """Parse SKILL.md file into metadata and body."""
        content = skill_md_path.read_text(encoding='utf-8')
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # Extract frontmatter
        frontmatter_match = self.FRONTMATTER_PATTERN.match(content)
        if frontmatter_match:
            frontmatter_text = frontmatter_match.group(1)
            body = content[frontmatter_match.end():].strip()
            try:
                frontmatter = yaml.safe_load(frontmatter_text) or {}
            except yaml.YAMLError as e:
                raise ValueError(f"Invalid YAML frontmatter in {skill_md_path}: {e}")
        else:
            frontmatter = {}
            body = content.strip()

        # Parse metadata
        metadata = self._parse_metadata(frontmatter, skill_md_path.parent.name)

        return ParsedSkill(
            metadata=metadata,
            body=body,
            scripts={},
            references={},
            assets={},
            content_hash=content_hash,
        )

    def _parse_metadata(self, frontmatter: dict[str, Any], skill_name: str) -> SkillMetadata:
        """Parse frontmatter into SkillMetadata."""
        # Handle hermes-specific metadata
        hermes_meta = frontmatter.get('metadata', {}).get('hermes', {}) if 'metadata' in frontmatter else {}

        return SkillMetadata(
            name=frontmatter.get('name', skill_name),
            description=frontmatter.get('description', ''),
            version=frontmatter.get('version', '1.0.0'),
            author=frontmatter.get('author', ''),
            license=frontmatter.get('license', ''),
            platforms=tuple(frontmatter.get('platforms', [])),
            tags=tuple(frontmatter.get('tags', [])),
            related_skills=tuple(frontmatter.get('related_skills', [])),
            compatibility=frontmatter.get('compatibility', {}),
            allowed_tools=tuple(frontmatter.get('allowed_tools', [])),
            required_capabilities=tuple(frontmatter.get('required_capabilities', [])),
            required_skills=tuple(frontmatter.get('required_skills', [])),
            hermes_tags=tuple(hermes_meta.get('tags', [])),
            hermes_related_skills=tuple(hermes_meta.get('related_skills', [])),
        )

    def _load_scripts(self, skill_path: Path) -> dict[str, str]:
        """Load scripts from scripts/ directory."""
        scripts = {}
        scripts_dir = skill_path / "scripts"
        if scripts_dir.exists() and scripts_dir.is_dir():
            for script_file in scripts_dir.iterdir():
                if script_file.is_file():
                    try:
                        scripts[script_file.name] = script_file.read_text(encoding='utf-8')
                    except UnicodeDecodeError:
                        scripts[script_file.name] = script_file.read_bytes().decode('latin-1')
        return scripts

    def _load_references(self, skill_path: Path) -> dict[str, str]:
        """Load references from references/ directory."""
        references = {}
        refs_dir = skill_path / "references"
        if refs_dir.exists() and refs_dir.is_dir():
            for ref_file in refs_dir.iterdir():
                if ref_file.is_file():
                    try:
                        references[ref_file.name] = ref_file.read_text(encoding='utf-8')
                    except UnicodeDecodeError:
                        references[ref_file.name] = ref_file.read_bytes().decode('latin-1')
        return references

    def _load_assets(self, skill_path: Path) -> dict[str, bytes]:
        """Load assets from assets/ directory."""
        assets = {}
        assets_dir = skill_path / "assets"
        if assets_dir.exists() and assets_dir.is_dir():
            for asset_file in assets_dir.iterdir():
                if asset_file.is_file():
                    assets[asset_file.name] = asset_file.read_bytes()
        return assets

    def load_full_skill(self, skill: Skill) -> Skill:
        """
        Load full skill content (body, scripts, references, assets).

        Called on activation for progressive disclosure.
        """
        skill_path = Path(skill.path)
        skill_md_path = skill_path / "SKILL.md"

        if not skill_md_path.exists():
            raise ValueError(f"SKILL.md not found at {skill_md_path}")

        content = skill_md_path.read_text(encoding='utf-8')
        frontmatter_match = self.FRONTMATTER_PATTERN.match(content)
        if frontmatter_match:
            body = content[frontmatter_match.end():].strip()
        else:
            body = content.strip()

        scripts = self._load_scripts(skill_path)
        references = self._load_references(skill_path)
        assets = self._load_assets(skill_path)

        return skill.with_body(
            body=body,
            scripts=scripts,
            references=references,
            assets=assets,
        )


def parse_skill_file(skill_md_path: Path) -> tuple[SkillMetadata, str]:
    """
    Parse a SKILL.md file and return metadata and body.

    Args:
        skill_md_path: Path to SKILL.md

    Returns:
        Tuple of (SkillMetadata, body_content)
    """
    parser = SkillParser()
    parsed = parser._parse_skill_file(skill_md_path)
    return parsed.metadata, parsed.body