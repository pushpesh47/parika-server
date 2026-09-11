"""
Tests for PARIKA Skill System
"""

import pytest
import tempfile
import yaml
from pathlib import Path
from unittest.mock import Mock

from parika.core.skill_system.skill import (
    Skill,
    SkillMetadata,
    SkillSource,
    SkillSourceType,
    SkillStatus,
    SkillTrustState,
    SkillSecurityStatus,
    SkillSecurityRecord,
)
from parika.core.skill_system.skill_parser import SkillParser, parse_skill_file
from parika.core.skill_system.skill_security import SkillSecurityScanner, SecurityFinding


class TestSkillMetadata:
    """Test skill metadata parsing."""

    def test_metadata_creation(self):
        """Test creating skill metadata."""
        metadata = SkillMetadata(
            name="test_skill",
            description="A test skill",
            version="1.0.0",
            author="Test Author",
            tags=("tag1", "tag2"),
            allowed_tools=("tool1", "tool2"),
        )
        assert metadata.name == "test_skill"
        assert metadata.description == "A test skill"
        assert metadata.version == "1.0.0"
        assert metadata.tags == ("tag1", "tag2")
        assert metadata.allowed_tools == ("tool1", "tool2")

    def test_metadata_to_dict(self):
        """Test metadata serialization."""
        metadata = SkillMetadata(
            name="test_skill",
            description="A test skill",
            version="1.0.0",
            tags=("tag1", "tag2"),
        )
        d = metadata.to_dict()
        assert d["name"] == "test_skill"
        assert d["tags"] == ["tag1", "tag2"]


class TestSkillSource:
    """Test skill source."""

    def test_source_creation(self):
        """Test creating skill source."""
        source = SkillSource(
            id="test_source",
            name="Test Source",
            source_type=SkillSourceType.USER_INSTALLED,
            location="/tmp/skills",
            priority=50,
        )
        assert source.id == "test_source"
        assert source.source_type == SkillSourceType.USER_INSTALLED
        assert source.enabled is True


class TestSkill:
    """Test skill model."""

    def test_skill_creation(self):
        """Test creating a skill."""
        metadata = SkillMetadata(
            name="test_skill",
            description="A test skill",
            version="1.0.0",
        )
        skill = Skill.create_discovered(
            source_id="source1",
            path="/tmp/skills/test_skill",
            metadata=metadata,
            content_hash="abc123",
        )
        assert skill.id.startswith("skill_")
        assert skill.source_id == "source1"
        assert skill.status == SkillStatus.DISCOVERED
        assert skill.trust_state == SkillTrustState.DISCOVERED
        assert skill.security_status == SkillSecurityStatus.PENDING

    def test_skill_activation(self):
        """Test skill activation."""
        metadata = SkillMetadata(
            name="test_skill",
            description="A test skill",
            version="1.0.0",
            allowed_tools=("tool1",),
        )
        skill = Skill.create_discovered(
            source_id="source1",
            path="/tmp/skills/test_skill",
            metadata=metadata,
            content_hash="abc123",
        )

        # Skill must be trusted to activate
        skill = skill.with_trust_state(SkillTrustState.TRUSTED)
        skill = skill.with_status(SkillStatus.SCANNED)

        activated = skill.activated()
        assert activated.status == SkillStatus.ACTIVE
        assert activated.activated_at is not None
        assert activated.activation_count == 1

    def test_skill_is_activatable(self):
        """Test skill activation checks."""
        metadata = SkillMetadata(
            name="test_skill",
            description="A test skill",
            version="1.0.0",
        )
        skill = Skill.create_discovered(
            source_id="source1",
            path="/tmp/skills/test_skill",
            metadata=metadata,
            content_hash="abc123",
        )

        # Not activatable initially
        assert not skill.is_activatable()

        # Trusted but not scanned
        skill = skill.with_trust_state(SkillTrustState.TRUSTED)
        assert not skill.is_activatable()

        # Trusted and scanned
        skill = skill.with_trust_state(SkillTrustState.TRUSTED, SkillSecurityStatus.CLEAN)
        assert skill.is_activatable()


class TestSkillParser:
    """Test SKILL.md parser."""

    def test_parse_simple_skill(self):
        """Test parsing a simple SKILL.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "test_skill"
            skill_dir.mkdir()

            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text("""---
name: test_skill
description: A test skill
version: 1.0.0
tags: [test, example]
allowed_tools: [read_file, write_file]
---

# Test Skill

This is a test skill body.
""")

            parser = SkillParser()
            metadata, body = parse_skill_file(skill_md)

            assert metadata.name == "test_skill"
            assert metadata.description == "A test skill"
            assert metadata.version == "1.0.0"
            assert metadata.tags == ("test", "example")
            assert metadata.allowed_tools == ("read_file", "write_file")
            assert "This is a test skill body" in body

    def test_parse_skill_with_hermes_metadata(self):
        """Test parsing SKILL.md with Hermes metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "hermes_skill"
            skill_dir.mkdir()

            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text("""---
name: hermes_skill
description: A Hermes skill
version: 2.0.0
metadata:
  hermes:
    tags: [hermes, test]
    related_skills: [other_skill]
---

# Hermes Skill

Hermes skill body.
""")

            parser = SkillParser()
            metadata, body = parse_skill_file(skill_md)

            assert metadata.name == "hermes_skill"
            assert metadata.hermes_tags == ("hermes", "test")
            assert metadata.hermes_related_skills == ("other_skill",)

    def test_parse_skill_directory_discovery(self):
        """Test parsing a skill directory during discovery (metadata only)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "full_skill"
            skill_dir.mkdir()

            # SKILL.md
            (skill_dir / "SKILL.md").write_text("""---
