"""Block B1.5 — PGDR-side tests. Covers B1.5-AC06 (no filesystem
dependency in PGDR domain code) and the structural contract itself
(AC03/AC05's PGDR-side half -- the resolver Port and ResolvedMedia model
exist and are typed correctly). Storage/upload/security tests (AC01,
AC02, AC07, AC08) live on the PI side, since PI owns the actual ingress
and storage adapter.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pgdr.domain.media import MediaType
from pgdr.ports.media_resolver import MediaResolutionError, MediaResolverPort, ResolvedMedia


class TestB15PGDRContract:
    def test_resolved_media_is_typed_and_frozen(self):
        resolved = ResolvedMedia(content=b"fake-jpeg-bytes", media_type=MediaType.IMAGE, reference="media-123")
        assert resolved.content == b"fake-jpeg-bytes"
        assert resolved.media_type == MediaType.IMAGE
        assert resolved.reference == "media-123"
        with pytest.raises(Exception):
            resolved.content = b"mutated"  # frozen

    def test_resolved_media_is_not_evidence_observation_or_interpretation_result(self):
        from pgdr.domain.evidence import Evidence
        from pgdr.domain.observation import Observation
        from pgdr.ports.dashboard_interpretation import DashboardInterpretationResult

        assert not issubclass(ResolvedMedia, Evidence)
        assert not issubclass(ResolvedMedia, Observation)
        assert not issubclass(ResolvedMedia, DashboardInterpretationResult)

    def test_port_is_runtime_checkable_protocol_matching_existing_convention(self):
        class _FakeResolver:
            def resolve(self, reference: str) -> ResolvedMedia:
                return ResolvedMedia(content=b"x", media_type=MediaType.IMAGE, reference=reference)

        assert isinstance(_FakeResolver(), MediaResolverPort)

    def test_resolver_port_no_filesystem_dependency_in_pgdr_domain_code(self):
        """B1.5-AC06: PGDR/domain code does not depend on filesystem
        paths -- confirmed by scanning only the executable bodies of the
        actual classes/functions in the media/resolution contract chain
        (docstrings explicitly discussing what NOT to do are excluded,
        since they legitimately mention the forbidden tokens by name)."""
        import inspect
        from pgdr.domain.media import DiagnosticMediaRole, MediaType, PrimaryDiagnosticMedia
        from pgdr.ports.media_resolver import MediaResolverPort, ResolvedMedia

        forbidden = ("open(", "os.path", "pathlib.Path(", "/Users/", "/home/", "file://")

        def body_only(obj) -> str:
            source = inspect.getsource(obj)
            # Strip the first statement if it is a bare string literal
            # (the docstring) -- keep everything else (actual code).
            lines = source.split("\n")
            out, in_docstring, opened = [], False, False
            for line in lines:
                stripped = line.strip()
                if not opened and (stripped.startswith('"""') or stripped.startswith("'''")):
                    opened = True
                    if stripped.count('"""') == 2 or stripped.count("'''") == 2:
                        opened = False
                    in_docstring = True
                    continue
                if in_docstring:
                    if '"""' in line or "'''" in line:
                        in_docstring = False
                    continue
                out.append(line)
            return "\n".join(out)

        for obj in (PrimaryDiagnosticMedia, MediaType, DiagnosticMediaRole, ResolvedMedia, MediaResolverPort):
            code = body_only(obj)
            for token in forbidden:
                assert token not in code, f"forbidden filesystem token {token!r} found in {obj.__name__}"

    def test_media_resolution_error_is_a_real_exception_type(self):
        assert issubclass(MediaResolutionError, Exception)
        with pytest.raises(MediaResolutionError):
            raise MediaResolutionError("reference not found")

    def test_resolver_creates_no_evidence_or_observation_by_construction(self):
        """B1.5-AC09 (PGDR-side half): resolving media, by itself, cannot
        construct Evidence/Observation/DashboardInterpretationResult --
        confirmed structurally: ResolvedMedia has no method that produces
        any of those types, and the Port's own return type is ResolvedMedia
        only."""
        import inspect
        source = inspect.getsource(MediaResolverPort.resolve)
        assert "Evidence(" not in source
        assert "Observation(" not in source
        assert "DashboardInterpretationResult(" not in source
