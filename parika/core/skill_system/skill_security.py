"""
PARIKA Skill Security Scanner

Scans skills for security issues including:
- Dangerous shell commands
- File system access patterns
- Network access
- Code injection vectors
- Suspicious imports
- Permission escalation attempts
"""

from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.skill_system.skill import Skill, SkillSecurityRecord, SkillSecurityStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class SecurityFinding:
    """A security finding from skill scanning."""
    severity: str  # "critical", "high", "medium", "low", "info"
    category: str
    description: str
    location: str  # "body", "scripts", "references"
    line_number: int | None = None
    code_snippet: str | None = None
    recommendation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "description": self.description,
            "location": self.location,
            "line_number": self.line_number,
            "code_snippet": self.code_snippet,
            "recommendation": self.recommendation,
        }


class SkillSecurityScanner:
    """
    Scans skills for security issues.

    Produces a SkillSecurityRecord with findings and overall security status.
    """

    # Patterns for dangerous operations
    DANGEROUS_PATTERNS = [
        # Shell command injection
        (r'\bsubprocess\.(run|call|Popen|check_output)\s*\([^)]*shell\s*=\s*True', "shell_injection", "critical"),
        (r'\bos\.system\s*\(', "shell_injection", "critical"),
        (r'\bos\.popen\s*\(', "shell_injection", "critical"),
        (r'\beval\s*\(', "code_injection", "critical"),
        (r'\bexec\s*\(', "code_injection", "critical"),
        (r'\bcompile\s*\(', "code_injection", "high"),

        # File system access
        (r'\bopen\s*\([^)]*[\'"]w[\'"]', "file_write", "medium"),
        (r'\bopen\s*\([^)]*[\'"]a[\'"]', "file_write", "medium"),
        (r'\bshutil\.(rmtree|move|copy)', "file_operation", "medium"),
        (r'\bos\.(remove|unlink|rmdir|mkdir|makedirs)', "file_operation", "medium"),
        (r'\bpathlib\.Path\.[^)]*(write|unlink|mkdir|rmdir)', "file_operation", "medium"),

        # Network access
        (r'\b(requests|urllib|httpx|aiohttp)\.', "network_access", "medium"),
        (r'\bsocket\.(socket|create_connection)', "network_access", "medium"),
        (r'\bhttp\.client', "network_access", "medium"),
        (r'\bftplib|telnetlib', "network_access", "high"),

        # Process execution
        (r'\bsubprocess\.(run|call|Popen)', "process_execution", "high"),
        (r'\bmultiprocessing\.(Process|Pool)', "process_execution", "medium"),

        # Privilege escalation
        (r'\bos\.setuid|os\.setgid|os\.seteuid', "privilege_escalation", "critical"),
        (r'\bsudo\s+', "privilege_escalation", "high"),

        # Data exfiltration
        (r'\b(shutil\.make_archive|tarfile|zipfile)\.', "data_packaging", "medium"),
        (r'\bbase64\.(encode|decode)', "encoding", "low"),
        (r'\bpickle\.(loads|dumps)', "serialization", "high"),

        # Crypto operations
        (r'\bhashlib\.(md5|sha1)\s*\(', "weak_crypto", "medium"),
        (r'\bCrypto\.|cryptography\.', "crypto_operation", "medium"),

        # Environment access
        (r'\bos\.environ\s*\[', "env_access", "low"),
        (r'\bdotenv|python-dotenv', "env_access", "low"),
    ]

    # Allowed patterns (reduce severity)
    ALLOWED_PATTERNS = [
        # Read-only file operations are generally OK
        (r'\bopen\s*\([^)]*[\'"]r[\'"]', "file_read", "info"),
        (r'\bpathlib\.Path\.(read_text|read_bytes|readlink|stat)', "file_read", "info"),
        (r'\bjson\.(load|loads)', "data_parse", "info"),
        (r'\byaml\.safe_load', "data_parse", "info"),
        (r'\bcsv\.reader', "data_parse", "info"),
    ]

    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
        strict_mode: bool = False,
    ) -> None:
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)
        self._strict_mode = strict_mode

        # Compile patterns
        self._dangerous_patterns = [
            (re.compile(pattern), category, severity)
            for pattern, category, severity in self.DANGEROUS_PATTERNS
        ]
        self._allowed_patterns = [
            (re.compile(pattern), category, severity)
            for pattern, category, severity in self.ALLOWED_PATTERNS
        ]

    def scan_skill(self, skill: Skill) -> SkillSecurityRecord:
        """
        Perform full security scan of a skill.

        Args:
            skill: Skill to scan (must have body, scripts, references loaded)

        Returns:
            SkillSecurityRecord with findings and overall status
        """
        start_time = datetime.now(UTC)
        scan_id = f"scan_{hashlib.sha256(f'{skill.id}{start_time.isoformat()}'.encode()).hexdigest()[:16]}"

        findings = []

        # Scan skill body (markdown content)
        if skill.body:
            findings.extend(self._scan_text(skill.body, "body", skill.id))

        # Scan scripts
        for script_name, script_content in skill.scripts.items():
            findings.extend(self._scan_text(script_content, f"scripts/{script_name}", skill.id))

        # Scan references
        for ref_name, ref_content in skill.references.items():
            findings.extend(self._scan_text(ref_content, f"references/{ref_name}", skill.id))

        # Determine overall security status
        security_status = self._determine_security_status(findings)

        scan_duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        record = SkillSecurityRecord(
            id=scan_id,
            skill_id=skill.id,
            scan_result=security_status,
            findings=tuple(f.to_dict() for f in findings),
            scanned_at=datetime.now(UTC),
            scanner_version="1.0.0",
            scan_duration_ms=scan_duration,
        )

        self._event_bus.publish("skill.security_scanned", {
            "skill_id": skill.id,
            "scan_id": scan_id,
            "status": security_status.value,
            "findings_count": len(findings),
        })

        self._logger.info(
            "Scanned skill '%s': %s (%d findings)",
            skill.id,
            security_status.value,
            len(findings),
        )

        return record

    def _scan_text(self, text: str, location: str, skill_id: str) -> list[SecurityFinding]:
        """Scan text content for security issues."""
        findings = []
        lines = text.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Check dangerous patterns
            for pattern, category, severity in self._dangerous_patterns:
                match = pattern.search(line)
                if match:
                    # Check if this matches an allowed pattern
                    allowed = False
                    for allowed_pattern, _, _ in self._allowed_patterns:
                        if allowed_pattern.search(line):
                            allowed = True
                            break

                    if not allowed or self._strict_mode:
                        findings.append(SecurityFinding(
                            severity=severity,
                            category=category,
                            description=f"Potential {category.replace('_', ' ')} detected",
                            location=location,
                            line_number=line_num,
                            code_snippet=line.strip()[:200],
                            recommendation=self._get_recommendation(category),
                        ))

        return findings

    def _determine_security_status(self, findings: list[SecurityFinding]) -> SkillSecurityStatus:
        """Determine overall security status from findings."""
        if not findings:
            return SkillSecurityStatus.CLEAN

        # Check for critical findings
        has_critical = any(f.severity == "critical" for f in findings)
        has_high = any(f.severity == "high" for f in findings)
        has_medium = any(f.severity == "medium" for f in findings)

        if has_critical:
            return SkillSecurityStatus.BLOCKED
        elif has_high:
            return SkillSecurityStatus.BLOCKED if self._strict_mode else SkillSecurityStatus.WARNING
        elif has_medium:
            return SkillSecurityStatus.WARNING
        else:
            return SkillSecurityStatus.CLEAN

    def _get_recommendation(self, category: str) -> str:
        """Get recommendation for a finding category."""
        recommendations = {
            "shell_injection": "Avoid shell=True in subprocess. Use list arguments instead.",
            "code_injection": "Avoid eval/exec. Use safe alternatives like ast.literal_eval.",
            "file_write": "Ensure file writes are authorized through WorkspacePermissionManager.",
            "file_operation": "File operations should go through PARIKA's filesystem tools.",
            "network_access": "Network access should use PARIKA's approved network capabilities.",
            "process_execution": "Process execution should be authorized and sandboxed.",
            "privilege_escalation": "Privilege escalation is not permitted in autonomous execution.",
            "data_packaging": "Data packaging operations should be reviewed for exfiltration risk.",
            "encoding": "Encoding operations are generally safe but may indicate obfuscation.",
            "serialization": "Avoid pickle for untrusted data. Use JSON or msgpack instead.",
            "weak_crypto": "Use strong cryptographic algorithms (SHA256+, AES-GCM).",
            "crypto_operation": "Cryptographic operations should use approved libraries.",
            "env_access": "Environment variable access should be through PARIKA's config system.",
        }
        return recommendations.get(category, "Review this code for security implications.")

    def scan_skill_directory(self, skill_path: Path) -> SkillSecurityRecord:
        """Scan a skill directory directly (for pre-registration scanning)."""
        from parika.core.skill_system.skill_parser import SkillParser
        from parika.core.skill_system.skill import SkillSource, SkillSourceType, generate_skill_id

        # Create a temporary source for scanning
        temp_source = SkillSource(
            id="scanner_temp",
            name="Scanner Temp",
            source_type=SkillSourceType.REMOTE,
            location=str(skill_path),
        )

        parser = SkillParser()
        skill = parser.parse_skill_file(skill_path / "SKILL.md", temp_source)
        skill = parser.load_full_skill(skill)

        return self.scan_skill(skill)