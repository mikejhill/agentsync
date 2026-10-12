"""Validate performance statistics and corpus dimensions independently of timing."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.quality_tools import Corpus, PerformanceGate


class TestQualityGates:
    """A fast ordinary suite verifies the dedicated gate's decision boundaries."""

    @pytest.mark.parametrize(
        ("current", "baseline", "regression"),
        [
            ([2.0] * 5, [1.0] * 5, True),
            ([1.19] * 5, [1.0] * 5, False),
            ([1.0, 3.0, 0.5, 4.0, 1.0], [1.0] * 5, False),
        ],
    )
    def test_statistical_regression(
        self, current: list[float], baseline: list[float], *, regression: bool
    ) -> None:
        """Only significant >20% regressions fail the performance gate."""
        assert PerformanceGate.regression(current, baseline) is regression

    def test_sample_requirement(self) -> None:
        """Insufficient observations cannot be used as release evidence."""
        with pytest.raises(ValueError, match="five"):
            PerformanceGate.regression([1.0], [1.0])

    def test_exact_corpus_size(self, tmp_path: Path) -> None:
        """Corpus generation guarantees customization, file, and byte dimensions."""
        corpus = Corpus(3, 12, 4096)
        corpus.create(tmp_path)
        files = [file for file in tmp_path.rglob("*") if file.is_file()]
        assert len(files) == 12
        assert sum(file.stat().st_size for file in files) == 4096
        assert len(list(tmp_path.glob("skills/*/SKILL.md"))) == 3