name: full_skill
description: A skill with scripts
version: 1.0.0
allowed_tools: [terminal]
---

# Full Skill

Skill body.
""")

            # Scripts
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "setup.sh").write_text("#!/bin/bash\necho 'setup'")

            # References
            refs_dir = skill_dir / "references"
            refs_dir.mkdir()
            (refs_dir / "readme.txt").write_text("Reference content")

            # Parse - discovery only loads metadata
            parser = SkillParser()
            from parika.core.skill_system.skill import SkillSource, SkillSourceType
            source = SkillSource(
                id="test_source",
                name="Test",
                source_type=SkillSourceType.USER_INSTALLED,
                location=tmpdir,
            )
            skill = parser.parse_skill_directory(skill_dir, source)

            assert skill.metadata.name == "full_skill"
            # During discovery, scripts/references are NOT loaded (progressive disclosure)
            assert skill.scripts == {}
            assert skill.references == {}
            assert skill.body is None

    def test_load_full_skill_activation(self):
        """Test loading full skill content on activation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "full_skill"
            skill_dir.mkdir()

            # SKILL.md
            (skill_dir / "SKILL.md").write_text("""---
name: full_skill
description: A skill with scripts
version: 1.0.0
allowed_tools: [terminal]
---

# Full Skill

Skill body.
""")

            # Scripts
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "setup.sh").write_text("#!/bin/bash\necho 'setup'")

            # References
            refs_dir = skill_dir / "references"
            refs_dir.mkdir()
            (refs_dir / "readme.txt").write_text("Reference content")

            # Parse - discovery only
            parser = SkillParser()
            from parika.core.skill_system.skill import SkillSource, SkillSourceType
            source = SkillSource(
                id="test_source",
                name="Test",
                source_type=SkillSourceType.USER_INSTALLED,
                location=tmpdir,
            )
            skill = parser.parse_skill_directory(skill_dir, source)

            # Activate - load full content
            full_skill = parser.load_full_skill(skill)

            assert full_skill.metadata.name == "full_skill"
            assert full_skill.body is not None
            assert "Skill body" in full_skill.body
            assert "setup.sh" in full_skill.scripts
            assert "readme.txt" in full_skill.references
            assert full_skill.scripts["setup.sh"] == "#!/bin/bash\necho 'setup'"


class TestSkillSecurityScanner:
    """Test skill security scanner."""

    def _make_scanner(self):
        """Create scanner with mock dependencies."""
        event_bus = Mock()
        logger = Mock()
        logger.get_logger = Mock(return_value=Mock(info=Mock(), debug=Mock(), warning=Mock(), error=Mock()))
        return SkillSecurityScanner(event_bus=event_bus, logger=logger)

    def test_scan_clean_skill(self):
        """Test scanning a clean skill."""
        metadata = SkillMetadata(
            name="clean_skill",
            description="A clean skill",
            version="1.0.0",
        )
        skill = Skill.create_discovered(
            source_id="source1",
            path="/tmp/skills/clean_skill",
            metadata=metadata,
            content_hash="abc123",
        )
        skill = skill.with_body("# Clean Skill\n\nThis is safe.")

        scanner = self._make_scanner()
        findings = scanner._scan_text(skill.body, "body", skill.id)
        assert len(findings) == 0

    def test_scan_dangerous_patterns(self):
        """Test detection of dangerous patterns."""
        scanner = self._make_scanner()

        dangerous_code = """
import os
os.system("rm -rf /")
eval(user_input)
subprocess.run("ls", shell=True)
"""

        findings = scanner._scan_text(dangerous_code, "scripts/test.py", "skill1")
        
        # Should detect shell injection, code injection, etc.
        categories = {f.category for f in findings}
        assert "shell_injection" in categories
        assert "code_injection" in categories

    def test_allowed_patterns(self):
        """Test that allowed patterns don't trigger false positives."""
        scanner = self._make_scanner()

        safe_code = """
with open("file.txt", "r") as f:
    content = f.read()
import json
data = json.loads(content)
"""

        findings = scanner._scan_text(safe_code, "scripts/read.py", "skill1")
        # Should not find critical/high issues for read-only operations
        critical_high = [f for f in findings if f.severity in ("critical", "high")]
        assert len(critical_high) == 0


class TestSkillSecurityRecord:
    """Test security record."""

    def test_record_creation(self):
        """Test creating security record."""
        record = SkillSecurityRecord(
            id="scan_123",
            skill_id="skill_456",
            scan_result=SkillSecurityStatus.CLEAN,
            findings=(),
        )
        assert record.scan_result == SkillSecurityStatus.CLEAN
        assert record.findings == ()

    def test_record_with_findings(self):
        """Test record with findings."""
        findings = (
            {"severity": "high", "category": "shell_injection", "description": "Found shell injection"},
        )
        record = SkillSecurityRecord(
            id="scan_123",
            skill_id="skill_456",
            scan_result=SkillSecurityStatus.BLOCKED,
            findings=findings,
        )
        assert record.scan_result == SkillSecurityStatus.BLOCKED
        assert len(record.findings) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])