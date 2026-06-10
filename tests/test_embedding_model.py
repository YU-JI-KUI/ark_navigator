"""Embedding 部署 GPU fail-fast 的单元测试

回归场景：USE_GPU=true 但运行时 CUDA 不可用（容器没分到 GPU / torch 是 CPU 构建），
此前会静默降级到 CPU 带病上线，现在必须在副本启动时直接失败。
"""
from unittest.mock import MagicMock, patch

import pytest

from ark_nav.config import settings
from ark_nav.core.models.embedding_model import EmbeddingModelDeployment

# @serve.deployment 包装后的原始类
_RawDeployment = EmbeddingModelDeployment.func_or_class


def test_embedding_init_fails_fast_when_gpu_required_but_unavailable(monkeypatch):
    # Arrange：要求 GPU，但 CUDA 不可用
    monkeypatch.setattr(settings, "use_gpu", True)

    # Act / Assert：副本启动直接失败，而不是静默降级到 CPU
    with patch("torch.cuda.is_available", return_value=False):
        with pytest.raises(RuntimeError, match="USE_GPU=true"):
            _RawDeployment()


def test_embedding_init_uses_cuda_when_gpu_required_and_available(monkeypatch):
    # Arrange
    monkeypatch.setattr(settings, "use_gpu", True)

    # Act
    with patch("torch.cuda.is_available", return_value=True), \
         patch("sentence_transformers.SentenceTransformer", MagicMock()):
        instance = _RawDeployment()

    # Assert
    assert instance.device == "cuda"


def test_embedding_init_cpu_mode_unaffected(monkeypatch):
    # Arrange：显式 CPU 模式不受 fail-fast 影响
    monkeypatch.setattr(settings, "use_gpu", False)

    # Act
    with patch("sentence_transformers.SentenceTransformer", MagicMock()):
        instance = _RawDeployment()

    # Assert
    assert instance.device == "cpu"
